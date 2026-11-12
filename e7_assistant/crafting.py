"""普通85级双足飞龙装备打造；单件预览与不可重试的确认。"""

from dataclasses import dataclass
from pathlib import Path
import re
import time

from .live import parse_amount
from .tasks import Cancelled, Ledger
from .vision import read_regions


SLOTS = {"weapon": (507, 216), "helmet": (354, 307), "armor": (354, 478),
         "necklace": (662, 307), "ring": (662, 479), "boots": (507, 568)}


@dataclass
class CraftPreview:
    resources: dict
    cost: dict
    slot: str
    image: str


def parse_material(text):
    match = re.fullmatch(r"([0-9,]+)/([0-9,]+)", text)
    if not match:
        raise ValueError("打造材料数量或费用未可靠读取：" + repr(text))
    available, cost = (parse_amount(value) for value in match.groups())
    if cost <= 0:
        raise ValueError("打造材料费用必须大于0")
    return available, cost


class CraftDriver:
    def __init__(self, adb, directory, control, slot):
        if slot not in SLOTS:
            raise ValueError("未知打造部位")
        self.adb, self.directory, self.control, self.slot = adb, Path(directory), control, slot
        self.counter = 0

    def capture(self, label):
        self.counter += 1
        path = self.directory / f"craft-{self.counter:04d}-{label}.png"
        self.adb.screenshot(str(path))
        return path

    def read(self):
        from PIL import Image
        path = self.capture("preview")
        labels = read_regions(path, {"boss": (914, 77, 1270, 128), "button": (1125, 651, 1214, 690)},
                              language="zh-Hans-CN")
        if labels != {"boss": "制作装备〖双足飞龙〗", "button": "制作"}:
            raise ValueError("未确认普通双足飞龙制作页面：" + str(labels))
        with Image.open(path) as image:
            # 单件的白色选中底，与十连未选中暗底必须同时成立。
            rgb = image.convert("RGB")
            if min(rgb.getpixel((1168, 495))) < 210 or max(rgb.getpixel((1250, 495))) > 150:
                raise ValueError("未确认单件制作选项")
            x, y = SLOTS[self.slot]
            border = list(rgb.crop((x - 42, y - 42, x + 42, y - 36)).getdata())
            if sum(b > 160 and g > 135 and b > r * 1.1 for r, g, b in border) / len(border) < .1:
                raise ValueError("未确认目标部位选中边框")
        numbers = read_regions(path, {"material": (1030, 588, 1156, 620)}, white_text=True)
        currency = read_regions(path, {"gold": (668, 17, 799, 51), "cost": (994, 650, 1076, 688)})
        available, material_cost = parse_material(numbers["material"])
        return CraftPreview({"gold": parse_amount(currency["gold"]), "craft_material": available},
                            {"gold": parse_amount(currency["cost"]), "craft_material": material_cost}, self.slot, str(path))

    def prepare(self):
        # 先验证页头，不在其他页面按固定坐标选择。
        path = self.capture("before-select")
        label = read_regions(path, {"boss": (914, 77, 1270, 128)}, language="zh-Hans-CN")["boss"]
        if label != "制作装备〖双足飞龙〗":
            raise ValueError("请先打开钢铁工坊的普通双足飞龙制作页")
        self.control.checkpoint()
        self.adb.tap(*SLOTS[self.slot])
        self.control.wait(.6)
        self.adb.tap(1186, 497)
        self.control.wait(.6)
        return self.read()

    def commit(self, preview):
        self.control.checkpoint()
        fresh = self.read()
        if (fresh.resources, fresh.cost, fresh.slot) != (preview.resources, preview.cost, preview.slot):
            raise ValueError("制作确认前资源或费用发生变化")
        self.control.checkpoint()
        self.adb.tap(1168, 670)
        self.control.wait(.8)
        path = self.capture("confirmation")
        self.verify_confirmation(path, preview)
        self.control.checkpoint()
        self.adb.tap(812, 533)

    def verify_confirmation(self, path, preview):
        labels = read_regions(path, {"title": (530, 154, 760, 206),
                                     "button": (777, 511, 851, 555)}, language="zh-Hans-CN")
        numbers = read_regions(path, {"cost": (656, 512, 744, 554), "material": (402, 413, 456, 450)})
        if labels != {"title": "制作装备1次", "button": "制作"}:
            raise ValueError("未确认单件制作弹窗")
        if {"gold": parse_amount(numbers["cost"]),
            "craft_material": parse_amount(numbers["material"])} != preview.cost:
            raise ValueError("制作弹窗费用与预览不一致")

    def wait_result(self, preview):
        # 确认后只读，不因为超时再次点击制作。
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            time.sleep(.8)
            path = self.capture("result")
            title = read_regions(path, {"title": (560, 50, 740, 95)}, language="zh-Hans-CN")["title"]
            if title == "制作完毕":
                return self.finish_result(path, preview)
        raise TimeoutError("未确认制作结果，禁止重复制作；请人工核对截图")

    def finish_result(self, path, preview):
        title = read_regions(path, {"title": (560, 50, 740, 95)}, language="zh-Hans-CN")["title"]
        if title != "制作完毕":
            raise ValueError("未确认制作完成页，不关闭未知弹窗")
        result = inspect_craft_result(path)
        # 仅点击装备卡片与操作按钮以外的空白区域关闭结果。
        self.adb.tap(1090, 365)
        time.sleep(.8)
        after = self.read()
        return {"image": str(path), "title": title, "equipment": result,
                "resources": after.resources}


def inspect_craft_result(path):
    from PIL import Image
    from .vision import ATTRIBUTE_NAMES, SLOT_NAMES
    regions = {"rarity_slot": (589, 190, 777, 219), "level": (496, 193, 524, 217),
               "stat1": (490, 362, 780, 389), "stat2": (490, 389, 780, 414),
               "stat3": (490, 414, 780, 441), "stat4": (490, 441, 780, 468),
               "set": (528, 517, 780, 548), "main": (490, 304, 780, 343)}
    raw = read_regions(path, regions, language="zh-Hans-CN")
    score = read_regions(path, {"score": (719, 469, 787, 507)})["score"]
    label = raw["rarity_slot"]
    rarity = "purple" if label.startswith("英雄") else "red" if label.startswith("传说") else None
    with Image.open(path) as image:
        pixels = list(image.convert("RGB").crop((590, 195, 670, 217)).getdata())
        purple_ratio = sum(r > 140 and b > 100 and g < 100 for r, g, b in pixels) / len(pixels)
    # 国服紫色品质文字的颜色证据，与词条数量共同复核；不替换OCR中的错别字。
    if rarity is None and purple_ratio > .04:
        rarity = "purple"
    slot = next((value for name, value in SLOT_NAMES.items() if label.endswith(name)), None)
    stats, issues = {}, []
    for key in ("stat1", "stat2", "stat3", "stat4"):
        if not raw[key]:
            continue
        match = re.fullmatch(r"(.+?)(\d+)(%)?", raw[key])
        if not match or match[1] not in ATTRIBUTE_NAMES:
            issues.append("副属性无法读取：" + raw[key])
            continue
        name, value, percentage = match.groups()
        if name in {"暴击率", "暴击伤害", "效果命中", "效果抗性"} and not percentage:
            issues.append("副属性缺少百分号")
            continue
        stat = ATTRIBUTE_NAMES[name][0 if percentage else 1]
        if stat in stats or (stat == "speed" and percentage):
            issues.append("重复或非法副属性")
            continue
        stats[stat] = int(value)
    if rarity is None or slot is None or raw["level"] != "85":
        issues.append("品质、部位或85级未确认")
    if len(stats) != (3 if rarity == "purple" else 4):
        issues.append("副属性数量不符合品质")
    return {"rarity": rarity, "slot": slot, "level": 85 if raw["level"] == "85" else None,
            "enhancement": 0, "stats": stats, "game_score": parse_amount(score),
            "main_ocr": raw["main"], "set_ocr": raw["set"], "issues": issues, "raw": raw}


class CraftTask:
    """一次制作事务；结果装备及消耗尚未核对时不开始下一次。"""

    def __init__(self, driver, limits, control, journal, policy=None):
        from .rules import Policy
        self.driver, self.control, self.journal = driver, control, journal
        self.ledger = Ledger(limits)
        self.policy = policy or Policy()

    def run(self):
        committed, state = False, "failed"
        try:
            while self.ledger.steps < self.ledger.limits.max_steps:
                self.control.checkpoint()
                preview = self.driver.prepare()
                self.ledger.check(preview.cost, preview.resources)
                self.journal.emit("craft_prepared", slot=preview.slot, cost=preview.cost,
                                  resources=preview.resources, image=preview.image)
                self.control.checkpoint()
                self.journal.emit("craft_commit_intent", cost=preview.cost)
                committed = True
                self.driver.commit(preview)
                result = self.driver.wait_result(preview)
                self.journal.emit("craft_result", **result)
                actual = self.ledger.settle(preview.resources, result["resources"], preview.cost)
                self.journal.emit("settled", actual=actual, spent=self.ledger.spent, steps=self.ledger.steps)
                committed = False
                state = "review_result" if result["equipment"]["issues"] else "crafted"
                if state == "review_result":
                    break
                from .rules import Equipment, evaluate
                item = result["equipment"]
                decision = evaluate(Equipment(
                    equipment_id=f"{self.journal.directory.name}-{self.ledger.steps}",
                    rarity=item["rarity"], slot=item["slot"], level=item["level"], enhancement=0,
                    stats=item["stats"], game_score=item["game_score"], recognition_ok=True,
                    main_stat_usable=item["slot"] in {"weapon", "helmet", "armor"}), self.policy)
                self.journal.emit("crafted_record", equipment=item, action=decision.action,
                                  reasons=decision.reasons, image=result["image"])
                if decision.action == "continue":
                    state = "awaiting_enhancement"
                    break
            else:
                state = "limit_reached"
        except Cancelled as exc:
            state = "stopped"
            self.journal.emit("stopped", message=str(exc))
        except Exception as exc:
            self.journal.emit("failed", message=str(exc), outcome_unknown=committed)
        self.journal.emit("finished", state=state, outcome_unknown=committed, spent=self.ledger.spent,
                          steps=self.ledger.steps)
        return {"state": state, "outcome_unknown": committed, "spent": dict(self.ledger.spent),
                "steps": self.ledger.steps}
