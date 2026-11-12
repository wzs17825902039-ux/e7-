"""读取实机采样文件验证零选择/一件选择布局，不发送游戏输入。"""
import hashlib
import json
from pathlib import Path
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.inventory_mode_vision import inspect_zero_selection
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


def main():
    directory = ROOT/'docs/assets/inventory-mode-2026-11-09'
    reports = []
    for source in sorted(directory.glob('*.png')):
        expected = 'inventory_batch_selection_empty' if int(source.name[:2]) <= 3 else 'inventory_batch_selection'
        screen = inspect_screen(source)
        result = {'file':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                  'expected':expected,'page':screen.page,'matched':screen.page==expected,'words':screen.words}
        if screen.page == 'inventory_batch_selection_empty':
            result['mode_evidence'] = inspect_zero_selection(source,screen.words)
            result['selected_count'] = 0
        else:
            counts = [int(match[1]) for w in screen.words if w['confidence'] >= .9
                      and (match := re.fullmatch(r'批量强化\((\d+)\)',w['text']))]
            result['selected_count'] = counts[0] if len(counts) == 1 else None
        result['expected_selected_count'] = 1 if int(source.name[:2]) in (4,5) else 0
        result['matched'] = result['matched'] and result['selected_count'] == result['expected_selected_count']
        reports.append(result)
        print(source.name,screen.page,flush=True)
    # 入口完整OCR：第二行整页只识别一个85，但不允许漏掉这行。
    initial = inspect_inventory(inspect_screen(directory/'01-zero-selection.png'))
    errors = []
    if initial['selected_count'] != 0 or len(initial['cards']) != 21:
        errors.append('入口零勾选数或完整可见行数错误')
    output = {'scope':'本次实机采样的六张页面识别和入口完整行回归；非完整背包扫描验收',
              'reports':reports,'initial_recognition':initial,'errors':errors,
              'notice':'尾部采样保留用于后续标定；本报告不证明尾行及末尾判断已经实现',
              'live_input':False}
    (ROOT/'runs/inventory-mode-validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pages_matched':sum(r['matched'] for r in reports),'pages':len(reports),
                      'initial_cards':len(initial['cards']),
                      'unknown_cards':[i for i,c in enumerate(initial['cards']) if not c['known']],
                      'errors':errors},ensure_ascii=False))
    return 0 if not errors and all(r['matched'] for r in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
