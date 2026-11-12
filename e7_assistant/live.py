"""1280×720国服强化页驱动。每个确认前核对页面、身份、等级和资源预览。"""

from dataclasses import asdict
from pathlib import Path
import re
import time

from .rules import Equipment
from .tasks import Preview, Snapshot, same_equipment
from .vision import inspect_image, read_regions


RESOURCE_REGIONS = {
    "gold": (668, 17, 799, 51),
    "powder": (1170, 145, 1278, 211),
    "lesser_stone": (1170, 240, 1278, 309),
    "greater_stone": (1170, 334, 1278, 403),
    "epic_stone": (1170, 429, 1278, 499),
    "cost": (623, 645, 695, 678),
    "registered_count": (438, 491, 507, 527),
}
MENU_Y = {3: 579, 6: 522, 9: 465, 12: 408, 15: 351}


def powder_checkbox_checked(image):
    pixels = list(image.convert("RGB").crop((968, 268, 985, 284)).getdata())
    # 实机勾号为亮绿色；白色边框和文字不代表选中。
    return sum(g > 150 and r < 170 and b < 140 for r, g, b in pixels) / len(pixels) > 0.08


def parse_amount(text, preview_remaining=False):
    # 金币图标有时被识别为这些标点；不把O/I等字母擅自当数字。
    clean = text.removeprefix("数量").replace(",", "").replace("，", "").lstrip("<>《》()。· ")
    match = re.match(r"^(\d{1,3}(?:,\d{3})+|\d+)", clean)
    if not match or (match.end() != len(clean) and not preview_remaining):
        raise ValueError(f"资源数值未可靠读取：{text!r}")
    return int(match[1].replace(",", ""))


def equipment_from_report(report, main_stat_usable):
    if report.get("page") != "enhancement" or report.get("issues"):
        raise ValueError("强化页字段识别不完整：" + "；".join(report.get("issues", [])))
    fields = report["fields"]
    return Equipment(equipment_id=report["identity"], rarity=fields["rarity"], slot=fields["slot"],
                     level=fields["level"], enhancement=fields["enhancement"], stats=fields["stats"],
                     game_score=fields["game_score"], main_stat_usable=main_stat_usable, recognition_ok=True)


def comparable(snapshot):
    item = snapshot.equipment
    return (snapshot.identity, item.level, item.rarity, item.slot, item.enhancement,
            item.game_score, item.stats, snapshot.resources)


class EnhancementDriver:
    def __init__(self, adb, directory, control, expected_report, main_stat_usable):
        self.adb, self.directory, self.control = adb, Path(directory), control
        self.expected_report = expected_report
        self.main_stat_usable = main_stat_usable
        self.counter = 0
        self.last_cost = None
        self.last_count = None

    def _capture(self, label):
        self.counter += 1
        path = self.directory / f"{self.counter:04d}-{label}.png"
        self.adb.screenshot(str(path))
        return path

    def _read(self, prepared=False):
        path = self._capture("prepared" if prepared else "observe")
        report = inspect_image(str(path))
        item = equipment_from_report(report, self.main_stat_usable)
        raw = read_regions(path, RESOURCE_REGIONS, language="zh-Hans-CN")
        resources = {key: parse_amount(raw[key], preview_remaining=prepared)
                     for key in ("gold", "powder", "lesser_stone", "greater_stone", "epic_stone")}
        try:
            cost = parse_amount(raw["cost"])
        except ValueError:
            # 中文OCR可能把25,600识别成2玩600；重新读纯数字区域，不替换猜字。
            fallback = read_regions(path, {"cost": RESOURCE_REGIONS["cost"]}, language="en-US")
            cost = parse_amount(fallback["cost"])
        if prepared:
            try:
                parse_amount(raw["registered_count"])
            except ValueError:
                raw["registered_count"] = read_regions(
                    path, {"registered_count": RESOURCE_REGIONS["registered_count"]},
                    language="en-US")["registered_count"]
                parse_amount(raw["registered_count"])
        if not prepared and cost != 0:
            raise ValueError("材料已经登记，请先清空材料再开始任务")
        self.last_cost = cost
        self.last_count = raw["registered_count"]
        return Snapshot(item, report["identity"], resources, str(path))

    def observe(self):
        self.control.checkpoint()
        first = self._read()
        self.control.wait(0.4)
        second = self._read()
        if comparable(first) != comparable(second):
            raise ValueError("两次观测不一致，请等待页面稳定后重新开始")
        if self.expected_report:
            expected = equipment_from_report(self.expected_report, self.main_stat_usable)
            if asdict(expected) != asdict(second.equipment):
                raise ValueError("当前装备与界面中确认的截图不一致，请重新截图核对")
            self.expected_report = None
        return second

    def _menu(self, target):
        self.control.checkpoint()
        self.adb.tap(1070, 660)
        self.control.wait(0.6)
        path = self._capture("target-menu")
        y = MENU_Y[target]
        label = read_regions(path, {"target": (1000, y - 19, 1140, y + 19)}, language="zh-Hans-CN")["target"]
        if label != f"+{target}阶段":
            raise ValueError(f"目标菜单识别不符：{label!r}")
        return path

    def _powder_only(self, menu_path, target):
        from PIL import Image
        with Image.open(menu_path) as image:
            checked = powder_checkbox_checked(image)
        if not checked:
            self.control.checkpoint()
            self.adb.tap(976, 276)
            self.control.wait(0.4)
            path = self._capture("powder-only")
            with Image.open(path) as image:
                if not powder_checkbox_checked(image):
                    raise ValueError("无法确认仅使用强化粉末选项")
        self.control.checkpoint()
        self.adb.tap(1070, MENU_Y[target])
        self.control.wait(0.6)

    def prepare(self, target, before):
        if target not in MENU_Y:
            raise ValueError("非法强化目标")
        current = self._read()
        if comparable(current) != comparable(before):
            raise ValueError("开始登记前装备或资源发生变化")
        menu_path = self._menu(target)
        self._powder_only(menu_path, target)
        prepared = self._read(prepared=True)
        same_equipment(before, prepared)
        if prepared.resources["gold"] != before.resources["gold"]:
            raise ValueError("登记材料期间金币发生变化")
        cost = {key: before.resources[key] - prepared.resources[key]
                for key in ("powder", "lesser_stone", "greater_stone", "epic_stone")}
        if any(value < 0 for value in cost.values()):
            raise ValueError("资源预览出现增加，无法核对登记消耗")
        if cost["powder"] <= 0 or any(cost[key] for key in ("lesser_stone", "greater_stone", "epic_stone")):
            raise ValueError("预览未满足仅使用粉末条件")
        count = parse_amount(self.last_count)
        if count != cost["powder"]:
            raise ValueError("登记槽粉末数与剩余数量差值不一致")
        cost["gold"] = self.last_cost
        return Preview(target, cost, prepared)

    def commit(self, preview):
        self.control.checkpoint()
        fresh = self._read(prepared=True)
        if comparable(fresh) != comparable(preview.snapshot) or self.last_cost != preview.cost["gold"]:
            raise ValueError("确认前预览发生变化，未发送强化确认")
        if parse_amount(self.last_count) != preview.cost["powder"]:
            raise ValueError("确认前登记数量发生变化")
        self.control.checkpoint()
        self.adb.tap(755, 663)

    def wait_result(self, before, preview):
        # 已经确认后，即便请求停止也尝试读取结果，不再发任何点击。
        deadline = time.monotonic() + 60
        last_error = "尚未出现结果"
        while time.monotonic() < deadline:
            time.sleep(0.6)
            try:
                after = self._read()
                if after.equipment.enhancement >= preview.target:
                    stable = self._read()
                    if comparable(after) == comparable(stable):
                        return stable
                last_error = "实际等级未达到目标"
            except (ValueError, RuntimeError) as exc:
                last_error = str(exc)
        raise TimeoutError("强化结果未可靠确认，禁止重复操作：" + last_error)

    def clear(self):
        # 清理只允许在可识别的强化页面，不在未知页面盲点。
        path = self._capture("before-clear")
        report = inspect_image(str(path))
        if report.get("page") != "enhancement":
            raise ValueError("未知页面，未发送清空点击")
        self.adb.tap(485, 663)
        self.control.stopped.wait(0.5)
        self._read()  # 清理成功必须由材料费用归零和可识别页面证明。
