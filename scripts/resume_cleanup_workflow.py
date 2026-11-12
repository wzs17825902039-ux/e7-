"""从已确认打造满包、尚未确认清理的本任务记录恢复；不重发未知确认。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.initial_cleanup import CleanupInventory,inspect_inventory,verify_cleanup
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator
from e7_assistant.workflow_screen import inspect_screen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original',type=Path)
    parser.add_argument('--next-rounds',type=int,default=0)
    parser.add_argument('--settle-cleanup',action='store_true',help='只核对已提交清理的回执后继续，不重复确认')
    args=parser.parse_args()
    original=args.original.resolve()
    old=json.loads((original/'result.json').read_text(encoding='utf8'))
    events=[json.loads(line) for line in (original/'events.jsonl').read_text(encoding='utf8').splitlines()]
    if (old['state']!='failed' or old['outcome_unknown']
            or not any(e['kind']=='workflow_forge_finished' and e['result']['state']=='inventory_full' for e in events)
            or any(e['kind']=='cleanup_commit_intent' for e in events)):
        raise ValueError('原记录不是已满包且清理未提交的恢复点')
    expected=inspect_inventory(inspect_screen(old['last_image']),track_gold=False)
    config=next(e for e in events if e['kind']=='live_test_configuration')
    options=WorkflowOptions(**{**config['options'],'rounds':max(1,args.next_rounds)})
    limits=Limits(**config['limits'])
    directory=ROOT/'runs'/('cleanup-workflow-resume-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(options.action_interval)
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=LiveWorkflowTask(nav,options,policy,limits,control,journal)
    task.ledger.spent.update(old['spent']);task.ledger.steps=old['steps']
    state='failed';rounds=0
    try:
        task.craft_guard.check_clear();task.enhancement_guard.check_clear()
        if args.settle_cleanup:
            pending=task.disposal_guard.read()
            if not pending or pending['action']!=options.initial_disposal:
                raise ValueError('没有可核对的初次清理记录')
            before=CleanupInventory(**pending['before'])
            if (before.count,before.capacity,before.selected)!=(expected.count,expected.capacity,expected.selected):
                raise ValueError('待结算记录与原满包现场不一致')
            current=inspect_inventory(nav.read(),track_gold=False)
            receipt=verify_cleanup(before,current,pending['action'])
            stable=inspect_inventory(nav.read(),track_gold=False)
            if (stable.count,stable.capacity,stable.selected,stable.gold)!=(current.count,current.capacity,current.selected,current.gold):
                raise ValueError('清理回执未稳定')
            journal.emit('cleanup_settled',operation_id=pending['operation_id'],original_record=pending,**receipt)
            task.disposal_guard.settle(pending['operation_id'])
            task.enhance_inventory_batches()
        else:
            task.disposal_guard.check_clear()
            screen=nav.read()
            if screen.page=='extract_confirmation':
                screen=nav.transition('cancel_extract')
            current=inspect_inventory(screen,track_gold=False)
            if (current.count,current.capacity,current.selected)!=(expected.count,expected.capacity,expected.selected):
                raise ValueError('现场数量或勾选与原记录不同，不能恢复')
            journal.emit('resume_verified_cleanup',original=str(original),inventory=asdict(current))
            # 退出本任务留下的整理勾选；正式清理重新执行用户预设快速选择。
            nav.navigate('inventory')
            task.finish_inventory_round()
        rounds=1
        journal.emit('round_finished',round=rounds,recovered_from=str(original))
        state='complete'
        if args.next_rounds:
            continuation=task.run()
            rounds+=continuation['rounds'];state=continuation['state']
    except Exception as exc:
        journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result={'state':state,'scope':'cleanup_recovery_and_continuation','rounds':rounds,
            'batches':task.completed_batches,'steps':task.ledger.steps,'spent':task.ledger.spent,
            'outcome_unknown':task.uncertain,'untracked_enhancements':task.untracked_enhancements,
            'last_image':nav.last_image,'directory':str(directory)}
    journal.emit('finished',**result)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return int(state!='complete')


if __name__=='__main__':raise SystemExit(main())
