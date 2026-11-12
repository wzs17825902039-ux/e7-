"""离线回放长任务中已结算的次数截图；不连接游戏。"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.legendary_crafting import read_charges

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('events',type=Path)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
events=[json.loads(line) for line in args.events.read_text(encoding='utf8').splitlines()]
cases=[(event['image'],event['charges_after']) for event in events
       if event.get('kind')=='legendary_craft_settled']
for name,value in [('forge-charges-77.png',77),('forge-charges-266.png',266),
                   ('forge-charges-271.png',271),('after-single-craft-170.png',170),
                   ('net-count-260-after.png',260)]:
    cases.append((str(ROOT/'docs/assets/legendary-crafting'/name),value))
cases.append((str(ROOT/'docs/assets/legendary-crafting/forge-charges-8.png'),8))
checks=[]
for path,expected in cases:
    try:
        actual=read_charges(path)
        checks.append({'image':path,'expected':expected,'actual':actual,'ok':actual==expected})
    except ValueError as exc:
        checks.append({'image':path,'expected':expected,'error':str(exc),'ok':False})
report={'live_input':False,'cases':len(checks),'passed':sum(check['ok'] for check in checks),
        'ok':bool(checks) and all(check['ok'] for check in checks),'checks':checks}
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({key:value for key,value in report.items() if key!='checks'},ensure_ascii=False))
raise SystemExit(0 if report['ok'] else 1)
