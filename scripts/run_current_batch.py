"""按当前已确认规则执行顶部一批；不打造、不遍历整包、不自动重试资源确认。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_entry import BatchEntryDriver
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.disposal_guard import BatchEnhancementGuard,CraftSessionGuard,DisposalGuard
from e7_assistant.inventory_sort import ensure_ascending
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import WorkflowTask,WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    directory=ROOT/'runs'/('current-batch-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2);journal=Journal(directory)
    serial='127.0.0.1:16384'
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    guard=BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial)
    disposal=DisposalGuard(ROOT/'runs/disposal-pending',serial)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    result={'state':'failed','directory':str(directory),'scope':'one_current_batch','outcome_unknown':False}
    task=None
    try:
        for pending in (guard,disposal,CraftSessionGuard(ROOT/'runs/craft-pending',serial)):
            pending.check_clear()
        nav.navigate('inventory');ensure_ascending(nav)
        nav.navigate('inventory_batch_selection')
        selector=BatchSelectionDriver(nav,policy=policy)
        # 首屏足够即进入强化；不为诊断继续向下扫描整包。
        selection=selector.collect_pages(limit=16,max_pages=3,start_at_top=True)
        (directory/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf8')
        report,items=BatchEntryDriver(selector).enter(selection)
        (directory/'context.json').write_text(json.dumps([asdict(i) for i in items],ensure_ascii=False,indent=2),encoding='utf8')
        driver=BatchEnhancementDriver(nav,guard=guard,track_resources=False,purple_speed_only=True,
                                      ignore_equipment_level=policy.ignore_equipment_level)
        task=WorkflowTask(driver,WorkflowOptions(first_target=3),policy,Limits(max_steps=5),control,journal)
        result.update(task.run_batch(items))
    except Exception as exc:
        result.update(state='failed',error=str(exc),outcome_unknown=bool(task and task.uncertain))
    finally:
        result['outcome_unknown']=result['outcome_unknown'] or bool(guard.read() or disposal.read())
        if not result['outcome_unknown']:
            try:
                nav.navigate('inventory');result['returned_inventory']=True
            except Exception as exc:
                result['cleanup_error']=str(exc)
        result['last_image']=nav.last_image
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='complete' or result['outcome_unknown'])


if __name__=='__main__':raise SystemExit(main())
