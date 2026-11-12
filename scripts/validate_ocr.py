"""将本机截图OCR与既有人工标注对照；不连接模拟器，不执行游戏动作。"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e7_assistant.vision import inspect_image


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    truth = json.loads((ROOT / "examples/live-armor-replay.json").read_text(encoding="utf-8"))
    images = ["enhance-ready.png", "trial-plus3-after.png", "trial-plus6-after.png", "trial-plus9-after.png"]
    keys = ["rarity", "slot", "level", "enhancement", "game_score", "stats"]
    checks = []
    for filename, expected in zip(images, truth, strict=True):
        observed = inspect_image(str(ROOT / "captures" / filename))
        mismatches = {key: {"expected": expected[key], "actual": observed["fields"].get(key)}
                      for key in keys if observed["fields"].get(key) != expected[key]}
        checks.append({"file": filename, "sha256": observed["sha256"],
                       "matched_fields": len(keys) - len(mismatches), "mismatches": mismatches,
                       "issues": observed["issues"], "automation_ready": observed["automation_ready"]})
    home = inspect_image(str(ROOT / "captures/home.png"))
    report = {
        "scope": "同一件紫色铠甲的四个阶段，小样本，不代表其他装备的准确率",
        "expected_fields": len(images) * len(keys),
        "matched_fields": sum(item["matched_fields"] for item in checks),
        "home_rejected": home["page"] == "unknown",
        "checks": checks,
        "limitations": ["名称OCR有漏字", "成长次数可能漏读，缺失不等于零",
                        "未覆盖红装/其他部位/其他分辨率/弹窗/动画", "自动点击未启用"],
    }
    target = ROOT / "runs/ocr-validation.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if (report["matched_fields"] == report["expected_fields"]
                 and report["home_rejected"] and all(not c["issues"] for c in checks)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
