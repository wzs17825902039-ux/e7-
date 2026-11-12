"""Windows本地OCR。当前仅标定1280×720强化页，输出报告而非点击依据。"""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata


ATTRIBUTE_NAMES = {
    "攻击力": ("atk_pct", "atk_flat"),
    "生命值": ("hp_pct", "hp_flat"),
    "防御力": ("def_pct", "def_flat"),
    "速度": ("speed", "speed"),
    "暴击率": ("crit", "crit"),
    "暴击伤害": ("cdmg", "cdmg"),
    "效果命中": ("effectiveness", "effectiveness"),
    "效果抗性": ("resistance", "resistance"),
}
SLOT_NAMES = {"武器": "weapon", "头盔": "helmet", "铠甲": "armor",
              "项链": "necklace", "戒指": "ring", "鞋子": "boots"}


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def text_in_box(lines, box):
    left, top, right, bottom = box
    words = [word for line in lines for word in line["words"]
             if left <= (word["x"] + word["width"] / 2) / 3 < right
             and top <= (word["y"] + word["height"] / 2) / 3 < bottom]
    return normalize("".join(word["text"] for word in sorted(words, key=lambda w: w["x"])))


def integer_field(text):
    return int(text) if re.fullmatch(r"\d+", text) else None


def parse_panel(lines, badge_absent=False, badge_text=None):
    """所有坐标来自已观察的强化页面；空值保持未知，不以零填充。"""
    issues = []
    title = text_in_box(lines, (60, 12, 175, 53))
    if title != "强化装备":
        return {"page": "unknown", "fields": {}, "issues": ["未确认强化装备页面"],
                "automation_ready": False}
    rarity_slot = text_in_box(lines, (135, 101, 305, 131))
    rarity = "purple" if rarity_slot.startswith("英雄") else "red" if rarity_slot.startswith("传说") else None
    slot = next((v for k, v in SLOT_NAMES.items() if rarity_slot.endswith(k)), None)
    badge = normalize(badge_text) if badge_text is not None else text_in_box(lines, (97, 78, 138, 114))
    enhancement = int(badge[1:]) if re.fullmatch(r"\+\d{1,2}", badge) else None
    if badge_absent:
        if enhancement is None:
            enhancement = 0
        else:
            issues.append("强化徽标颜色与OCR数字冲突")
            enhancement = None
    if enhancement is not None and enhancement > 15:
        enhancement = None
    level = integer_field(text_in_box(lines, (37, 92, 74, 123)))
    score_text = text_in_box(lines, (245, 394, 369, 434))
    # 增长括号是累计值，只保留括号前的当前分。
    match = re.fullmatch(r"(\d+)(?:\(\+\d+\))?", score_text)
    score = int(match[1]) if match else None
    stats, roll_counts = {}, {}
    for row, y in enumerate((286, 311, 336, 361)):
        label = text_in_box(lines, (38, y - 12, 205, y + 12))
        value = text_in_box(lines, (210, y - 12, 369, y + 12))
        if not label and not value:
            continue
        if label.startswith("强化+12时"):
            continue
        label_match = re.fullmatch(r"(.+?)(?:\((\d+)\))?", label)
        name = label_match[1] if label_match else ""
        value_match = re.fullmatch(r"(\d+)(%)?(?:\(\+\d+%?\))?", value)
        if name not in ATTRIBUTE_NAMES or not value_match:
            issues.append(f"第{row + 1}条副属性无法可靠读取：{label} / {value}")
            continue
        percent = bool(value_match[2])
        if name in {"暴击率", "暴击伤害", "效果命中", "效果抗性"} and not percent:
            issues.append(f"第{row + 1}条缺少百分号")
            continue
        if name == "速度" and percent:
            issues.append("速度出现百分号，需复核")
            continue
        key = ATTRIBUTE_NAMES[name][0 if percent else 1]
        if key in stats:
            issues.append("出现重复副属性")
        stats[key] = int(value_match[1])
        if label_match[2] is not None:
            roll_counts[key] = int(label_match[2])
    fields = {
        "rarity": rarity, "slot": slot, "level": level, "enhancement": enhancement,
        "game_score": score, "stats": stats, "roll_counts": roll_counts,
        "name_ocr": text_in_box(lines, (135, 130, 380, 166)),
        "set_ocr": text_in_box(lines, (73, 437, 300, 468)),
    }
    for key in ("rarity", "slot", "level", "enhancement", "game_score"):
        if fields[key] is None:
            issues.append(f"{key}未可靠读取")
    if enhancement is not None and rarity:
        expected = 3 if rarity == "purple" and enhancement < 12 else 4
        if len(stats) != expected:
            issues.append("副属性数量不符合品质与强化阶段")
    return {"page": "enhancement", "fields": fields, "issues": issues,
            "automation_ready": False,
            "notice": "仅为OCR候选；尚未确认装备身份、主属性用途和材料登记状态，不执行点击"}


def map_detail_lines(lines):
    """把独立排列的4行属性映射回装备面板坐标。"""
    mapped = []
    for line in lines:
        for word in line["words"]:
            y = word["y"] + word["height"] / 2
            for row in range(4):
                top = 30 + row * 145
                if top <= y < top + 108:
                    mapped.append({"words": [{**word, "x": ((word["x"] - 20) / 4 + 38) * 3,
                        "y": ((word["y"] - top) / 4 + 273 + row * 25) * 3,
                        "width": word["width"] / 4 * 3, "height": word["height"] / 4 * 3}]})
                    break
    return mapped


def inspect_image(path: str) -> dict:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("截图识别需要Pillow，请安装项目vision可选依赖") from exc
    source = Path(path)
    source_bytes = source.read_bytes()
    with Image.open(source) as image:
        image.load()
        if image.size != (1280, 720):
            raise ValueError("当前仅标定1280×720，其他尺寸需重新标定")
        identity = hashlib.sha256(image.convert("RGB").crop((40, 116, 125, 177)).tobytes()).hexdigest()
        # 只把装备面板交给本地OCR，不处理聊天或其他玩家信息。
        panel = ImageOps.invert(ImageOps.grayscale(image.crop((0, 0, 400, 470)).resize((1200, 1410))))
        details = Image.new("L", (1500, 620), 255)
        for row in range(4):
            strip = image.crop((38, 273 + row * 25, 369, 300 + row * 25)).resize((1324, 108))
            details.paste(ImageOps.invert(ImageOps.grayscale(strip)), (20, 30 + row * 145))
        badge = Image.new("L", (600, 400), 255)
        badge.paste(ImageOps.invert(ImageOps.grayscale(
            image.crop((97, 78, 138, 114)).resize((328, 288)))), (100, 50))
        badge_rgb = list(image.convert("RGB").crop((101, 84, 132, 107)).getdata())
        orange_ratio = sum(r > 150 and 55 < g < 200 and b < 90 and r > g * 1.1
                           for r, g, b in badge_rgb) / len(badge_rgb)
    script = Path(__file__).with_name("windows_ocr.ps1")
    with tempfile.TemporaryDirectory(prefix="e7-ocr-") as temporary:
        png = Path(temporary) / "panel.png"
        payloads = []
        images = [(panel, "zh-Hans-CN"), (details, "zh-Hans-CN")]
        if orange_ratio >= 0.15:
            images.append((badge, "en-US"))
        for bitmap, language in images:
            bitmap.save(png)
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-File", str(script), "-ImagePath", str(png),
                 "-Language", language],
                capture_output=True, timeout=30, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if process.returncode:
                raise RuntimeError("Windows本地OCR失败：" + process.stderr.decode("utf-8", errors="replace").strip())
            payloads.append(json.loads(process.stdout.decode("utf-8-sig")))
    lines = []
    for line in payloads[0]["lines"]:
        words = [w for w in line["words"] if not
                 270 <= (w["y"] + w["height"] / 2) / 3 < 375]
        lines.append({"words": words})
    lines.extend(map_detail_lines(payloads[1]["lines"]))
    badge_text = "".join(line["text"] for line in payloads[2]["lines"]) if len(payloads) == 3 else None
    if badge_text is not None and not re.fullmatch(r"\+\d{1,2}", normalize(badge_text)):
        badge_text = None
    result = parse_panel(lines, badge_absent=orange_ratio < 0.02, badge_text=badge_text)
    primary_badge = text_in_box(lines, (97, 78, 138, 114))
    if (badge_text is not None and re.fullmatch(r"\+\d{1,2}", primary_badge)
            and primary_badge != normalize(badge_text)):
        result["issues"].append("两次OCR强化等级不一致")
        result["fields"]["enhancement"] = None
    if result["page"] == "enhancement" and result["fields"].get("game_score") is None:
        fallback = read_regions(source, {"score": (35, 390, 369, 434)}, language="en-US")["score"]
        match = re.fullmatch(r"(\d+)(?:\(\+\d+\))?", fallback)
        if match:
            result["fields"]["game_score"] = int(match[1])
            result["issues"] = [issue for issue in result["issues"] if issue != "game_score未可靠读取"]
    result.update({"source": str(source.resolve()), "sha256": hashlib.sha256(source_bytes).hexdigest(),
                   "identity": identity,
                   "engine": "Windows.Media.Ocr", "language": payloads[0]["language"],
                   "size": [1280, 720], "uploaded": False})
    return result


def read_regions(path, regions, language="en-US", white_text=False, contrast=False, scale_max=3):
    """本地识别明确指定的少量区域；不读取其余画面。返回原始文字，解析由调用方负责。"""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    if not regions or len(regions) > 16:
        raise ValueError("区域数必须为1～16")
    sheet = Image.new("L", (1600, (len(regions) + 1) * 160 + 20), 255)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 25) if font_path.exists() else ImageFont.load_default()
    # 给引擎提供独立的文本上下文；该行在所有取值区域外，不参与字段结果。
    ImageDraw.Draw(sheet).text((250, len(regions) * 160 + 42), "LOCAL OCR 0123456789", font=font, fill=0)
    with Image.open(path) as source:
        if source.size != (1280, 720):
            raise ValueError("当前仅支持1280×720区域标定")
        for row, (key, box) in enumerate(regions.items()):
            x1, y1, x2, y2 = box
            if not (0 <= x1 < x2 <= 1280 and 0 <= y1 < y2 <= 720):
                raise ValueError("识别区域越界")
            patch = source.crop(box)
            if white_text:
                # 资源数量的白字与材料图标重叠时，先排除彩色图标。
                rgb = patch.convert("RGB")
                mask = Image.new("L", rgb.size)
                mask.putdata([255 if min(r, g, b) > 175 and max(r, g, b) - min(r, g, b) < 65
                              else 0 for r, g, b in rgb.getdata()])
                patch = mask
            width, height = patch.size
            scale = min(scale_max, 1300 / width, 130 / height)
            patch = patch.resize((int(width * scale), int(height * scale)))
            patch = ImageOps.grayscale(patch)
            if contrast:
                patch = ImageOps.autocontrast(patch)
            patch = ImageOps.invert(patch)
            ImageDraw.Draw(sheet).text((20, row * 160 + 42), key, font=font, fill=0)
            sheet.paste(patch, (250, row * 160 + 15))
    with tempfile.TemporaryDirectory(prefix="e7-fields-") as temporary:
        png = Path(temporary) / "regions.png"
        sheet.save(png)
        process = subprocess.run(["powershell.exe", "-NoProfile", "-File",
                                  str(Path(__file__).with_name("windows_ocr.ps1")), "-ImagePath", str(png),
                                  "-Language", language], capture_output=True, timeout=30, check=False,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        raise RuntimeError("区域OCR失败：" + process.stderr.decode("utf-8", errors="replace").strip())
    payload = json.loads(process.stdout.decode("utf-8-sig"))
    words = [word for line in payload["lines"] for word in line["words"]]
    result = {}
    for row, key in enumerate(regions):
        selected = [word for word in words if word["x"] >= 240
                    and row * 160 <= word["y"] + word["height"] / 2 < (row + 1) * 160]
        groups = []
        for word in sorted(selected, key=lambda w: w["y"] + w["height"] / 2):
            center = word["y"] + word["height"] / 2
            tolerance = max(14, word["height"] * .6,
                            max((w["height"] for w in groups[-1][1]), default=0) * .6) if groups else 14
            if not groups or abs(center - groups[-1][0]) > tolerance:
                groups.append((center, [word]))
            else:
                groups[-1][1].append(word)
        result[key] = normalize("".join(word["text"] for _, group in groups
                                       for word in sorted(group, key=lambda w: w["x"])))
    return result
