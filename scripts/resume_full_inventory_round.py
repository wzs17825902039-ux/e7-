"""只恢复已确认打造到满、尚未快速选择的现场；复用正式清理和强化链路。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.initial_cleanup import inspect_inventory
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    retry_preview='--after-extract-preview' in sys.argv
    original=ROOT/'runs'/('full-inventory-resume-3f3424b9' if retry_preview else 'craft-recovery-workflow-077af0de')
    old=json.loads((original/'result.json').read_text(encoding='utf8'))
    events=[json.loads(line) for line in (original/'events.jsonl').read_text(encoding='utf8').splitlines()]
    full_verified=(any(e['kind']=='resume_verified_inventory_full' for e in events) if retry_preview else
                   any(e['kind']=='workflow_forge_finished' and e['result']['state']=='inventory_full' for e in events))
    if (old['state']!='failed' or old['outcome_unknown'] or not full_verified
            or any(e['kind']=='cleanup_commit_intent' for e in events)):
        raise ValueError('原记录不是指定的清理前安全恢复点')
    directory=ROOT/'runs'/('full-inventory-resume-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    options=WorkflowOptions(source_index=0,slot='helmet',craft_count=10,first_target=3,
                            initial_disposal='extract',rounds=1,scan_pages=150,action_interval=.2)
    limits=Limits(gold=10000000,craft_material=10000,max_steps=300)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    task=LiveWorkflowTask(nav,options,policy,limits,control,journal)
    task.ledger.spent.update(old['spent']);task.ledger.steps=old['steps']
    task.craft_guard.check_clear();task.enhancement_guard.check_clear();task.disposal_guard.check_clear()
    current=inspect_inventory(nav.navigate('inventory') if retry_preview else nav.read(),track_gold=False)
    cleanup_already_done=retry_preview and current.count==1053 and current.selected is None
    if (current.count!=1203 and not cleanup_already_done) or current.selected not in (None,0):
        raise ValueError('不是原背包满且未勾选的整理现场')
    journal.emit('resume_verified_inventory_full',original=str(original),inventory=asdict(current),
                 options=asdict(options),limits=asdict(limits))
    state='failed'
    try:
        if cleanup_already_done:
            stable=inspect_inventory(nav.read(),track_gold=False)
            if (stable.count,stable.gold)!=(current.count,current.gold):
                raise ValueError('现场清理后数量未稳定')
            journal.emit('external_cleanup_observed',before_count=1203,after_count=1053,
                         removed=150,automatic_confirmation_verified=False)
            task.enhance_inventory_batches()
        else:
            task.finish_inventory_round()
        journal.emit('round_finished',round=1,recovered_from=str(original))
        state='complete'
    except Exception as exc:
        journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result={'state':state,'scope':'recovered_inventory_round','rounds':int(state=='complete'),
            'batches':task.completed_batches,'steps':task.ledger.steps,'spent':task.ledger.spent,
            'outcome_unknown':task.uncertain,'untracked_enhancements':task.untracked_enhancements,
            'last_image':nav.last_image,'directory':str(directory)}
    journal.emit('finished',**result)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
