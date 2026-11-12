"""核对指定运行已提交的出售回执并继续背包；不重发出售。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_sale import BatchSaleDriver
from e7_assistant.batch_sale_vision import SaleConfirmation,verify_sale_survivors
from e7_assistant.initial_cleanup import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import BatchItem,WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('original',type=Path)
    parser.add_argument('--survivor-evidence',type=Path,help='已保存的两张出售后保留装备截图所在恢复运行')
    args=parser.parse_args()
    directory=ROOT/'runs'/('pending-sale-resume-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=LiveWorkflowTask(nav,WorkflowOptions(first_target=3,scan_pages=150),policy,Limits(max_steps=600),control,journal)
    task.enhancement_guard.check_clear();task.craft_guard.check_clear()
    pending=task.disposal_guard.read()
    if not pending or Path(pending['run_directory']).resolve()!=args.original.resolve() or pending['action']!='sell':
        raise ValueError('未找到指定已提交出售记录')
    (directory/'original-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf8')
    baseline=pending['before']
    items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in baseline['items']]
    rejected=set(baseline['rejected']);protected={i.token for i in items}-rejected
    events=[json.loads(l) for l in (args.original/'events.jsonl').read_text(encoding='utf8').splitlines()]
    commit_index=next(i for i,e in enumerate(events) if e['kind']=='batch_sale_commit_intent'
                      and e['operation_id']==pending['operation_id'])
    reference=[e['image'] for e in events[:commit_index]
               if e['kind']=='workflow_screen' and e['page']=='batch_enhancement'][-1]
    state='failed'
    try:
        screen=nav.read()
        if args.survivor_evidence and screen.page in {'inventory','inventory_batch_selection','inventory_batch_selection_empty'}:
            evidence=[json.loads(l) for l in (args.survivor_evidence/'events.jsonl').read_text(encoding='utf8').splitlines()]
            frames=[e['image'] for e in evidence if e['kind']=='workflow_screen' and e['page']=='batch_enhancement']
            if len(frames)<2:raise ValueError('缺少两张保留装备回执证据')
            for path in frames[:2]:verify_sale_survivors(inspect_screen(path),reference,items,rejected)
            screen=nav.navigate('inventory')
            for frame in (screen,nav.read()):
                inventory=inspect_inventory(frame,track_gold=False)
                if (inventory.count,inventory.capacity)!=(baseline['inventory_count']-len(rejected),baseline['capacity']):
                    raise ValueError('当前背包减量与出售回执不符')
            journal.emit('batch_sale_settled',operation_id=pending['operation_id'],disposed=sorted(rejected),
                         survivor_frames=frames[:2],inventory_count=inventory.count)
            task.disposal_guard.settle(pending['operation_id'])
        else:
            BatchSaleDriver(task.driver,guard=task.disposal_guard).settle_result(items,rejected,protected,
                baseline['resources'],reference,SaleConfirmation(**pending['confirmation']),
                baseline['inventory_count'],baseline['capacity'],pending['operation_id'],screen.page)
        task.completed_batches=1
        task.enhance_inventory_batches()
        state='complete'
    except Exception as exc:
        journal.emit('failed',message=str(exc))
    result={'state':state,'scope':'sale_receipt_and_inventory','batches':task.completed_batches,
            'steps':task.ledger.steps,'untracked_enhancements':task.untracked_enhancements,
            'outcome_unknown':bool(task.disposal_guard.read() or task.enhancement_guard.read() or task.uncertain),
            'last_image':nav.last_image,'items':[asdict(i) for i in getattr(task,'last_batch',[])],
            'directory':str(directory)}
    journal.emit('finished',**result)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
