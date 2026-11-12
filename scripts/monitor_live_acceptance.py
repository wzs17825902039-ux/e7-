"""只读汇总原生客户端验收日志；不发送游戏输入或推断未记录的成功。"""
import argparse
from collections import Counter
import json
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory',type=Path)
parser.add_argument('--compact',action='store_true')
args=parser.parse_args()
rows=(args.directory/'events.jsonl').read_text(encoding='utf8').splitlines()
events=[]
for index,line in enumerate(rows):
    try:events.append(json.loads(line))
    except json.JSONDecodeError:
        if index!=len(rows)-1:raise
counts=Counter(e['kind'] for e in events)
def latest(kind):
    return next((e for e in reversed(events) if e['kind']==kind),None)
report={'task':args.directory.name,'latest_time':events[-1]['time'] if events else None,
        'stage':latest('workflow_stage'),'craft_commits':counts['craft_commit_intent'],
        'craft_settled':latest('craft_session_settled'),'cleanup':latest('cleanup_settled'),
        'batches':counts['workflow_batch_finished'],'rounds':counts['round_finished'],
        'enhancement_commits':counts['batch_enhance_commit_intent'],
        'last_screen':latest('workflow_screen'),'last_decision':latest('equipment_decision'),
        'failure':latest('failed'),'finished':latest('finished')}
if args.compact:
    timings=[e['seconds'] for e in events if e['kind']=='batch_ocr_timing']
    report={'task':report['task'],'time':report['latest_time'],
            'stage':(report['stage'] or {}).get('stage'),'craft_commits':report['craft_commits'],
            'initial_removed':sum(e['removed'] for e in events if e['kind']=='cleanup_settled'),
            'sold':sum(len(e['disposed']) for e in events if e['kind']=='batch_sale_settled'),
            'locks':sum(len(e['tokens']) for e in events if e['kind']=='lock_verified'),
            'batches':report['batches'],'rounds':report['rounds'],
            'enhancement_commits':report['enhancement_commits'],
            'page':(report['last_screen'] or {}).get('page'),
            'ocr_seconds_latest':timings[-1] if timings else None,
            'failure':report['failure'],'finished':report['finished']}
print(json.dumps(report,ensure_ascii=False,indent=2))
