"""只读确认已锁结果，继续同一批整理；不重发锁或旧强化确认。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.disposal_guard import BatchEnhancementGuard,DisposalGuard
from e7_assistant.lock_vision import verify_batch_lock_pixels
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import BatchItem,WorkflowOptions,WorkflowTask,verify_lock_update
from e7_assistant.workflow_navigation import WorkflowNavigator

directory=ROOT/'runs'/('locked-batch-recovery-'+uuid.uuid4().hex[:8])
journal=Journal(directory);control=TaskControl(.2);serial='127.0.0.1:16384'
guard=BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial)
guard.check_clear();DisposalGuard(ROOT/'runs/disposal-pending',serial).check_clear()
original=ROOT/'runs/current-batch-ae36abf6'
old=json.loads((original/'result.json').read_text(encoding='utf8'))
if old['steps']!=5 or old['state']!='failed':raise ValueError('原运行记录不符')
items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in old['items']]
adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
nav=WorkflowNavigator(adb,directory,control,journal)
nav.batch_inventory_context=json.loads((original/'selection.json').read_text(encoding='utf8'))['inventory_context']
driver=BatchEnhancementDriver(nav,guard=guard,track_resources=False,purple_speed_only=True,ignore_equipment_level=True)
screen,current,resources=driver.observe(items)
verify_lock_update(items,current,{'2'})
with Image.open(original/'workflow-0078.png') as before,Image.open(screen.source) as after:
    verify_batch_lock_pixels(before,after,16,2)
_,stable,stable_resources=driver.observe(items)
driver.unchanged(current,stable);driver.same_resources(resources,stable_resources)
journal.emit('recovered_lock_verified',token='2',items=[asdict(i) for i in stable])
policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
task=WorkflowTask(driver,WorkflowOptions(first_target=3),policy,Limits(max_steps=10),control,journal)
task.ledger.steps=5;task.untracked_enhancements=5
result=task.run_batch(stable,verified_recovery=(stable,15))
if not result['outcome_unknown']:
    nav.navigate('inventory');result['returned_inventory']=True
result['last_image']=nav.last_image
(directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'directory':str(directory),'state':result['state'],'outcome_unknown':result['outcome_unknown']},ensure_ascii=False))
