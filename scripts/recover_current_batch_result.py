"""只读核验当前未结算确认；默认不继续强化，不重发旧确认。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.disposal_guard import BatchEnhancementGuard
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import BatchItem,WorkflowTask,WorkflowOptions,verify_batch
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    directory=ROOT/'runs'/('current-result-recovery-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    serial='127.0.0.1:16384'
    guard=BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial)
    pending=guard.read()
    if (not pending or Path(pending['run_directory'])!=ROOT/'runs/current-batch-f23164a3'
            or pending['confirmation']['target']!=3 or len(pending['before']['items'])!=16):
        raise ValueError('未找到指定原批次未结算确认，不操作')
    (directory/'original-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf8')
    before=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked'])
            for i in pending['before']['items']]
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    selection=json.loads((ROOT/'runs/current-batch-f23164a3/selection.json').read_text(encoding='utf8'))
    nav.batch_inventory_context=selection['inventory_context']
    driver=BatchEnhancementDriver(nav,guard=guard,track_resources=False,purple_speed_only=True,
                                  ignore_equipment_level=True)
    _,current,resources=driver.observe(before)
    verify_batch(before,current,3)
    if resources.has_preview:
        raise ValueError('仍有强化预览，不结算也不重发')
    screen,stable,stable_resources=driver.observe(before)
    driver.unchanged(current,stable);driver.same_resources(resources,stable_resources)
    if guard.read()!=pending:raise ValueError('原未结算确认已变化')
    result={'state':'recovered','items':[asdict(i) for i in stable],
            'original_target':3,'image':screen.source,'resource_tracking':False}
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    journal.emit('authorized_result_recovered',**result)
    guard.settle(pending['operation_id'])
    if '--continue' in sys.argv:
        policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
        task=WorkflowTask(driver,WorkflowOptions(first_target=3),policy,Limits(max_steps=5),control,journal)
        task.ledger.steps=1;task.untracked_enhancements=1
        result=task.run_batch(stable,verified_recovery=(before,3))
        if not result['outcome_unknown']:
            nav.navigate('inventory');result['returned_inventory']=True
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),'state':result['state']},ensure_ascii=False))


if __name__=='__main__':main()
