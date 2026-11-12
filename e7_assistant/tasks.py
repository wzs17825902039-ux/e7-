"""可取消的单件强化任务；资源结算与点击驱动分开测试。"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time

from .rules import Equipment, Policy, evaluate


RESOURCE_NAMES = ("gold", "powder", "lesser_stone", "greater_stone", "epic_stone", "craft_material",
                  "jewelry_powder", "jewelry_lesser_stone", "jewelry_greater_stone", "jewelry_epic_stone")


@dataclass
class Snapshot:
    equipment: Equipment
    identity: str
    resources: dict[str, int]
    image: str


@dataclass
class Preview:
    target: int
    cost: dict[str, int]
    snapshot: Snapshot


@dataclass
class Limits:
    gold: int = 200000
    powder: int = 100
    lesser_stone: int = 0
    greater_stone: int = 0
    epic_stone: int = 0
    craft_material: int = 0
    max_steps: int = 5
    jewelry_powder: int = 0
    jewelry_lesser_stone: int = 0
    jewelry_greater_stone: int = 0
    jewelry_epic_stone: int = 0

    def __post_init__(self):
        for key, value in asdict(self).items():
            if type(value) is not int or value < 0:
                raise ValueError(f"{key}必须为非负整数")
        if self.max_steps < 1:
            raise ValueError("任务操作次数至少为1")


class Cancelled(Exception):
    pass


class TaskControl:
    def __init__(self, action_interval=0):
        if isinstance(action_interval, bool) or not isinstance(action_interval, (int, float)) or not 0 <= action_interval <= 5:
            raise ValueError("操作间隔必须为0～5秒")
        self.action_interval = action_interval
        self.last_action = None
        self.stopped = threading.Event()
        self.running = threading.Event()
        self.running.set()

    def stop(self):
        self.stopped.set()
        self.running.set()

    def pause(self):
        self.running.clear()

    def resume(self):
        self.running.set()

    def checkpoint(self):
        while not self.running.wait(0.1):
            if self.stopped.is_set():
                raise Cancelled("用户已停止")
        if self.stopped.is_set():
            raise Cancelled("用户已停止")

    def wait(self, seconds):
        if self.stopped.wait(seconds):
            raise Cancelled("用户已停止")
        self.checkpoint()

    def before_input(self):
        self.checkpoint()
        if self.last_action is not None:
            remaining = self.action_interval - (time.monotonic() - self.last_action)
            if remaining > 0:
                self.wait(remaining)
        self.checkpoint()
        self.last_action = time.monotonic()


class Journal:
    def __init__(self, directory: Path, callback=None):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.path = directory / "events.jsonl"
        self.callback = callback or (lambda event: None)

    def emit(self, kind, **data):
        event = {"time": datetime.now(timezone(timedelta(hours=8))).isoformat(), "kind": kind, **data}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
        self.callback(event)
        return event


@dataclass
class Ledger:
    limits: Limits
    spent: dict[str, int] = field(default_factory=lambda: dict.fromkeys(RESOURCE_NAMES, 0))
    steps: int = 0

    def check(self, cost, resources):
        if self.steps >= self.limits.max_steps:
            raise ValueError("达到任务操作次数上限")
        if not cost or cost.get("gold", 0) <= 0:
            raise ValueError("未读取到有效金币费用")
        for key, value in cost.items():
            if key not in RESOURCE_NAMES or type(value) is not int or value < 0:
                raise ValueError("预览包含未知或无效资源费用")
            if key not in resources or resources[key] < value:
                raise ValueError(f"{key}资源不足或未可靠识别")
            if self.spent[key] + value > getattr(self.limits, key):
                raise ValueError(f"{key}超过本任务剩余预算")

    def settle(self, before, after, expected):
        actual = {}
        for key in expected:
            if key not in before or key not in after:
                raise ValueError(f"缺少{key}实际消耗核对")
            delta = before[key] - after[key]
            if delta < 0:
                raise ValueError(f"{key}发生补充或退款，需复核实际消耗")
            actual[key] = delta
        # 即使与预览不一致，也先把观测到的消耗记入账本，不抹掉证据。
        for key, value in actual.items():
            self.spent[key] += value
        self.steps += 1
        if actual != expected:
            raise ValueError(f"实际消耗与预览不一致：{actual}，预览：{expected}")
        return actual


def same_equipment(before: Snapshot, after: Snapshot):
    a, b = before.equipment, after.equipment
    if not before.identity or before.identity != after.identity:
        raise ValueError("装备图标身份发生变化，任务暂停")
    if (a.level, a.rarity, a.slot) != (b.level, b.rarity, b.slot):
        raise ValueError("装备品质/等级/部位不一致")
    if any(b.stats.get(key, -1) < value for key, value in a.stats.items()):
        raise ValueError("原有副属性丢失或回退")


class EnhancementTask:
    """driver接口：observe / prepare / commit / wait_result / clear。"""

    def __init__(self, driver, policy, limits, control, journal):
        self.driver, self.policy = driver, policy
        self.ledger = Ledger(limits)
        self.control, self.journal = control, journal
        from .enhancement_statistics import EnhancementStatistics
        self.enhancement_statistics=EnhancementStatistics()

    def run(self):
        state = "failed"
        pending = False
        committed = False
        try:
            self.control.checkpoint()
            current = self.driver.observe()
            self.journal.emit("observed", equipment=asdict(current.equipment), image=current.image)
            while True:
                self.control.checkpoint()
                decision = evaluate(current.equipment, self.policy)
                self.journal.emit("decision", **asdict(decision))
                if decision.action != "continue":
                    state = decision.action
                    break
                if self.ledger.steps >= self.ledger.limits.max_steps:
                    state = "limit_reached"
                    break
                self.control.checkpoint()
                pending = True
                preview = self.driver.prepare(decision.target_level, current)
                if preview.target != decision.target_level:
                    raise ValueError("材料登记目标与规则决策不一致")
                same_equipment(current, preview.snapshot)
                if preview.snapshot.equipment.enhancement != current.equipment.enhancement:
                    raise ValueError("登记材料期间强化等级发生变化")
                self.ledger.check(preview.cost, current.resources)
                self.journal.emit("prepared", target=preview.target, cost=preview.cost, image=preview.snapshot.image)
                self.control.checkpoint()
                # 持久化意图之后只确认一次；异常时不自动重试或恢复此确认。
                self.journal.emit("commit_intent", target=preview.target, cost=preview.cost)
                committed = True
                self.driver.commit(preview)
                pending = False
                after = self.driver.wait_result(current, preview)
                self.journal.emit("result_observed", equipment=asdict(after.equipment), image=after.image,
                                  resources=after.resources)
                same_equipment(current, after)
                if after.equipment.enhancement < preview.target:
                    raise ValueError("结果未达到登记目标，需核对，禁止重复确认")
                actual = self.ledger.settle(current.resources, after.resources, preview.cost)
                self.journal.emit("settled", actual=actual, spent=self.ledger.spent, steps=self.ledger.steps)
                committed = False
                if after.equipment.enhancement >= preview.target + 3:
                    raise ValueError("额外跨过属性节点，暂停核对全部成长")
                from .workflow import BatchItem,record_speed_roll
                recorded=record_speed_roll([BatchItem('single',current.equipment,True)],
                                          [BatchItem('single',after.equipment,True)],preview.target)
                after.equipment=recorded[0].equipment
                if self.enhancement_statistics.record('single',current.equipment,after.equipment):
                    self.journal.emit('enhancement_statistics',**self.enhancement_statistics.snapshot())
                current = after
        except Cancelled as exc:
            state = "stopped"
            self.journal.emit("stopped", message=str(exc), outcome_unknown=committed)
        except Exception as exc:
            self.journal.emit("failed", message=str(exc), outcome_unknown=committed)
        finally:
            if pending and not committed:
                try:
                    self.driver.clear()
                    self.journal.emit("selection_cleared")
                except Exception as exc:
                    self.journal.emit("clear_failed", message=str(exc))
            self.journal.emit("finished", state=state, spent=self.ledger.spent, steps=self.ledger.steps,
                              outcome_unknown=committed)
        return {"state": state, "spent": dict(self.ledger.spent), "steps": self.ledger.steps,
                "outcome_unknown": committed,"enhancement_statistics":self.enhancement_statistics.snapshot()}
