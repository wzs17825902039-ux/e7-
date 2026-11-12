"""固定样本尾行与底部证据验证；只读文件，不连接游戏。"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.inventory_tail_vision import inspect_tail
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


def main():
    directory = ROOT/'docs/assets/inventory-mode-2026-11-09'
    records,errors = [],[]
    for path in sorted(directory.glob('*.png')):
        index = int(path.name[:2])
        screen = inspect_screen(path)
        observed = inspect_tail(screen)
        expected_count = 5 if index in (3,4,5) else None
        expected_bottom = index in (3,5)
        if (observed['tail_count'],observed['end_verified']) != (expected_count,expected_bottom):
            errors.append({'file':path.name,'expected_count':expected_count,'expected_bottom':expected_bottom})
        records.append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'expected_count':expected_count,'expected_bottom':expected_bottom,'observed':observed})
        print(path.name,observed['tail_count'],observed['end_verified'],flush=True)
    recognition = inspect_inventory(inspect_screen(directory/'03-zero-selection-tail.png'))
    last = [c for c in recognition['cards'] if c['row']==recognition['tail_layout']['row']]
    if len(recognition['cards']) != 26 or len(last) != 5:
        errors.append('尾行接入后卡片数量错误')
    for card in last:
        expected = {'level':85,'rarity':'purple','enhancement':0,'selected':False}
        if not card['known'] or any(card[key] != value for key,value in expected.items()):
            errors.append({'column':card['column'],'message':'尾行未完整识别为已标注的未强化紫装'})
    output = {'scope':'固定1280×720背景模板与六张同实例实机样本；不是跨分辨率或完整扫描准确率',
              'records':records,'recognition':recognition,'errors':errors,'live_input':False,
              'notice':'模板来自普通背包单件尾行；验证为后续批量选择五件尾行，静态背景相同，非独立背景域'}
    (ROOT/'runs/inventory-tail-validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'cases':len(records),'tail_cards':len(last),'all_visible_cards':len(recognition['cards']),
                      'errors':errors},ensure_ascii=False))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
