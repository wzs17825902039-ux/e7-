"""背包15号图与批量17号图中同一件装备的初始属性核对。"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.inventory_detail import read_detail
from e7_assistant.workflow_screen import inspect_screen


def main():
    source = ROOT/'docs/assets/user-workflow-2026-11-09/15-select-unenhanced.png'
    screen = inspect_screen(source)
    detail = read_detail(screen,{'rarity':'red','level':85,'enhancement':0})
    equipment = asdict(detail['equipment'])
    expected = {'rarity':'red','level':85,'enhancement':0,'slot':'helmet','game_score':23,
                'stats':{'speed':3,'def_flat':28,'effectiveness':4,'atk_pct':5}}
    errors = {key:{'expected':value,'actual':equipment[key]} for key,value in expected.items() if equipment[key]!=value}
    batch_file = ROOT/'runs/batch-ocr-validation.json'
    batch = json.loads(batch_file.read_text(encoding='utf8'))['pages'][0]
    batch_source = ROOT/'docs/assets/user-workflow-2026-11-09/17-batch-target.png'
    if batch['sha256'] != hashlib.sha256(batch_source.read_bytes()).hexdigest():
        raise ValueError('批量报告与截图哈希不符')
    record = next(record for record in batch['recognition']['records'] if record['index']==15)
    cross_errors = {key:{'inventory':equipment[key],'batch':record['equipment'][key]}
                    for key in expected if equipment[key]!=record['equipment'][key]}
    if record.get('main') != {'stat':'hp_flat','value':540} or tuple(detail['main']) != ('生命值','540'):
        cross_errors['main'] = '主属性未完整匹配'
    output = {'scope':'两张用户截图的一件已知装备；不证明完整批次或实机入口成功',
              'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'detail':{**detail,'equipment':equipment},'errors':errors,'cross_errors':cross_errors,
              'batch_index':15,'batch_report':str(batch_file)}
    (ROOT/'runs/inventory-detail-validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'errors':errors,'cross_errors':cross_errors,'equipment':equipment},ensure_ascii=False))
    return 1 if errors or cross_errors else 0


if __name__=='__main__':
    raise SystemExit(main())
