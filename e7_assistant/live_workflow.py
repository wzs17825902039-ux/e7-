"""组合真实打造、预设清理、背包扫描和批量强化；不恢复未知确认。"""
import json

from .batch_enhancement import BatchEnhancementDriver
from .batch_entry import BatchEntryDriver
from .batch_selection import BatchSelectionDriver
from .disposal_guard import BatchEnhancementGuard, CraftSessionGuard, DisposalGuard
from .equipment_protection import EquipmentProtection
from .forge_loop import LiveForgeLoop
from .initial_cleanup import InitialCleanupDriver
from .tasks import Cancelled
from .workflow import WorkflowTask
from .inventory_sort import ensure_ascending


class LiveWorkflowTask(WorkflowTask):
    def __init__(self,navigator,options,policy,limits,control,journal):
        self.navigator=navigator
        self.workspace=navigator.directory.parent
        self.enhancement_guard=BatchEnhancementGuard(
            self.workspace/'enhancement-pending',navigator.adb.serial)
        self.disposal_guard=DisposalGuard(self.workspace/'disposal-pending',navigator.adb.serial)
        self.craft_guard=CraftSessionGuard(self.workspace/'craft-pending',navigator.adb.serial)
        self.protection=EquipmentProtection(self.workspace/'equipment-protection',navigator.adb.serial,policy)
        self.cleanup=InitialCleanupDriver(navigator,guard=self.disposal_guard)
        super().__init__(BatchEnhancementDriver(navigator,guard=self.enhancement_guard,track_resources=False,purple_speed_only=True,
                                                ignore_equipment_level=policy.ignore_equipment_level),
                         options,policy,limits,control,journal)
        self.last_image=None
        self.completed_batches=0
        self.selection_skip_positions={}
        self.selection_registered=[]
        self.craft_consumption_complete=options.track_craft_consumption

    def collect_batch(self):
        # 返回背包会清除本任务上一批的视口；选装驱动仍拒绝任何既有勾选。
        self.navigator.navigate('inventory')
        ensure_ascending(self.navigator)
        self.navigator.navigate('inventory_batch_selection')
        selector=BatchSelectionDriver(self.navigator,policy=self.policy,protection=self.protection,
                                      excluded_positions=self.selection_skip_positions)
        selection=selector.collect_pages(limit=16,max_pages=self.options.scan_pages,start_at_top=True)
        self.last_image=selection['source']
        self.selection_registered=selection.get('registered',[])
        path=self.navigator.directory/f'selection-{self.completed_batches+1:04d}.json'
        path.write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf8')
        if selection['selected_count']==0:
            if selection.get('scan_complete') is not True:
                raise ValueError('扫描未完成，不能认定已无+0～+14候选装备')
            return []
        report,items=BatchEntryDriver(selector).enter(selection)
        self.last_image=report['source']
        # 上一批上锁建立的等级锚点不得用于另一批同位置的装备。
        self.driver=BatchEnhancementDriver(self.navigator,guard=self.enhancement_guard,track_resources=False,purple_speed_only=True)
        return items

    def finish_inventory_round(self):
        """打造已到满后的同一清理与多批循环；恢复现场也复用本路径。"""
        self._stage('initial_cleanup',action=self.options.initial_disposal)
        try:
            cleanup=self.cleanup.initial_cleanup(self.options.initial_disposal)
        except Exception:
            self.uncertain=self.cleanup.pending
            raise
        self.last_image=cleanup['image']
        self.selection_skip_positions.clear()
        self.journal.emit('workflow_cleanup_finished',result=cleanup)
        self.enhance_inventory_batches()

    def enhance_inventory_batches(self):
        """按顶部顺序连续处理所有可强化候选，清理后与恢复共用。"""
        while True:
            self._stage('select_unenhanced')
            items=self.collect_batch()
            if not items:
                break
            self.run_batch_with_recovery(items)
            if (getattr(self,'last_disposed_tokens',[]) or
                    any(a.equipment.enhancement!=b.equipment.enhancement or a.locked!=b.locked
                        for a,b in zip(items,self.last_batch))):
                self.selection_skip_positions.clear()
            else:
                for entry in self.selection_registered:
                    if entry.get('selection_only') and entry.get('list_card'):
                        self.selection_skip_positions[tuple(entry['position'])]=entry['list_card']
            self.last_image=self.driver.last_image or self.last_image
            self.completed_batches+=1
            self.journal.emit('workflow_batch_finished',batch=self.completed_batches,
                              spent=dict(self.ledger.spent),steps=self.ledger.steps)

    def recover_pending_batch(self):
        """只恢复已有回执；不重新发送旧强化或出售确认。"""
        from .batch_recovery import settle_submitted_enhancement,settle_submitted_sale
        enhancement=self.enhancement_guard.read()
        disposal=self.disposal_guard.read()
        if not enhancement and not disposal:return None
        self.control.checkpoint()
        if enhancement and disposal:raise ValueError('同时存在强化与出售待核验记录，不能自动推定先后')
        kind='enhancement' if enhancement else 'sale'
        self.journal.emit('workflow_auto_recovery',operation=kind,message='正在自动恢复当前批次')
        for attempt in range(2):
            result=(settle_submitted_enhancement(self) if enhancement else settle_submitted_sale(self))
            if result['state']=='stopped':raise Cancelled('自动恢复已停止')
            if result['state']=='complete':break
            if attempt==0:self.control.wait(.3)
        else:raise ValueError('自动恢复两次仍未确认原提交结果，未重复确认')
        self.journal.emit('workflow_auto_recovered',operation=kind)
        return kind

    def run_batch_with_recovery(self,items,*,resumed=False):
        """消费后的短暂拒识先自动恢复，不要求用户另点核验。"""
        from .batch_enhancement import BatchObservationError
        current=items
        for attempt in range(3):
            try:
                self._batch(current,resumed=resumed)
                return
            except Cancelled:raise
            except (ValueError,TimeoutError) as exc:
                if attempt==2:raise
                kind=self.recover_pending_batch()
                if kind is None:
                    if isinstance(exc,BatchObservationError) and not self.uncertain:
                        self.journal.emit('workflow_observation_retry',attempt=attempt+1,message=str(exc))
                        self.control.wait(.3)
                        current=self.last_batch;resumed=True
                        continue
                    raise
                if kind=='sale':
                    # 外层循环统一计一次批次，保留已确认的处置结果供扫描重置使用。
                    self.last_disposed_tokens=[item.token for item in current
                                               if item.token not in {i.token for i in self.last_batch}]
                    return
                # 恢复器只接受提交之后没有 settled 事件的回执，补记这一档一次。
                self.ledger.steps+=1
                if getattr(self.driver,'resource_untracked',False):self.untracked_enhancements+=1
                current=self.last_batch;resumed=True

    def resume_pending_batch(self,kind):
        """显式恢复入口也走同一背包主循环，不在回执模块继续消费。"""
        guard=self.enhancement_guard if kind=='enhancement' else self.disposal_guard if kind=='sale' else None
        if guard is None or guard.read() is None:
            raise ValueError('没有对应的待恢复批次')
        return self.run(inventory_only=True)

    def run(self,*,inventory_only=False):
        state='failed'
        completed_rounds=0
        try:
            self._stage('preflight')
            recovered=self.recover_pending_batch()
            if recovered=='enhancement':
                self.run_batch_with_recovery(self.last_batch,resumed=True)
            if recovered is not None:
                self.completed_batches+=1
            # 在任何打造或导航输入前检查，不能先花材料再发现旧确认未知。
            self.enhancement_guard.check_clear()
            self.disposal_guard.check_clear()
            self.craft_guard.check_clear()
            if inventory_only:
                self.enhance_inventory_batches()
            for index in range(0 if inventory_only else self.options.rounds):
                self._stage('navigate_forge',round=index+1)
                forge=LiveForgeLoop(self.navigator,self.options,self.ledger,self.control,self.journal)
                forged=forge.run()
                self.craft_consumption_complete=self.craft_consumption_complete and forged.get('consumption_complete',False)
                self.uncertain=forged['outcome_unknown']
                self.journal.emit('workflow_forge_finished',round=index+1,result=forged)
                if self.uncertain:
                    raise ValueError('打造结果未结算，停止整轮流程')
                if forged['state']=='stopped':
                    raise Cancelled('打造阶段已停止')
                if forged['state'] in {'budget_reached','resources_exhausted'}:
                    state=forged['state']
                    break
                if forged['state']!='inventory_full':
                    raise ValueError('打造未确认以背包满结束，停止整轮流程')
                self.finish_inventory_round()
                completed_rounds+=1
                self.journal.emit('round_finished',round=completed_rounds)
            else:
                state='complete'
        except Cancelled as exc:
            state='stopped'
            self.last_image=self.driver.last_image or self.last_image
            self.journal.emit('stopped',message=str(exc),outcome_unknown=self.uncertain)
        except Exception as exc:
            self.last_image=self.driver.last_image or self.last_image
            self.journal.emit('failed',message=str(exc),outcome_unknown=self.uncertain)
        result={'state':state,'scope':'inventory_only' if inventory_only else 'live_workflow','rounds':completed_rounds,
                'enhancement_statistics':self.enhancement_statistics.snapshot(),
                'batches':self.completed_batches,'steps':self.ledger.steps,
                'spent':dict(self.ledger.spent),'outcome_unknown':self.uncertain,
                'untracked_enhancements':self.untracked_enhancements,
                'spent_excludes_enhancement':bool(self.untracked_enhancements),
                'craft_gold_tracked':self.options.track_craft_gold,
                'consumption_tracking':self.options.track_craft_consumption,
                'consumption_complete':self.craft_consumption_complete and not inventory_only,
                'last_image':getattr(self.navigator,'last_image',None) or self.last_image}
        self.journal.emit('finished',**result)
        return result
