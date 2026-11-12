"""用离线记录检验同一装备的决策序列，不执行ADB动作。"""

from dataclasses import asdict
from .rules import Equipment, Policy, evaluate


def replay(observations: list[dict], policy: Policy) -> list[dict]:
    if not observations:
        raise ValueError("回放记录不能为空")
    decisions = []
    previous = None
    target = None
    for raw in observations:
        item = Equipment(**raw)
        if previous:
            if (item.equipment_id, item.rarity, item.level, item.slot) != (
                previous.equipment_id, previous.rarity, previous.level, previous.slot
            ):
                raise ValueError("回放装备身份发生变化，停止")
            if item.enhancement < target:
                raise ValueError("实际强化等级未达到上一目标，需核对操作结果")
            if any(item.stats.get(k, -1) < v for k, v in previous.stats.items()):
                raise ValueError("原有副属性丢失或回退，需重新识别")
        decision = evaluate(item, policy)
        if previous and item.enhancement > target:
            decision.reasons.insert(0, f"目标+{target}，实际+{item.enhancement}，按实际等级重新评估")
            if item.enhancement >= target + 3:
                decision.action = "review"
                decision.target_level = None
                decision.reasons.insert(0, "额外跨过属性节点，暂停并核对全部成长")
        decisions.append(asdict(decision))
        if decision.action != "continue":
            break
        previous, target = item, decision.target_level
    return decisions
