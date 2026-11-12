"""单件实机批量强化测试：prepare只登记；commit核对已保存预览后只确认一次。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver,BatchPreview
from e7_assistant.batch_resources import BatchResources
from e7_assistant.disposal_guard import BatchEnhancementGuard
from e7_assistant.rules import Equipment
from e7_assistant.tasks import Journal,TaskControl,Ledger,Limits
from e7_assistant.workflow import BatchItem
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=('prepare','commit'))
    parser.add_argument('input',type=Path)
    parser.add_argument('--target',type=int,choices=(3,6),default=3)
    args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8'))
    directory=ROOT/'runs'/('stage-probe-'+uuid.uuid4().hex[:8])
    journal=Journal(directory)
    control=TaskControl(.8)
    serial='127.0.0.1:16384'
    navigator=WorkflowNavigator(Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',
                                   serial,control),directory,control,journal)
    guard=BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial)
    guard.check_clear()
    driver=BatchEnhancementDriver(navigator,guard=guard)
    def items(records):
        return [BatchItem(r['token'],Equipment(**r['equipment']),r['selected'],r['locked']) for r in records]
    ledger=Ledger(Limits(gold=20000,powder=100,lesser_stone=1,max_steps=1))
    if args.phase=='prepare':
        current=items(data)
        if len(current)!=1 or current[0].equipment.enhancement!=0:
            raise ValueError('本测试只允许一件已核对的+0装备')
        preview=driver.prepare_enhancement(current,args.target)
        ledger.check(preview.cost,preview.resources)
        (directory/'preview.json').write_text(json.dumps(asdict(preview),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'preview':str(directory/'preview.json'),'cost':preview.cost,'image':preview.image},ensure_ascii=False))
    else:
        preview=BatchPreview(**{**data,'items':items(data['items']),
                               'before':BatchResources(**data['before']),
                               'prepared':BatchResources(**data['prepared'])})
        if len(preview.items)!=1 or preview.target not in (3,6):
            raise ValueError('本测试仅允许单件首节点')
        ledger.check(preview.cost,preview.resources)
        driver.commit_enhancement(preview)
        observed=driver.finish_enhancement(preview)
        ledger.settle(preview.resources,observed['resources'],preview.cost)
        journal.emit('settled',spent=ledger.spent,steps=ledger.steps)
        driver.settle_enhancement(preview)
        result={**observed,'items':[asdict(i) for i in observed['items']],'spent':ledger.spent}
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'directory':str(directory),**result},ensure_ascii=False))


if __name__=='__main__':
    main()
