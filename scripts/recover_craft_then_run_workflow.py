"""核验指定的一次打造结果并结清，沿用账本继续正式整轮，不重发原确认。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.craft_reservation import CraftReservation
from e7_assistant.forge_loop import LiveForgeLoop,number
from e7_assistant.live import parse_amount
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    directory=ROOT/'runs'/('craft-recovery-workflow-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    original=ROOT/'runs/craft-recovery-workflow-7502f113'
    events=[json.loads(line) for line in (original/'events.jsonl').read_text(encoding='utf8').splitlines()]
    config=next(e for e in events if e['kind']=='live_test_configuration')
    intents=[e for e in events if e['kind']=='craft_commit_intent' and e['button']=='制作']
    if len(intents)!=1:
        raise ValueError('原始确认次数不是一次，不执行指定恢复')
    options=WorkflowOptions(**(config['options']|{'track_craft_gold':False}));limits=Limits(**config['limits'])
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    task=LiveWorkflowTask(nav,options,policy,limits,control,journal)
    finished=events[-1]
    if finished['kind']!='finished' or finished['state']!='failed':
        raise ValueError('原任务未确认已停止')
    task.ledger.spent.update(finished['spent']);task.ledger.steps=finished['steps']
    pending=task.craft_guard.read()
    if not pending or Path(pending['run_directory'])!=original:
        raise ValueError('指定未结算打造记录不存在，禁止继续')
    task.enhancement_guard.check_clear();task.disposal_guard.check_clear()
    (directory/'original-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf8')
    reservation=CraftReservation(task.ledger,
        {'craft_material':pending['before']['resources']['craft_material']},
        {'craft_material':pending['before']['cost']['craft_material']})
    reservation.mark_commit()
    screen=nav.read()
    if screen.page!='craft_confirmation':
        raise ValueError('现场不是尚未确认的重新制作弹窗，不操作')
    forge=LiveForgeLoop(nav,options,task.ledger,control,journal,guard=task.craft_guard)
    from e7_assistant.forge_loop import ForgePreview
    before=pending['before']
    preview=ForgePreview(reservation.before,reservation.cost,before['slot'],before['count'],before['source_index'],before['image'])
    forge.verify_confirmation(screen,preview)
    word=screen.find('取消',(350,490,590,575))
    journal.emit('cancel_unconfirmed_repeat',image=screen.source)
    nav.adb.tap(*(round(v) for v in word['center']))
    forge.wait_for({'craft_result'})
    for _ in range(2):
        screen=nav.read()
        if screen.page!='craft_result':
            raise ValueError('现场不是原打造结果页，不恢复')
        journal.emit('original_craft_result_verified',image=screen.source,accounting=reservation.evidence())
    final=forge.preview(nav.navigate('forge'))
    stable=forge.preview(nav.read())
    if asdict(final)|{'image':None} != asdict(stable)|{'image':None}:
        raise ValueError('制作页两次读数不一致，不清除记录')
    if task.craft_guard.read()!=pending:
        raise ValueError('原未结算记录发生变化')
    actual=reservation.settle(stable.resources)
    journal.emit('original_craft_settled',actual=actual,batches=reservation.committed,
                 accounting=reservation.evidence(),image=stable.image)
    task.craft_guard.settle(pending['operation_id'])
    journal.emit('live_test_configuration',options=asdict(options),limits=asdict(limits),
                 carried_spent=dict(task.ledger.spent),carried_steps=task.ledger.steps)
    result=task.run();result['directory']=str(directory)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
