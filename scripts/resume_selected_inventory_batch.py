"""只读核对保存的选装记录与当前批量页，再继续背包；不恢复未知确认。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_entry import verify_entry,BatchEntryDriver
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_vision import inspect_batch,inspect_selection_flags,verify_stable_batch_pixels
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import BatchItem,WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb-path',default=r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe')
    parser.add_argument('selection',type=Path)
    parser.add_argument('--observed-result',type=Path,help='同一批已完整识别、仅取消选择后拒识的结果记录')
    parser.add_argument('--resume-unsubmitted-sale',action='store_true',help='仅恢复出售前失败且没有提交记录的整理现场')
    parser.add_argument('--settle-lock',action='store_true',help='只读核验最后一次上锁结果，不重复点击锁按钮')
    parser.add_argument('--from-current-decisions',action='store_true',help='结果文件的items过期时，用同一入口后的完整决策记录恢复')
    args=parser.parse_args()
    selection=json.loads(args.selection.read_text(encoding='utf8'))
    # JSON把运行时上下文元组转成数组；恢复其原类型，内容仍逐项核验。
    for snapshot in (selection,selection.get('visual_snapshot',{})):
        if isinstance(snapshot.get('inventory_context'),list):
            snapshot['inventory_context']=tuple(snapshot['inventory_context'])
    directory=ROOT/'runs'/('selected-inventory-resume-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    adb=Adb(args.adb_path,'127.0.0.1:16384',control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task=LiveWorkflowTask(nav,WorkflowOptions(first_target=3,action_interval=.2),
                          policy,Limits(max_steps=300),control,journal)
    for guard in (task.enhancement_guard,task.disposal_guard,task.craft_guard):guard.check_clear()
    screen=nav.read()
    if args.resume_unsubmitted_sale and args.observed_result and screen.page=='sale_confirmation':
        from e7_assistant.batch_sale_vision import inspect_sale_confirmation,sale_confirmation_unchanged
        from e7_assistant.workflow_screen import inspect_screen
        prior=json.loads(args.observed_result.read_text(encoding='utf8'))
        history=[json.loads(x) for x in args.observed_result.with_name('events.jsonl').read_text(encoding='utf8').splitlines()]
        dialogs=[e for e in history if e['kind']=='workflow_screen' and e['page']=='sale_confirmation']
        if (prior['state']!='failed' or not dialogs
                or not any(e['kind']=='disposal_intent' for e in history)
                or any(e['kind']=='batch_sale_commit_intent' for e in history)):
            raise ValueError('不是尚未提交的出售弹窗，不发送输入')
        if not sale_confirmation_unchanged(inspect_sale_confirmation(inspect_screen(dialogs[-1]['image'])),
                                           inspect_sale_confirmation(screen)):
            raise ValueError('当前出售弹窗与保存记录不符，不发送输入')
        cancel=screen.find('取消',(400,490,650,570),.95)
        journal.emit('unsubmitted_sale_cancel_intent',image=screen.source,confirmation_repeated=False)
        adb.tap(*(round(v) for v in cancel['center']))
        control.wait(.4)
        screen=nav.read()
        if screen.page!='batch_organize':
            raise ValueError('取消出售后未确认整理页，停止恢复')
    if args.observed_result and screen.page=='batch_organize':
        screen=nav.transition('cancel_batch_organize')
    if screen.page not in ('batch_enhancement','inventory_batch_selection'):
        raise ValueError('不是原生批量页或已选装现场，不发送输入')
    if args.observed_result and screen.page!='batch_enhancement':
        raise ValueError('已强化结果只能从同一原生批量页恢复')
    slots={i:r['equipment']['slot'] for i,r in enumerate(selection['registered'])}
    if args.observed_result:
        previous=json.loads(args.observed_result.read_text(encoding='utf8'))
        if previous['state']!='failed' or previous['outcome_unknown'] and not (args.resume_unsubmitted_sale or args.settle_lock):
            raise ValueError('不是确认已结算的失败观察，不恢复')
        events=[json.loads(x) for x in args.observed_result.with_name('events.jsonl').read_text(encoding='utf8').splitlines()]
        if args.resume_unsubmitted_sale and (not any(e['kind']=='disposal_intent' for e in events)
                or any(e['kind']=='batch_sale_commit_intent' for e in events)):
            raise ValueError('不是尚未提交出售的整理失败点')
        if args.from_current_decisions:
            entries=[e for e in events if e['kind']=='batch_entry_verified']
            if not entries or previous['outcome_unknown']:
                raise ValueError('缺少已核对入口或存在未知操作，不从决策恢复')
            entry=entries[-1]
            decisions=[e for e in events[events.index(entry)+1:] if e['kind']=='equipment_decision'][-len(selection['registered']):]
            if (len(decisions)!=len(entry['equipment']) or
                    [e['equipment']['equipment_id'] for e in decisions]!=
                    [i['equipment']['equipment_id'] for i in entry['equipment']]):
                raise ValueError('决策记录不属于同一已核对入口')
            previous['items']=[{'token':e['token'],'equipment':e['equipment'],'locked':e['locked']} for e in decisions]
        if not previous.get('items'):
            decisions=[e for e in events if e['kind']=='equipment_decision'][-len(selection['registered']):]
            if len(decisions)!=len(selection['registered']) or len({e['token'] for e in decisions})!=len(decisions):
                raise ValueError('缺少完整批次判断记录，不能恢复')
            previous['items']=[{'token':e['token'],'equipment':e['equipment'],'locked':e['locked']} for e in decisions]
        reference=[e['image'] for e in events if e['kind']=='workflow_screen' and e['page']=='batch_enhancement'][-1]
        flags=inspect_selection_flags(screen.source,len(previous['items']))
        items=[BatchItem(i['token'],Equipment(**i['equipment']),flag,i['locked'])
               for i,flag in zip(previous['items'],flags)]
        if args.settle_lock:
            from dataclasses import replace
            from PIL import Image
            from e7_assistant.lock_vision import verify_batch_lock_pixels
            intents=[e for e in events if e['kind']=='batch_lock_intent']
            if not previous['outcome_unknown'] or not intents:
                raise ValueError('没有待核验的锁动作')
            intent=intents[-1]
            target=next(i for i,item in enumerate(items) if item.token==intent['token'])
            with Image.open(intent['image']) as before,Image.open(screen.source) as after:
                verify_batch_lock_pixels(before,after,len(items),target,attributes_only=True)
            items=[replace(item,locked=True) if i==target else item for i,item in enumerate(items)]
            journal.emit('lock_recovery_verified',token=intent['token'],image=screen.source,input_repeated=False)
        verify_stable_batch_pixels(reference,screen.source,items)
        # 部分属性结果不包含原速度行；先用当前批量页重建并核对，不能猜行号。
        if any(i.equipment.observation_scope=='purple_speed' for i in items):
            report=inspect_batch(screen.source,slots,ignore_levels=policy.ignore_equipment_level,
                                 require_score=False,ignore_purple_main=True,purple_speed_only=True,known_items=items)
            rows=report.get('speed_rows',{})
            if any(i not in rows for i,item in enumerate(items) if item.equipment.observation_scope=='purple_speed'):
                raise ValueError('恢复时无法重建完整速度行')
            task.driver.speed_rows=rows
        task.driver.remember_observation(screen,items)
        _,observed,resources=task.driver.observe_unchanged(items)
        task.driver.unchanged(items,observed)
        if resources.has_preview:
            journal.emit('existing_preview_observed',target=resources.target,image=screen.source)
            # 规则重新计算后，驱动仅接受同一目标和同一勾选集合的预览。
            # 需要调整勾选或目标不一致时仍拒绝，不直接提交。
        items=observed
        task.ledger.steps=previous['steps']
        task.untracked_enhancements=previous['untracked_enhancements']
        task.completed_batches=previous.get('batches',0)
    else:
        selection_only=all(e.get('selection_only') for e in selection['registered'])
        from types import SimpleNamespace
        entry=BatchEntryDriver(SimpleNamespace(navigator=nav,policy=policy,
                              ignore_equipment_level=policy.ignore_equipment_level))
        if screen.page=='inventory_batch_selection':
            from e7_assistant.batch_selection import BatchSelectionDriver
            # enter先逐卡核对保存快照、原生计数和当前勾选，确认一致才进入。
            entry=BatchEntryDriver(BatchSelectionDriver(nav,policy=policy,protection=task.protection))
            report,items=entry.enter(selection)
        else:
            report,items=entry.read_entry(selection,screen)
        nav.batch_speed_rows=report.get('speed_rows',{})
    nav.batch_inventory_context=selection['inventory_context']
    nav.batch_ignore_equipment_level=policy.ignore_equipment_level
    if not args.observed_result:
        task.driver=BatchEnhancementDriver(nav,guard=task.enhancement_guard,
                                          track_resources=False,purple_speed_only=True)
    journal.emit('selected_entry_recovered',selection=str(args.selection.resolve()),image=screen.source)
    result=task.run_batch(items,verified_recovery=(items,0) if args.observed_result else None)
    if result['state']=='complete':
        task.completed_batches+=1
        try:
            task.enhance_inventory_batches()
        except Exception as exc:
            result['state']='failed'
            journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result.update(scope='inventory_only',batches=task.completed_batches,steps=task.ledger.steps,
                  untracked_enhancements=task.untracked_enhancements,outcome_unknown=task.uncertain,
                  last_image=nav.last_image,items=[asdict(i) for i in task.last_batch])
    journal.emit('finished',**result)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),'state':result['state'],'batches':task.completed_batches},ensure_ascii=False))


if __name__=='__main__':main()
