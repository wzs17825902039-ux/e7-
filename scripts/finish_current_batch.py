"""恢复原批结束整理；只接受指定结果和原入口数量，不启动新强化。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.disposal_guard import BatchEnhancementGuard,DisposalGuard
from e7_assistant.rules import Equipment,Policy,evaluate
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import BatchItem,WorkflowTask,WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    directory=ROOT/'runs'/('current-batch-finish-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2);serial='127.0.0.1:16384'
    guard=BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial)
    guard.check_clear();DisposalGuard(ROOT/'runs/disposal-pending',serial).check_clear()
    previous=json.loads((ROOT/'runs/current-result-recovery-5c000646/result.json').read_text(encoding='utf8'))
    items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in previous['items']]
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    if len(items)!=16 or any(i.selected or evaluate(i.equipment,policy).action=='continue' for i in items):
        raise ValueError('原批次尚有强化或勾选，不执行结束整理')
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    selection=json.loads((ROOT/'runs/current-batch-f23164a3/selection.json').read_text(encoding='utf8'))
    nav.batch_inventory_context=selection['inventory_context']
    driver=BatchEnhancementDriver(nav,guard=guard,track_resources=False,ignore_equipment_level=True)
    _,observed,_=driver.observe(items);driver.unchanged(items,observed)
    task=WorkflowTask(driver,WorkflowOptions(first_target=3),policy,Limits(max_steps=5),control,journal)
    task.ledger.steps=3;task.untracked_enhancements=3
    result=task.run_batch(observed)
    result['restored_inventory_context']=nav.batch_inventory_context
    result['last_image']=nav.last_image
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),'state':result['state']},ensure_ascii=False))


if __name__=='__main__':main()
