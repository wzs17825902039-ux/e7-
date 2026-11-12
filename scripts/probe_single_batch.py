"""单件实机批量入口取样；仅选装与进入，不强化、不出售、不切换锁。"""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_entry import verify_entry
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.batch_vision import inspect_batch
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    directory=ROOT/'runs'/('single-batch-probe-'+uuid.uuid4().hex[:8])
    journal=Journal(directory)
    control=TaskControl(.8)
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',
            '127.0.0.1:16384',control)
    navigator=WorkflowNavigator(adb,directory,control,journal)
    navigator.navigate('inventory_batch_selection')
    selector=BatchSelectionDriver(navigator)
    selector.rewind_to_top(selector._begin(1),50)
    selection=selector.collect_visible(limit=1)
    (directory/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
    # 这是用户授权的一件装备测试，不将它标成已扫描末尾；生产尾批条件不变。
    if selection['selected_count']!=1 or len(selection['registered'])!=1:
        raise ValueError('单件测试选装数量不符')
    fresh=selector.observe()
    selector._verify_unchanged({k:v for k,v in selection.items()
                               if k not in ('source','selection_status','registered')},
                              {k:v for k,v in fresh.items() if k!='source'})
    button=selector.screen.find('批量强化(1)',(1000,630,1250,710))
    journal.emit('single_probe_entry_intent',scope='single_item_test',image=selector.screen.source)
    adb.tap(*(round(v) for v in button['center']))
    for _ in range(8):
        control.wait(.4)
        screen=navigator.read()
        if screen.page=='batch_enhancement':
            break
        if screen.page not in {'unknown','inventory_batch_selection'}:
            raise ValueError('单件测试入口出现意外页面')
    else:
        raise TimeoutError('单件测试入口未确认，未重试')
    report=inspect_batch(screen.source,{0:selection['registered'][0]['equipment']['slot']})
    from dataclasses import asdict
    (directory/'batch.json').write_text(json.dumps({k:v for k,v in report.items() if k!='items'},
                                                 ensure_ascii=False,indent=2),encoding='utf-8')
    items=verify_entry(selection,report)
    (directory/'context.json').write_text(json.dumps([asdict(i) for i in items],ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'directory':str(directory),'source':screen.source,'items':[asdict(i) for i in items]},ensure_ascii=False))


if __name__=='__main__':
    main()
