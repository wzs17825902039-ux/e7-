"""真实用户选装截图的只读验证；不连接设备或发送输入。"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


def main():
    source = ROOT / 'docs/assets/user-workflow-2026-11-09/15-select-unenhanced.png'
    screen = inspect_screen(source)
    report = inspect_inventory(screen)
    errors = []
    if report['selected_count'] != 16 or len(report['cards']) != 21:
        errors.append('可见卡片数或总勾选数错误')
    unknown = []
    rarities = ['purple','red','red','purple','purple','purple','purple',
                'red','purple','red','purple','red','purple','purple',
                'purple','red','red','red','purple','purple','red']
    for index, card in enumerate(report['cards']):
        expected = {'enhancement': 3 if index == 18 else 0, 'selected': index < 16,
                    'level':85, 'rarity':rarities[index]}
        for key, value in expected.items():
            if card[key] is not None and card[key] != value:
                errors.append({'index':index,'field':key,'actual':card[key],'expected':value})
        if not card['known']:
            unknown.append(index)
    output = {'scope':'用户15号截图；同源回归，不是完整扫描或实机选装证明',
              'sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'errors':errors,
              'unknown_cards':unknown, 'recognition':report, 'words':screen.words}
    (ROOT / 'runs/inventory-selection-vision.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'cards':len(report['cards']),'unknown_cards':unknown,'errors':errors},ensure_ascii=False))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
