"""只读结算已出现满包弹窗的打造会话，再继续正式流程。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.craft_reservation import CraftReservation
from e7_assistant.forge_loop import LiveForgeLoop
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original',type=Path)
    args=parser.parse_args()
    original=args.original.resolve()
    old=json.loads((original/'result.json').read_text(encoding='utf8'))
    events=[json.loads(line) for line in (original/'events.jsonl').read_text(encoding='utf8').splitlines()]
    config=next(e for e in events if e['kind']=='live_test_configuration')
    commits=[e for e in events if e['kind']=='craft_commit_intent']
    results=[e for e in events if e['kind']=='craft_result_observed']
    if (old['state']!='failed' or not old['outcome_unknown'] or not commits or not results
            or results[-1]['accounting']['confirmed_attempts']!=len(commits)
            or events.index(results[-1])<events.index(commits[-1])):
        raise ValueError('没有全部已观察结果的失败打造会话，不恢复')
    options=WorkflowOptions(**config['options']);limits=Limits(**config['limits'])
    directory=ROOT/'runs'/('full-craft-recovery-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(options.action_interval)
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=LiveWorkflowTask(nav,options,policy,limits,control,journal)
    task.enhancement_guard.check_clear();task.disposal_guard.check_clear()
    pending=task.craft_guard.read()
    if not pending or Path(pending['run_directory']).resolve()!=original or pending['action']!='craft':
        raise ValueError('待结算记录不属于原任务')
    task.ledger.spent.update(old['spent']);task.ledger.steps=old['steps']
    before=pending['before']
    if options.track_craft_gold or set(before['cost'])!={'craft_material'}:
        raise ValueError('此工具只结算已授权的不核账金币模式')
    reservation=CraftReservation(task.ledger,before['resources'],before['cost'])
    for _ in commits:reservation.mark_commit()
    screen=nav.read()
    if screen.page!='inventory_full':
        raise ValueError('现场没有完整满包提示，不操作')
    forge=LiveForgeLoop(nav,options,task.ledger,control,journal,guard=task.craft_guard)
    final=forge.preview(nav.navigate('forge'))
    stable=forge.preview(nav.read())
    if asdict(final)|{'image':None}!=asdict(stable)|{'image':None} or task.craft_guard.read()!=pending:
        raise ValueError('两次材料观察或待结算记录不一致')
    actual=reservation.settle(stable.resources)
    journal.emit('original_craft_settled',actual=actual,batches=reservation.committed,image=stable.image,
                 accounting=reservation.evidence(),original=str(original))
    task.craft_guard.settle(pending['operation_id'])
    journal.emit('live_test_configuration',options=asdict(options),limits=asdict(limits),
                 carried_spent=dict(task.ledger.spent),carried_steps=task.ledger.steps)
    result=task.run();result['directory']=str(directory)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='complete')


if __name__=='__main__':raise SystemExit(main())
