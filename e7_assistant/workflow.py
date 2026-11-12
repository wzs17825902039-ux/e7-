"""用户打造流程的事务编排；驱动负责截图与界面操作。"""

from dataclasses import asdict, dataclass, replace
import math

from .rules import Equipment, Policy, evaluate
from .tasks import Cancelled, Ledger, Limits


@dataclass
class WorkflowOptions:
    source_index: int = 0
    slot: str = "helmet"
    craft_count: int = 10
    first_target: int = 3
    initial_disposal: str = "extract"
    rounds: int = 1
    scan_pages: int = 200
    action_interval: float = 0.2
    track_craft_gold: bool = False
    track_craft_consumption: bool = False
    legendary_set: str = ''
    legendary_count: int | None = None

    def __post_init__(self):
        from .rules import SLOTS
        if type(self.track_craft_gold) is not bool:
            raise ValueError('打造金币识别开关必须为布尔值')
        if type(self.track_craft_consumption) is not bool:
            raise ValueError('打造消耗统计开关必须为布尔值')
        if type(self.source_index) is not int or not 0 <= self.source_index < 5:
            raise ValueError("打造来源必须为0～4")
        from .custom_targets import SET_GROUPS
        if self.legendary_set and self.legendary_set not in SET_GROUPS[self.source_index]:
            raise ValueError('传说套装必须属于当前打造来源')
        if self.legendary_count is not None and (type(self.legendary_count) is not int or not 1<=self.legendary_count<=1000):
            raise ValueError('传说制作件数留空或填写1～1000')
        if self.slot not in SLOTS:
            raise ValueError("未知打造部位")
        if type(self.craft_count) is not int or self.craft_count not in (1, 10):
            raise ValueError("打造次数只允许1或10")
        if type(self.first_target) is not int or self.first_target not in (3, 6):
            raise ValueError("首轮强化阶段只允许+3或+6")
        if self.initial_disposal not in ("extract", "sell"):
            raise ValueError("初次清理只允许萃取或出售")
        for name in ("rounds", "scan_pages"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + "必须为正整数")
        if isinstance(self.action_interval, bool) or not isinstance(self.action_interval, (int, float)) or not math.isfinite(self.action_interval) or not .2 <= self.action_interval <= 5:
            raise ValueError("操作间隔必须为0.2～5秒")


@dataclass
class BatchItem:
    token: str
    equipment: Equipment
    selected: bool
    locked: bool | None = None


def record_speed_roll(before,after,target):
    result=[]
    for old,new in zip(before,after):
        if target>0 and old.selected and old.equipment.rarity=='red':
            rolls=new.equipment.enhancement//3-old.equipment.enhancement//3
            prior=0 if old.equipment.enhancement<3 else old.equipment.red_speed_misses
            hit=new.equipment.stats.get('speed',0)>old.equipment.stats.get('speed',0)
            misses=(prior+int(not hit) if rolls==1 and prior is not None else
                    prior+rolls if rolls>1 and not hit and prior is not None else None)
            new=replace(new,equipment=replace(new.equipment,red_speed_misses=misses))
        if target>0 and old.selected and old.equipment.rarity=='red' and old.equipment.enhancement<6 and new.equipment.enhancement<9:
            hit=new.equipment.stats.get('speed',0)>old.equipment.stats.get('speed',0)
            prior=old.equipment.early_speed_increased
            early=True if hit or prior is True else False if old.equipment.enhancement<3 or prior is False else None
            new=replace(new,equipment=replace(new.equipment,early_speed_increased=early))
        if old.selected and old.equipment.rarity=='purple':
            hit=(new.equipment.stats.get('speed',0)>old.equipment.stats.get('speed',0)) if target!=12 else None
            new=replace(new,equipment=replace(new.equipment,last_speed_increased=hit))
        result.append(new)
    return result


def verify_lock_update(before,after,targets):
    if len(before)!=len(after) or not before:
        raise ValueError('上锁前后装备数量发生变化')
    for old,new in zip(before,after):
        if (old.token,asdict(old.equipment),old.selected)!=(new.token,asdict(new.equipment),new.selected):
            raise ValueError('上锁前后装备身份、属性或选中状态发生变化')
        if old.token in targets:
            if new.locked is not True:
                raise ValueError('有价值装备未确认上锁，禁止进入整理出售')
        elif old.locked!=new.locked:
            raise ValueError('非目标装备锁状态发生变化')


def verify_batch(before, after, target):
    """卡片顺序与身份不变；未选中装备不应发生强化。"""
    if len(before) != len(after) or not before:
        raise ValueError("批量装备数量发生变化")
    if len({item.token for item in before}) != len(before):
        raise ValueError("批量卡片标识重复")
    for old, new in zip(before, after):
        a, b = old.equipment, new.equipment
        if (old.token, a.equipment_id, a.rarity, a.slot, a.level) != (
                new.token, b.equipment_id, b.rarity, b.slot, b.level):
            raise ValueError("批量结果装备身份或顺序发生变化")
        if not b.recognition_ok or any(b.stats.get(k, -1) < v for k, v in a.stats.items()):
            raise ValueError("批量结果属性缺失、回退或未确认")
        if old.selected and b.enhancement < target:
            raise ValueError("选中装备未达到强化目标，禁止重试确认")
        if not old.selected and asdict(a) != asdict(b):
            raise ValueError("未选中装备发生变化")
        if old.locked!=new.locked:
            raise ValueError('强化期间装备锁状态发生变化')
        completed_deselection = (target==15 and old.selected and not new.selected and b.enhancement==15)
        if old.selected != new.selected and not completed_deselection:
            raise ValueError('强化期间装备勾选状态发生变化')


class WorkflowTask:
    """完整循环；所有资源消耗共用一个账本，重启不自动恢复确认。"""

    def __init__(self, driver, options, policy, limits, control, journal):
        self.driver, self.options, self.policy = driver, options, policy
        self.ledger = Ledger(limits)
        self.control, self.journal = control, journal
        self.uncertain = False
        self.records = []
        self.untracked_enhancements = 0
        from .enhancement_statistics import EnhancementStatistics
        self.enhancement_statistics=EnhancementStatistics()
        self.statistics_batch=0

    def _lock_candidates(self,items,decisions):
        targets={item.token for item in items if decisions[item.token].action=='keep_candidate'}
        pending={item.token for item in items if item.token in targets and item.locked is not True}
        if not pending:
            return items
        if any(item.locked is None for item in items if item.token in pending):
            raise ValueError('保留装备锁状态未知，暂存并停止整理；不得盲点锁按钮')
        self._stage('lock_valuable',tokens=sorted(pending))
        self.journal.emit('lock_intent',tokens=sorted(pending))
        self.uncertain=True
        after=self.driver.lock_items(items,pending)
        verify_lock_update(items,after,targets)
        self.uncertain=False
        self.journal.emit('lock_verified',tokens=sorted(targets))
        return after

    def _stage(self, name, **data):
        self.control.checkpoint()
        self.journal.emit("workflow_stage", stage=name, **data)

    def _spend(self, kind, prepare, commit, result):
        self.control.checkpoint()
        preview = prepare()
        if preview is None:  # 打造背包满，或该阶段没有选中装备。
            return None
        untracked = kind == 'batch_enhance' and getattr(self.driver,'resource_untracked',False)
        if untracked:
            if preview.cost is not None or preview.resources is not None:
                raise ValueError('免资源识别模式不得记录猜测的费用')
            if self.ledger.steps >= self.ledger.limits.max_steps:
                raise ValueError('达到任务操作次数上限')
        else:
            self.ledger.check(preview.cost, preview.resources)
        self.journal.emit("prepared", operation=kind, cost=preview.cost, image=preview.image)
        self.control.checkpoint()
        self.journal.emit("commit_intent", operation=kind, cost=preview.cost)
        self.uncertain = True
        commit(preview)
        observed = result(preview)
        self.journal.emit("result_observed", operation=kind, resources=observed["resources"],
                          image=observed["image"])
        if untracked:
            self.ledger.steps += 1
            self.untracked_enhancements += 1
        else:
            self.ledger.settle(preview.resources, observed["resources"], preview.cost)
        self.journal.emit("settled", spent=None if untracked else self.ledger.spent,
                          resources_tracked=not untracked, steps=self.ledger.steps)
        if kind == 'batch_enhance' and hasattr(self.driver,'settle_enhancement'):
            self.driver.settle_enhancement(preview)
        self.uncertain = False
        return observed

    def _batch(self, items, *, resumed=False):
        self.statistics_batch+=1
        self.last_disposed_tokens=[]
        if hasattr(self.driver,'normalize_items'):
            items=self.driver.normalize_items(items)
        if not items or len(items) > 16:
            raise ValueError("每批装备数量应为1～16")
        if any((not resumed and item.equipment.enhancement == 15) or not item.equipment.recognition_ok for item in items):
            raise ValueError("新批次只允许已确认的+0～+14装备")
        if len({item.token for item in items}) != len(items):
            raise ValueError("批次卡片身份重复")
        current = items
        self.last_batch = current
        first_pending = {item.token for item in items} if not resumed else set()
        rejected = set()
        protected = set()
        custom_notified=set()
        while True:
            self._stage("batch_evaluate")
            decisions = {item.token: evaluate(item.equipment, self.policy) for item in current}
            current=self._lock_candidates(current,decisions)
            self.last_batch = current
            active = []
            for item in current:
                decision = decisions[item.token]
                custom_names=[name[7:] for name in decision.effective_scores if name.startswith('custom:')]
                if custom_names and (item.token,item.equipment.enhancement) not in custom_notified:
                    custom_notified.add((item.token,item.equipment.enhancement))
                    self.journal.emit('custom_target_match',token=item.token,names=custom_names,
                                      equipment=asdict(item.equipment),score=decision.weighted_score,
                                      action=decision.action,reasons=decision.reasons)
                self.journal.emit("equipment_decision", token=item.token, equipment=asdict(item.equipment), locked=item.locked,
                                  **{key: value for key, value in asdict(decision).items() if key != "equipment_id"})
                if decision.action == "continue":
                    active.append(item.token)
                elif decision.action == "stop" and decision.discard_allowed and item.locked is False:
                    rejected.add(item.token)
                else:
                    protected.add(item.token)
            if rejected & protected:
                raise ValueError("同一装备同时被标为保留与出售")
            # 混合等级先处理最近的下一节点；较高等级装备暂不勾选，避免低目标覆盖。
            by_token={item.token:item.equipment for item in current}
            targets = {token: max(decisions[token].target_level,
                                  self.options.first_target if token in first_pending and by_token[token].rarity!='purple'
                                  and not (self.policy.red_profile_enabled and by_token[token].rarity=='red'
                                           and by_token[token].stats.get('speed',0)>0) else 0) for token in active}
            target = min(targets.values()) if targets else None
            scheduled = {token for token in active if targets[token] == target}
            selected = self.driver.select_active(current, scheduled)
            if [item.token for item in selected] != [item.token for item in current]:
                raise ValueError("调整选中状态后卡片顺序发生变化")
            if any(asdict(a.equipment)!=asdict(b.equipment) or a.locked!=b.locked
                   for a,b in zip(current,selected)):
                raise ValueError('调整选中状态时装备或锁状态发生变化')
            if {item.token for item in selected if item.selected} != scheduled:
                raise ValueError("参与强化的选中集合不符")
            self.last_batch = selected
            if not active:
                current = selected
                break
            before = selected
            def finish(preview):
                observed = self.driver.finish_enhancement(preview)
                verify_batch(before, observed["items"], target)
                return observed
            observed = self._spend("batch_enhance",
                lambda: self.driver.prepare_enhancement(before, target),
                self.driver.commit_enhancement, finish)
            if observed is None:
                raise ValueError("已选中装备但未提供强化预览")
            current = record_speed_roll(before,observed["items"],target)
            first_pending.difference_update(scheduled)
            self.last_batch = current
            # 额外跨过一个属性节点时暂停核对，不把未知成长当成普通超出。
            if any(item.selected and item.equipment.enhancement >= target + 3 for item in current):
                raise ValueError("批量结果额外跨过属性节点，需复核")
            changed=False
            for old,new in zip(before,current):
                if old.selected:
                    changed=self.enhancement_statistics.record((self.statistics_batch,new.token),
                        old.equipment,new.equipment) or changed
            if changed:
                self.journal.emit('enhancement_statistics',**self.enhancement_statistics.snapshot())
        if not rejected:
            self.journal.emit("batch_finished", disposed=[], protected=sorted(protected))
            return
        self._stage("post_enhancement_sale", rejected=sorted(rejected), protected=sorted(protected))
        # driver必须把自动选择结果限制到rejected；明确禁止萃取和处置protected。
        self.journal.emit("disposal_intent", rejected=sorted(rejected), protected=sorted(protected), action="sell")
        self.uncertain = True
        outcome = self.driver.dispose_batch(current, rejected, protected, action="sell")
        if set(outcome["disposed"]) != rejected or set(outcome["disposed"]) & protected:
            raise ValueError("批量出售结果与明确淘汰名单不一致")
        self.uncertain = False
        self.journal.emit("batch_finished", disposed=outcome["disposed"], protected=sorted(protected))
        self.last_disposed_tokens=list(outcome['disposed'])

    def run_batch(self,items,*,verified_recovery=None):
        """运行已经完成入口核对的一批；不宣称完成打造或整个背包循环。"""
        state='failed'
        self.last_batch=items
        try:
            self.control.checkpoint()
            if verified_recovery is not None:
                before,target = verified_recovery
                verify_batch(before,items,target)
                items=record_speed_roll(before,items,target)
            self._batch(items,resumed=verified_recovery is not None)
            state='complete'
        except Cancelled as exc:
            state='stopped'
            self.journal.emit('stopped',message=str(exc),outcome_unknown=self.uncertain)
        except Exception as exc:
            self.journal.emit('failed',message=str(exc),outcome_unknown=self.uncertain)
        result={'state':state,'scope':'batch_only','steps':self.ledger.steps,
                'spent':None if getattr(self.driver,'resource_untracked',False) else dict(self.ledger.spent),'outcome_unknown':self.uncertain,
                'untracked_enhancements':self.untracked_enhancements,
                'enhancement_statistics':self.enhancement_statistics.snapshot(),
                'items':[asdict(item) for item in self.last_batch]}
        self.journal.emit('batch_run_finished',**result)
        return result

    def run(self):
        state = "failed"
        completed_rounds = 0
        try:
            for round_index in range(self.options.rounds):
                self._stage("navigate_forge", round=round_index + 1)
                self.driver.open_forge(self.options)
                repeat = False
                while True:
                    self._stage("craft", repeat=repeat)
                    result = self._spend("craft",
                        lambda: self.driver.prepare_craft(self.options, repeat),
                        self.driver.commit_craft, self.driver.finish_craft)
                    if result is None:
                        break
                    repeat = True
                self._stage("initial_cleanup", action=self.options.initial_disposal)
                self.journal.emit("initial_cleanup_intent", action=self.options.initial_disposal)
                self.uncertain = True
                self.driver.initial_cleanup(self.options.initial_disposal)
                self.uncertain = False
                while True:
                    self._stage("select_unenhanced")
                    batch = self.driver.collect_batch(limit=16, max_pages=self.options.scan_pages)
                    if batch is None:
                        raise ValueError("背包扫描未完成，不能认定已无+0～+14候选装备")
                    if not batch:
                        break
                    self._batch(batch)
                completed_rounds += 1
                self.journal.emit("round_finished", round=completed_rounds)
            state = "complete"
        except Cancelled as exc:
            state = "stopped"
            self.journal.emit("stopped", message=str(exc), outcome_unknown=self.uncertain)
        except Exception as exc:
            self.journal.emit("failed", message=str(exc), outcome_unknown=self.uncertain)
        result = {"state": state, "rounds": completed_rounds, "steps": self.ledger.steps,
                  "enhancement_statistics":self.enhancement_statistics.snapshot(),
                  "spent": dict(self.ledger.spent), "outcome_unknown": self.uncertain}
        self.journal.emit("finished", **result)
        return result
