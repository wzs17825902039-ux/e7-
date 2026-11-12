"""核验包含强化加成红装的原生批量入口；不执行强化、出售或萃取。"""
from dataclasses import asdict
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
    directory=ROOT/'runs'/('boosted-red-entry-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2);journal=Journal(directory)
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=LiveWorkflowTask(nav,WorkflowOptions(scan_pages=200),policy,Limits(),control,journal)
    result={'state':'failed','resource_confirmations':0}
    try:
        for guard in (task.enhancement_guard,task.disposal_guard,task.craft_guard):guard.check_clear()
        items=task.collect_batch()
        result.update(state='entry_verified',items=[asdict(i) for i in items])
    except Exception as exc:
        result['message']=str(exc)
    result.update(directory=str(directory),last_image=nav.last_image)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='entry_verified')


if __name__=='__main__':raise SystemExit(main())
