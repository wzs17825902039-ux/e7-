"""七张既有实机/用户截图的等级回归；仅离线，不发送游戏输入。"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.batch_selection import BatchSelectionDriver


def main():
    sources = sorted((ROOT/'docs/assets/inventory-mode-2026-11-09').glob('*.png'))
    sources.append(ROOT/'docs/assets/user-workflow-2026-11-09/15-select-unenhanced.png')
    counts = [21, 14, 26, 26, 26, 21, 21]
    results, errors = [], []
    for source, count in zip(sources, counts):
        report = inspect_inventory(inspect_screen(source))
        unknown = [i for i,c in enumerate(report['cards']) if c['level'] is None]
        wrong = [i for i,c in enumerate(report['cards']) if c['level'] not in (None, 85)]
        result = {'file': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                  'expected_count': count, 'cards': len(report['cards']), 'unknown_level': unknown,
                  'wrong_level': wrong,
                  'unknown_card': [i for i,c in enumerate(report['cards']) if not c['known']],
                  'recognition': report}
        results.append(result)
        if len(report['cards']) != count or unknown or wrong:
            errors.append({'file': source.name, 'reason': '等级未完整正确读取或数量不符'})
        print(json.dumps({k:v for k,v in result.items() if k not in {'recognition','sha256'}},
                         ensure_ascii=False), flush=True)
    try:
        BatchSelectionDriver._verify_click(results[2]['recognition'], results[3]['recognition'], (0,0))
        click_verified = True
    except ValueError as exc:
        click_verified = False
        errors.append({'reason': str(exc)})
    output = {'scope': '七张已有截图，同源回归；不是独立泛化评测或实机自动选装证明',
              'expected_level': 85, 'paired_click_verified': click_verified,
              'errors': errors, 'samples': results}
    (ROOT/'runs/inventory-level-validation.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'paired_click_verified':click_verified,'errors':errors}, ensure_ascii=False))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
