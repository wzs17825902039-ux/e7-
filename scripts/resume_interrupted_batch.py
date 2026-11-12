"""核对已结算批次及中断上锁现场；用初始记录恢复红装前两档速度成长。"""
import argparse
from dataclasses import asdict,replace
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_vision import inspect_batch
from e7_assistant.batch_sale_vision import content_proof
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import BatchItem,WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator
from PIL import Image


def events(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf8').splitlines()]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('original',type=Path)
    p.add_argument('--entry-events',type=Path,required=True)
    p.add_argument('--previous-result',type=Path,required=True)
    p.add_argument('--selection',type=Path,required=True)
    p.add_argument('--adb-path',required=True)
    args=p.parse_args()
    old=events(args.original/'events.jsonl')
    entry=[e for e in events(args.entry_events) if e['kind']=='batch_entry_verified'][-1]
    settlement=[e for e in old if e['kind']=='settled']
    commits=[e for e in old if e['kind']=='batch_enhance_commit_intent']
    if not settlement or len(settlement)!=len(commits) or any(e['kind']=='batch_sale_commit_intent' for e in old):
        raise ValueError('存在尚未结算操作或出售，不能按此路径恢复')
    selection=json.loads(args.selection.read_text(encoding='utf8'))
    initial=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in entry['equipment']]
    if len(initial)!=selection['selected_count'] or len(initial)!=len(selection['registered']):
        raise ValueError('初始入口数量不符')
    decisions=[e for e in old if e['kind']=='equipment_decision'][-len(initial):]
    if [e['equipment']['equipment_id'] for e in decisions]!=[i.equipment.equipment_id for i in initial]:
        raise ValueError('初始记录与中断批次身份不同')
    directory=ROOT/'runs'/('interrupted-batch-resume-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    nav=WorkflowNavigator(Adb(args.adb_path,'127.0.0.1:16384',control),directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=LiveWorkflowTask(nav,WorkflowOptions(action_interval=.2),policy,Limits(max_steps=600),control,journal)
    for guard in (task.enhancement_guard,task.disposal_guard,task.craft_guard):guard.check_clear()
    nav.batch_inventory_context=selection['inventory_context']
    screen,current,resources=task.driver.observe_selection_result(initial)
    if resources.has_preview:raise ValueError('存在材料预览，不恢复')
    reference=[e['image'] for e in old if e['kind']=='result_observed'][-1]
    lock_intents={e['token'] for e in old if e['kind']=='batch_lock_intent'}
    with Image.open(reference) as before,Image.open(screen.source) as after:
        for index,(base,item) in enumerate(zip(initial,current)):
            content_proof(before,after,index,strict=True,attributes_only=True)
            if item.locked is None or (item.locked!=base.locked and not (item.locked is True and item.token in lock_intents)):
                raise ValueError('当前锁状态缺少对应操作证据')
            if item.equipment.enhancement<base.equipment.enhancement or any(item.equipment.stats.get(k,-1)<v for k,v in base.equipment.stats.items()):
                raise ValueError('当前装备属性或阶段与初始记录不符')
            if item.equipment.rarity=='red' and base.equipment.enhancement<3 and 6<=item.equipment.enhancement<9:
                current[index]=replace(item,equipment=replace(item.equipment,
                    early_speed_increased=item.equipment.stats.get('speed',0)>base.equipment.stats.get('speed',0)))
    _,stable,stable_resources=task.driver.observe_selection_result(current)
    task.driver.unchanged(current,stable);task.driver.same_resources(resources,stable_resources)
    previous=json.loads(args.previous_result.read_text(encoding='utf8'))
    task.ledger.steps=settlement[-1]['steps']
    task.untracked_enhancements=previous['untracked_enhancements']+len(settlement)
    journal.emit('interrupted_batch_verified',original=str(args.original),image=screen.source,
                 items=[asdict(i) for i in stable],confirmation_repeated=False)
    result=task.run_batch(stable,verified_recovery=(stable,0))
    if result['state']=='complete':
        task.completed_batches+=1
        try:task.enhance_inventory_batches()
        except Exception as exc:
            result['state']='failed';journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result.update(items=[asdict(i) for i in task.last_batch],batches=task.completed_batches,
                  steps=task.ledger.steps,untracked_enhancements=task.untracked_enhancements,
                  outcome_unknown=task.uncertain,last_image=nav.last_image)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),'state':result['state']},ensure_ascii=False))


if __name__=='__main__':main()
