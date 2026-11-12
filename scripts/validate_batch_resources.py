"""真实批量强化前后截图资源核对；不连接模拟器，不执行输入。"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.batch_resources import inspect_resources, MATERIALS
from e7_assistant.workflow_screen import inspect_screen


def main():
    pages = []
    for name in ('17-batch-target.png','18-batch-result.png'):
        source = ROOT/'docs/assets/user-workflow-2026-11-09'/name
        resources = inspect_resources(inspect_screen(source))
        pages.append({'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                      'resources':asdict(resources)})
    prepared,after = [page['resources'] for page in pages]
    expected_remaining = {'gold':343327724,'powder':95834,'jewelry_powder':74554,
                          'lesser_stone':0,'jewelry_lesser_stone':2169,'greater_stone':0,
                          'jewelry_greater_stone':207,'epic_stone':0,'jewelry_epic_stone':0}
    errors = []
    if prepared['remaining'] != expected_remaining or prepared['target']!=6:
        errors.append('强化预览余额或目标与目视真值不符')
    expected_cost = {'gold':1379200,**{key:862 if key=='powder' else 0 for key,_ in MATERIALS}}
    actual = {key:prepared['available'][key]-after['available'][key] for key in expected_cost}
    if actual != expected_cost or prepared['gold_cost']!=1379200 or prepared['reserved']['powder']!=862:
        errors.append('前后实际差额与预览费用不符')
    if after['gold_cost'] or any(after['reserved'].values()) or after['target'] is not None:
        errors.append('结果页登记状态未清空')
    output = {'scope':'两张用户截图离线核对；原始持有量由游戏预览的剩余+预留还原，非独立未登记截图',
              'pages':pages,'observed_delta':actual,'expected_cost':expected_cost,'errors':errors}
    (ROOT/'runs/batch-resource-validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'errors':errors,'observed_delta':actual,
                      'zero_recovered':[p['resources']['evidence']['zero_recovered'] for p in pages]},ensure_ascii=False))
    return 1 if errors else 0


if __name__=='__main__':
    raise SystemExit(main())
