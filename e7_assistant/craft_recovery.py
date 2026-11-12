"""在原生客户端核验已打造至满包的会话，再继续该轮清理和强化。"""
from dataclasses import asdict,replace
import json
from pathlib import Path

from .craft_reservation import CraftReservation
from .forge_loop import LiveForgeLoop
from .tasks import Cancelled


def settle_full_craft(task):
    pending=task.craft_guard.read()
    if pending is None or pending['action']!='craft':
        raise ValueError('没有待核验打造记录')
    task.enhancement_guard.check_clear();task.disposal_guard.check_clear()
    original=Path(pending['run_directory']).resolve()
    if original.parent!=task.navigator.directory.parent.resolve():
        raise ValueError('原打造不属于本工作区')
    events=[json.loads(line) for line in (original/'events.jsonl').read_text(encoding='utf8').splitlines()]
    if pending['before'].get('verification')=='result':
        return settle_result_craft(task,pending,original,events)
    commits=[e for e in events if e['kind']=='craft_commit_intent']
    results=[e for e in events if e['kind']=='craft_result_observed']
    starts=[e for e in events if e['kind']=='craft_session_started']
    if (not commits or not results or len(starts)!=1 or starts[0]['operation_id']!=pending['operation_id']
            or results[-1]['accounting']['confirmed_attempts']!=len(commits)
            or events.index(results[-1])<events.index(commits[-1])
            or events[-1]['kind']!='finished' or events[-1]['state']!='failed'
            or any(e['kind']=='craft_session_settled' for e in events)
            or not any(e['kind']=='workflow_screen' and e['page']=='inventory_full'
                       for e in events[events.index(results[-1])+1:])):
        raise ValueError('原会话不是全部打造结果已观察且随后满包的失败任务')
    before=pending['before']
    if (task.options.track_craft_gold or set(before['cost'])!={'craft_material'}
            or (before['slot'],before['count'],before['source_index'])!=
               (task.options.slot,task.options.craft_count,task.options.source_index)):
        raise ValueError('原打造参数或材料核账模式不符')
    task.ledger.spent.update(events[-1]['spent']);task.ledger.steps=events[-1]['steps']
    reservation=CraftReservation(task.ledger,before['resources'],before['cost'])
    for _ in commits:reservation.mark_commit()
    task.uncertain=True
    state='failed'
    try:
        forge=LiveForgeLoop(task.navigator,replace(task.options,track_craft_consumption=True),
                            task.ledger,task.control,task.journal,guard=task.craft_guard)
        final=forge.settlement_preview()
        stable=forge.preview(task.navigator.read())
        if (asdict(final)|{'image':None})!=(asdict(stable)|{'image':None}) or task.craft_guard.read()!=pending:
            raise ValueError('打造材料双帧或待结算记录变化')
        actual=reservation.settle(stable.resources)
        task.journal.emit('original_craft_settled',operation_id=pending['operation_id'],
                          actual=actual,batches=len(commits),original=str(original),image=stable.image)
        task.craft_guard.settle(pending['operation_id'])
        task.uncertain=False
        task.finish_inventory_round()
        state='complete'
    except Exception as exc:
        state='stopped' if isinstance(exc,Cancelled) else 'failed'
        task.journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result={'state':state,'scope':'craft_full_recovery','rounds':int(state=='complete'),
            'batches':task.completed_batches,'steps':task.ledger.steps,'spent':dict(task.ledger.spent),
            'outcome_unknown':task.uncertain,'last_image':task.navigator.last_image,
            'enhancement_statistics':task.enhancement_statistics.snapshot()}
    task.journal.emit('finished',**result)
    return result


def settle_result_craft(task,pending,original,events):
    """新记录按对应提交后的结果恢复；结果不明时才读取旧截图材料。"""
    from .workflow_screen import inspect_screen
    from .forge_loop import number
    from .crafting import parse_material
    before=pending['before']
    if (before['slot'],before['count'],before['source_index'])!=(
            task.options.slot,task.options.craft_count,task.options.source_index):
        raise ValueError('待恢复打造参数与当前设置不符')
    commits=[e for e in events if e.get('kind')=='craft_commit_intent'
             and e.get('operation_id')==pending['operation_id']]
    if len(commits)!=1:raise ValueError('对应制作提交不唯一，保留记录')
    following=events[events.index(commits[0])+1:]
    if any(e.get('kind')=='craft_commit_intent' for e in following):
        raise ValueError('原提交后存在其他制作，不能混用结果')
    verified=False
    for event in following:
        if event.get('kind')!='craft_result_observed' or event.get('operation_id')!=pending['operation_id']:continue
        image=Path(event['image']).resolve()
        if image.parent!=original:raise ValueError('结果截图不属于原任务')
        if inspect_screen(image).page=='craft_result':verified=True;break
    if not verified:
        current=task.navigator.read()
        verified=current.page=='craft_result'
    if not verified:
        image=Path(before['image']).resolve()
        if image.parent!=original:raise ValueError('制作前截图不属于原任务')
        initial=inspect_screen(image)
        available,cost=parse_material(number(initial,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
        forge=LiveForgeLoop(task.navigator,task.options,task.ledger,task.control,task.journal,guard=task.craft_guard)
        forge.configure()
        current=task.navigator.read()
        observed,_=parse_material(number(current,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
        verified=cost>0 and available-observed==cost*(before['confirmed_batches']+1)
    if not verified:raise ValueError('制作结果与辅助材料仍不明确，未重复制作')
    if task.craft_guard.read()!=pending:raise ValueError('待核验记录发生变化')
    finished=next((event for event in reversed(events) if event.get('kind')=='finished'),None)
    if finished:
        task.ledger.steps=finished.get('steps',task.ledger.steps)
        task.ledger.spent.update(finished.get('spent',{}))
    task.ledger.steps+=1
    task.journal.emit('original_craft_result_verified',operation_id=pending['operation_id'],
                      input_repeated=False,consumption_tracked=False)
    task.craft_guard.settle(pending['operation_id'])
    task.uncertain=False
    return task.run()
