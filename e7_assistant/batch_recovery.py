"""仅恢复有完整记录且从未提交出售的原批次；不恢复未知消耗确认。"""
from dataclasses import asdict
import json
from pathlib import Path

from .batch_vision import inspect_selection_flags,verify_stable_batch_pixels,inspect_batch
from .rules import Equipment
from .workflow import BatchItem,verify_batch


def settle_submitted_enhancement(task):
    """仅结算旧强化回执并交回可靠批次；接续由主流程负责。"""
    from .batch_enhancement import BatchEnhancementDriver
    record=task.enhancement_guard.read()
    if record is None or record['action']!='batch_enhance':
        raise ValueError('没有待核验的已提交强化记录')
    task.disposal_guard.check_clear();task.craft_guard.check_clear()
    directory=Path(record['run_directory']).resolve()
    if directory.parent!=task.navigator.directory.parent.resolve():
        raise ValueError('强化记录不属于本工作区')
    confirmation=record['confirmation']
    target=confirmation['target']
    if type(target) is not int or target not in (3,6,9,12,15):
        raise ValueError('旧强化目标节点无效')
    image=Path(confirmation['image']).resolve()
    if image.parent!=directory:
        raise ValueError('旧确认截图不属于原任务')
    events=[json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf8').splitlines()]
    commits=[index for index,event in enumerate(events) if event['kind']=='batch_enhance_commit_intent'
             and event.get('target')==target and Path(event.get('image','')).resolve()==image
             and event.get('operation_id',record['operation_id'])==record['operation_id']]
    if len(commits)!=1 or any(event['kind'] in {'settled','batch_enhance_commit_intent','batch_sale_commit_intent'}
                             for event in events[commits[0]+1:]):
        raise ValueError('原强化提交或结算日志不唯一，不清除记录')
    before=[BatchItem(item['token'],Equipment(**item['equipment']),item['selected'],item['locked'])
            for item in record['before']['items']]
    if not before or len(before)>16 or not any(item.selected for item in before):
        raise ValueError('旧强化选中集合不完整')
    ignored=all(item.equipment.level is None for item in before)
    if not ignored and any(item.equipment.level is None for item in before):
        raise ValueError('旧强化等级识别范围不一致')
    task.last_batch=before
    (task.navigator.directory/'original-enhancement-pending.json').write_text(
        json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    task.uncertain=True
    state='failed'
    recovered=False
    nav=task.navigator
    try:
        task.control.checkpoint()
        screen=nav.read()
        if screen.page!='batch_enhancement':
            raise ValueError('现场不是原批量强化结果页；只读核验停止，不导航或重发确认')
        nav.batch_inventory_context=record['before'].get('inventory_context')
        task.driver=BatchEnhancementDriver(nav,guard=task.enhancement_guard,track_resources=False,
                                          purple_speed_only=True,ignore_equipment_level=ignored)
        if any(item.equipment.observation_scope=='purple_speed' for item in before):
            report=inspect_batch(screen.source,{index:item.equipment.slot for index,item in enumerate(before)},
                ignore_levels=ignored,require_score=False,ignore_purple_main=True,purple_speed_only=True,known_items=before)
            if report['issues']:
                raise ValueError('旧批次速度行尚未可靠识别')
            task.driver.speed_rows=report.get('speed_rows',{})
        task.journal.emit('submitted_enhancement_receipt_recovery',operation_id=record['operation_id'],
                          original_directory=str(directory),target=target,confirmation_repeated=False)
        screen,current,resources=task.driver.observe(before,screen=screen)
        verify_batch(before,current,target)
        if resources.has_preview:
            raise ValueError('结果仍显示强化预览，不结算或重复确认')
        screen,stable,stable_resources=task.driver.observe_unchanged(current)
        task.driver.unchanged(current,stable)
        task.driver.same_resources(resources,stable_resources)
        if stable_resources.has_preview or task.enhancement_guard.read()!=record:
            raise ValueError('结果或待结算记录在核验期间变化，不清除记录')
        task.journal.emit('enhancement_receipt_recovered',operation_id=record['operation_id'],
                          target=target,items=[asdict(item) for item in stable],image=screen.source,
                          counts_in_current_statistics=False)
        task.enhancement_guard.settle(record['operation_id'])
        recovered=True
        task.uncertain=False
        # 本次只结算历史消耗，不把它伪记为本次新强化，也不重复累计速度统计。
        from .workflow import record_speed_roll
        task.last_batch=record_speed_roll(before,stable,target)
        state='complete'
    except Exception as exc:
        from .tasks import Cancelled
        state='stopped' if isinstance(exc,Cancelled) else 'failed'
        task.journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result={'state':state,'scope':'submitted_enhancement_recovery','rounds':0,
            'batches':task.completed_batches,'steps':task.ledger.steps,'outcome_unknown':task.uncertain,
            'recovered_enhancements':int(recovered),'untracked_enhancements':task.untracked_enhancements,
            'last_image':nav.last_image,'enhancement_statistics':task.enhancement_statistics.snapshot(),
            'items':[asdict(item) for item in task.last_batch]}
    task.journal.emit('receipt_recovery_finished',**result)
    return result


def historical_survivor_frames(runs,operation_id):
    """重读同一出售回执恢复任务的双帧；后续只允许导航和只读截图。"""
    from .workflow_screen import inspect_screen
    candidates=[]
    allowed={'workflow_screen','navigation_intent','batch_sale_survivors_verified','failed','finished',
             'workflow_auto_recovery','submitted_sale_receipt_recovery','navigation_replanned','navigation_retry',
             'receipt_recovery_finished'}
    paths=list(Path(runs).glob('recovery-*/events.jsonl'))+list(Path(runs).glob('desktop-*/events.jsonl'))
    for path in paths:
        try:raw=path.read_text(encoding='utf8')
        except FileNotFoundError:continue  # 与本次回执无关的旧目录可能已被清理。
        try:
            events=[json.loads(line) for line in raw.splitlines() if line.strip()]
            if any(not isinstance(event,dict) or not isinstance(event.get('kind'),str) for event in events):
                raise ValueError('任务日志结构不完整')
        except ValueError as exc:
            if operation_id in raw:
                raise ValueError('同一出售的历史日志损坏，保留回执') from exc
            continue  # 不让无关旧任务的截断日志阻塞当前完整凭据。
        verified=[i for i,e in enumerate(events) if e['kind']=='batch_sale_survivors_verified'
                  and e.get('operation_id')==operation_id]
        if verified:
            index=verified[-1]
            if any(e['kind'] not in allowed for e in events[index+1:]):
                raise ValueError('保留凭据之后存在其他操作，不能用历史截图结算')
            frames=events[index].get('images',[])
            if len(frames)!=2 or len(set(frames))!=2:
                raise ValueError('历史保留凭据缺少独立双帧')
            if any(Path(frame).resolve().parent!=path.parent.resolve() for frame in frames):
                raise ValueError('历史保留凭据图片不属于原任务目录')
            candidates.append((events[index]['time'],frames))
            continue
        starts=[i for i,e in enumerate(events) if e['kind']=='submitted_sale_receipt_recovery'
                and e['operation_id']==operation_id]
        if not starts:
            continue
        history=events[starts[-1]+1:]
        if any(e['kind'] not in allowed or e['kind']=='navigation_intent'
               and e['action'] not in {'back_batch','inventory','inventory_from_batch'} for e in history):
            raise ValueError('保留凭据之后存在其他操作，不能用历史截图结算')
        navigation=next((i for i,e in enumerate(history) if e['kind']=='navigation_intent'),None)
        if navigation is None:
            continue
        frames=[e['image'] for e in history[:navigation] if e['kind']=='workflow_screen'
                and e['page']=='batch_enhancement'][-2:]
        if len(frames)!=2 or len(set(frames))!=2:
            continue
        if any(Path(frame).resolve().parent!=path.parent.resolve() for frame in frames):
            raise ValueError('历史保留凭据图片不属于原恢复目录')
        candidates.append((history[navigation]['time'],frames))
    if not candidates:
        raise ValueError('离开批量页后缺少同一出售的双帧保留凭据，不清除记录')
    return [inspect_screen(frame) for frame in max(candidates,key=lambda item:item[0])[1]]


def settle_submitted_sale(task):
    """只核验持久化已提交出售的回执；绝不调用出售确认入口。"""
    from .batch_sale import BatchSaleDriver
    from .batch_sale_vision import SaleConfirmation
    record=task.disposal_guard.read()
    if record is None or record['action']!='sell':
        raise ValueError('没有待核验的已提交出售记录')
    task.enhancement_guard.check_clear();task.craft_guard.check_clear()
    directory=Path(record['run_directory']).resolve()
    if directory.parent!=task.navigator.directory.parent.resolve():
        raise ValueError('出售记录不属于本工作区')
    events=[json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf8').splitlines()]
    commits=[i for i,e in enumerate(events) if e['kind']=='batch_sale_commit_intent'
             and e['operation_id']==record['operation_id']]
    if len(commits)!=1 or any(e['kind']=='batch_sale_settled' for e in events[commits[0]:]):
        raise ValueError('提交或结算日志不完整，不清除待核验记录')
    reference=[e['image'] for e in events[:commits[0]]
               if e['kind']=='workflow_screen' and e['page']=='batch_enhancement'][-1]
    before=record['before']
    items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked'])
           for i in before['items']]
    rejected=set(before['rejected']);protected={i.token for i in items}-rejected
    sale=BatchSaleDriver(task.driver,guard=task.disposal_guard)
    task.uncertain=True
    state='failed'
    try:
        screen=task.navigator.read()
        if screen.page in {'home','home_menu'}:
            # 重启或手动返回主页后只导航回背包；原数量、容量及保留凭据仍须完整核验。
            screen=task.navigator.navigate('inventory')
        if screen.page not in {'batch_enhancement','batch_organize','inventory','forge',
                               'inventory_batch_selection','inventory_batch_selection_empty'}:
            raise ValueError('已提交出售结果页面仍不明确，只能等待，不重复确认')
        historical=None
        if protected and screen.page not in {'batch_enhancement','batch_organize'}:
            historical=historical_survivor_frames(directory.parent,record['operation_id'])
        task.journal.emit('submitted_sale_receipt_recovery',operation_id=record['operation_id'],
                          image=screen.source,confirmation_repeated=False)
        sale.settle_result(items,rejected,protected,before['resources'],reference,
            SaleConfirmation(**record['confirmation']),before['inventory_count'],before['capacity'],
            record['operation_id'],screen.page,historical_survivors=historical)
        task.uncertain=False
        task.last_batch=[i for i in items if i.token in protected]
        state='complete'
    except Exception as exc:
        from .tasks import Cancelled
        state='stopped' if isinstance(exc,Cancelled) else 'failed'
        task.journal.emit('failed',message=str(exc),outcome_unknown=task.uncertain)
    result={'state':state,'scope':'submitted_sale_settlement','rounds':0,
        'batches':task.completed_batches,'steps':task.ledger.steps,'outcome_unknown':task.uncertain,
        'last_image':task.navigator.last_image,'enhancement_statistics':task.enhancement_statistics.snapshot()}
    task.journal.emit('receipt_recovery_finished',**result)
    return result


def recover_unsubmitted_batch(task,result_path):
    """核对旧未提交批次，返回可接续装备；不在恢复模块执行消费或扫描。"""
    path=Path(result_path).resolve()
    if path.parent.parent!=task.navigator.directory.parent.resolve() or path.name!='result.json':
        raise ValueError('恢复记录必须位于本工作区runs任务目录')
    prior=json.loads(path.read_text(encoding='utf8'))
    events=[json.loads(line) for line in path.with_name('events.jsonl').read_text(encoding='utf8').splitlines()]
    entries=[i for i,e in enumerate(events) if e['kind']=='batch_entry_verified']
    if prior.get('state')!='failed' or not entries:
        raise ValueError('缺少失败任务及已核验的原批次入口')
    history=events[entries[-1]:]
    if (not any(e['kind']=='disposal_intent' for e in history)
            or any(e['kind'] in {'batch_sale_commit_intent','batch_sale_settled'} for e in history)):
        raise ValueError('该批次不是从未提交的出售，不自动恢复')
    entry=history[0]
    decisions=[e for e in history if e['kind']=='equipment_decision'][-len(entry['equipment']):]
    if ([e['equipment']['equipment_id'] for e in decisions]!=
            [e['equipment']['equipment_id'] for e in entry['equipment']]):
        raise ValueError('恢复决策与原批次身份或顺序不符')
    selections=sorted(path.parent.glob('selection-*.json'))
    if not selections:
        raise ValueError('缺少本批背包登记')
    selection=json.loads(selections[-1].read_text(encoding='utf8'))
    if len(selection['registered'])!=len(decisions):
        raise ValueError('原批次登记数量不符')
    for guard in (task.enhancement_guard,task.disposal_guard,task.craft_guard):
        guard.check_clear()
    nav=task.navigator
    screen=nav.read()
    # 仅取消尚未提交的提示，不点击确认，也不使用“不再显示”。
    if screen.page=='sale_confirmation':
        from .batch_sale_vision import inspect_sale_confirmation
        preview=inspect_sale_confirmation(screen)
        disposal=[e for e in history if e['kind']=='disposal_intent'][-1]
        if preview.count!=len(disposal['rejected']):
            raise ValueError('现场出售件数与原淘汰名单不符')
        screen=nav.transition('cancel_batch_sale')
    if screen.page=='sale_level_warning':
        screen=nav.transition('cancel_sale_level_warning')
    if screen.page=='batch_organize':
        screen=nav.transition('cancel_batch_organize')
    if screen.page!='batch_enhancement':
        raise ValueError('恢复现场不是原批量强化页')
    flags=inspect_selection_flags(screen.source,len(decisions))
    items=[BatchItem(e['token'],Equipment(**e['equipment']),flag,e['locked'])
           for e,flag in zip(decisions,flags)]
    reference=[e['image'] for e in history if e['kind']=='workflow_screen'
               and e['page']=='batch_enhancement'][-1]
    verify_stable_batch_pixels(reference,screen.source,items)
    if any(i.equipment.observation_scope=='purple_speed' for i in items):
        report=inspect_batch(screen.source,{i:item.equipment.slot for i,item in enumerate(items)},
            ignore_levels=task.policy.ignore_equipment_level,require_score=False,
            ignore_purple_main=True,purple_speed_only=True,known_items=items)
        rows=report.get('speed_rows',{})
        if any(i not in rows for i,item in enumerate(items) if item.equipment.observation_scope=='purple_speed'):
            raise ValueError('恢复时速度行不完整')
        task.driver.speed_rows=rows
    nav.batch_inventory_context=tuple(selection['inventory_context'])
    nav.batch_ignore_equipment_level=task.policy.ignore_equipment_level
    task.driver.remember_observation(screen,items)
    _,observed,resources=task.driver.observe_unchanged(items)
    task.driver.unchanged(items,observed)
    if resources.has_preview:
        raise ValueError('恢复现场存在未结算强化预览')
    task.journal.emit('unsubmitted_batch_recovered',prior_result=str(path),image=screen.source)
    task.last_batch=observed
    return observed
