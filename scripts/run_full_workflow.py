"""按正式驱动验收一轮；确认未知保留现场，不自动重启。"""
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb-path',default=r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe')
    parser.add_argument('--inventory-only',action='store_true',help='只继续当前背包批次，不重新打造')
    parser.add_argument('--rounds',type=int,default=1,help='连续完整轮数')
    parser.add_argument('--craft-material-budget',type=int,default=10000,help='本次打造材料总预算')
    parser.add_argument('--max-steps',type=int,default=300,help='确认操作次数上限')
    args=parser.parse_args()
    directory=ROOT/'runs'/('full-workflow-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    options=WorkflowOptions(source_index=0,slot='helmet',craft_count=10,first_target=3,
                            initial_disposal='extract',rounds=args.rounds,action_interval=.2)
    limits=Limits(gold=10000000,craft_material=args.craft_material_budget,max_steps=args.max_steps)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    journal.emit('live_test_configuration',options=asdict(options),limits=asdict(limits),
                 enhancement_resources_tracked=False)
    adb=Adb(args.adb_path,'127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    task=LiveWorkflowTask(nav,options,policy,limits,control,journal)
    if args.inventory_only:
        state='failed'
        try:
            task.enhancement_guard.check_clear();task.disposal_guard.check_clear();task.craft_guard.check_clear()
            task.enhance_inventory_batches()
            state='complete'
        except Exception as exc:
            journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
        result={'state':state,'scope':'inventory_only','batches':task.completed_batches,
                'steps':task.ledger.steps,'spent':dict(task.ledger.spent),
                'outcome_unknown':task.uncertain,'last_image':nav.last_image,
                'untracked_enhancements':task.untracked_enhancements}
        result['items']=[asdict(item) for item in getattr(task,'last_batch',[])]
        journal.emit('finished',**result)
    else:
        result=task.run()
    result['directory']=str(directory)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='complete')


if __name__=='__main__':raise SystemExit(main())
