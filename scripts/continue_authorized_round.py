"""只恢复已授权16件的+3结果；不重发旧确认，不启动新批次。"""
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
    directory=ROOT/'runs'/('authorized-round-recovery-'+uuid.uuid4().hex[:8])
    journal=Journal(directory)
    control=TaskControl(.2)
    serial='127.0.0.1:16384'
    guard=BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial)
    pending=guard.read()
    allowed=[ROOT/'runs/verified-batch-round-7d9c6b20', ROOT/'runs/authorized-round-recovery-fb3a1a23']
    if (not pending or Path(pending['run_directory']) not in allowed
            or pending['confirmation']['target'] not in (3,15) or len(pending['before']['items'])!=16):
        raise ValueError('未找到该授权批次唯一的+3未结算记录；不操作')
    (directory/'original-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf8')
    expected=Path(pending['run_directory'])
    target=pending['confirmation']['target']
    before=[BatchItem(item['token'],Equipment(**item['equipment']),item['selected'],item['locked'])
            for item in pending['before']['items']]
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    driver=BatchEnhancementDriver(nav,guard=guard,track_resources=False)
    # 全程先只读；确认装备属性递进，连续两次结果相同才结清旧确认。
    screen,current,resources=driver.observe(before)
    verify_batch(before,current,target)
    if resources.has_preview:
        raise ValueError('仍有强化预览，旧确认结果不明确，不重发')
    screen,stable,stable_resources=driver.observe(before)
    driver.unchanged(current,stable)
    driver.same_resources(resources,stable_resources)
    if guard.read()!=pending:
        raise ValueError('未结算记录期间变化，不继续')
    journal.emit('authorized_result_recovered',target=target,items=[asdict(item) for item in stable],
                 resources_tracked=False,image=screen.source,
                 reason='用户要求不读取金币及强化材料，以装备结果复核结清')
    guard.settle(pending['operation_id'])
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=WorkflowTask(driver,WorkflowOptions(first_target=3),policy,Limits(max_steps=5),control,journal)
    task.ledger.steps=target//3
    task.untracked_enhancements=target//3
    result=task.run_batch(stable,verified_recovery=(before,target))
    result.update(directory=str(directory),recovered_from=str(expected),resource_tracking=False)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    if not result['outcome_unknown']:
        nav.navigate('inventory')
        result['returned_inventory']=True
    result['last_image']=nav.last_image
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='complete')


if __name__=='__main__':raise SystemExit(main())
