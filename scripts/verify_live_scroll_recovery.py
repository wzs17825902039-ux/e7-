"""指定现场的滚动恢复验证：仅截图及最多两次视口微调，不确认资源。"""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_scan import InventoryTraversal
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    before,_=json.loads((ROOT/'runs/scroll-b6a-offline.json').read_text(encoding='utf8'))
    before['inventory_context']=tuple(before['inventory_context'])
    directory=ROOT/'runs'/('scroll-recovery-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2);journal=Journal(directory)
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    selector=BatchSelectionDriver(nav,policy=policy)
    traversal=InventoryTraversal();traversal.start(before)
    try:
        after,offset=selector.observe_scrolled_with_adjustment(before,traversal)
        result={'state':'complete','offset':offset,'evidence':traversal.evidence(),'image':after['source']}
    except Exception as exc:
        result={'state':'failed','message':str(exc),'evidence':traversal.evidence(),'image':nav.last_image}
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),**result},ensure_ascii=False))
    return int(result['state']!='complete')


if __name__=='__main__':raise SystemExit(main())
