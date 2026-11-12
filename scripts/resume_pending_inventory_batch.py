"""只读结算指定运行的强化回执，再继续整包；不重发旧确认。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_vision import inspect_batch
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import BatchItem,WorkflowOptions,verify_batch
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb-path',default=r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe')
    parser.add_argument('original',type=Path)
    args=parser.parse_args()
    directory=ROOT/'runs'/('pending-inventory-resume-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    adb=Adb(args.adb_path,'127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=LiveWorkflowTask(nav,WorkflowOptions(first_target=3,scan_pages=150),policy,Limits(max_steps=600),control,journal)
    task.disposal_guard.check_clear();task.craft_guard.check_clear()
    pending=task.enhancement_guard.read()
    if not pending or Path(pending['run_directory']).resolve()!=args.original.resolve():
        raise ValueError('未找到指定运行的强化待结算记录')
    (directory/'original-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf8')
    before=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in pending['before']['items']]
    nav.batch_inventory_context=pending['before'].get('inventory_context')
    target=pending['confirmation']['target']
    screen=nav.read()
    if screen.page!='batch_enhancement':raise ValueError('不是原批量页，只读恢复停止')
    report=inspect_batch(screen.source,{i:x.equipment.slot for i,x in enumerate(before)},
                         ignore_levels=policy.ignore_equipment_level,require_score=False,
                         ignore_purple_main=True,purple_speed_only=True,known_items=before)
    if report['issues']:raise ValueError(str(report['issues']))
    nav.batch_speed_rows=report.get('speed_rows',{})
    nav.batch_ignore_equipment_level=policy.ignore_equipment_level
    task.driver=BatchEnhancementDriver(nav,guard=task.enhancement_guard,track_resources=False,purple_speed_only=True)
    screen,current,resources=task.driver.observe(before)
    verify_batch(before,current,target)
    if resources.has_preview:raise ValueError('仍有强化预览，不结算')
    screen,stable,stable_resources=task.driver.observe_unchanged(current)
    task.driver.unchanged(current,stable);task.driver.same_resources(resources,stable_resources)
    if task.enhancement_guard.read()!=pending:raise ValueError('待结算记录发生变化')
    journal.emit('enhancement_receipt_recovered',target=target,items=[asdict(i) for i in stable],image=screen.source)
    task.enhancement_guard.settle(pending['operation_id'])
    previous=json.loads((args.original/'result.json').read_text(encoding='utf8'))
    # 原运行在结果结算前停止，该次已确认成功的强化还未计入原账本。
    task.ledger.steps=previous['steps']+1
    task.untracked_enhancements=previous['untracked_enhancements']+1
    result=task.run_batch(stable,verified_recovery=(before,target))
    if result['state']=='complete':
        task.completed_batches+=1
        try:task.enhance_inventory_batches()
        except Exception as exc:
            result['state']='failed';journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result.update(scope='inventory_only',batches=task.completed_batches,steps=task.ledger.steps,
                  untracked_enhancements=task.untracked_enhancements,outcome_unknown=task.uncertain,
                  last_image=nav.last_image,directory=str(directory),items=[asdict(i) for i in task.last_batch])
    journal.emit('finished',**result)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),'state':result['state'],'batches':task.completed_batches},ensure_ascii=False))


if __name__=='__main__':main()
