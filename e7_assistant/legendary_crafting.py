"""中央传说锻造器的选择预览；预览绝不点击最终制作。"""
from dataclasses import replace

from .custom_targets import SET_GROUPS, SET_LABELS
from .forge_loop import LiveForgeLoop,ForgePreview,number,verify_selection
from .crafting import parse_material
from .live import parse_amount


class LegendaryForgeLoop(LiveForgeLoop):
    """传说制作不使用普通次数开关；费用以传说弹窗为准。"""

    def configure(self):
        return super().configure(select_count=False)

    def preview(self,screen):
        verify_selection(screen,self.options,fields=('source','slot'))
        resources={}
        if self.options.track_craft_consumption or self.options.track_craft_gold:
            try:
                available,_=parse_material(number(screen,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
                resources={'craft_material':available}
            except ValueError:
                self.journal.emit('craft_statistics_unavailable',image=screen.source)
        if self.options.track_craft_gold:
            try:resources['gold']=parse_amount(number(screen,'gold',(665,15,805,55)))
            except ValueError:self.journal.emit('craft_statistics_unavailable',image=screen.source)
        return ForgePreview(resources,{},self.options.slot,1,
                            self.options.source_index,screen.source,'result')


def read_charges(screen):
    """次数只读独立数字区域；全页OCR曾把170漏读成70，不能优先采用。"""
    from .local_ocr import read_local_regions
    values,evidence=read_local_regions(getattr(screen,'source',screen),{
        'counter':(538,340,574,364),'counter_tight':(539,340,572,364)})
    def accepted(key):
        return values[key].isdigit() and evidence[key].get('confidence',0)>=.95
    if accepted('counter') and accepted('counter_tight'):
        if values['counter']!=values['counter_tight']:
            raise ValueError('传说制作次数的独立区域识别冲突')
        return int(values['counter'])
    # 仅在拒识时扩大裁图重读；已接受的冲突数字不能被投票覆盖。
    extra,extra_evidence=read_local_regions(getattr(screen,'source',screen),{
        'counter_wide':(537,339,575,365),'counter_short':(538,341,574,363),
        'counter_digits':(538,342,574,362)})
    reliable=[values[key] for key in values if accepted(key)]
    reliable.extend(extra[key] for key in extra if extra[key].isdigit()
                    and extra_evidence[key].get('confidence',0)>=.95)
    if len(set(reliable))>1:
        raise ValueError('传说制作次数的独立区域识别冲突')
    if len(reliable)<2:
        # 位数变化后圆形边框占比不同；按中央白色字笔画定位完整左右边界。
        import numpy as np
        from PIL import Image
        with Image.open(getattr(screen,'source',screen)) as image:
            pixels=np.asarray(image.convert('RGB'))[346:359,538:574].astype(int)
        white=(pixels.min(axis=2)>180)&((pixels.max(axis=2)-pixels.min(axis=2))<50)
        columns=np.flatnonzero(white.sum(axis=0)>1)
        if len(columns):
            left=max(538,538+int(columns[0])-3)
            right=min(574,538+int(columns[-1])+4)
            adaptive,adaptive_evidence=read_local_regions(getattr(screen,'source',screen),{
                'counter_adaptive':(left,341,right,363),
                'counter_adaptive_tight':(left,342,right,362),
                'counter_adaptive_full':(left,340,right,364)})
            reliable.extend(adaptive[key] for key in adaptive if adaptive[key].isdigit()
                            and adaptive_evidence[key].get('confidence',0)>=.95)
    if len(reliable)<2 or len(set(reliable))!=1:
        raise ValueError('传说制作次数的独立区域识别未达成共识')
    return int(reliable[0])


def retry_observation(navigator,initial,observe,stage):
    """最多四次只读观察；不重发制作、选择或导航输入。"""
    for attempt in range(4):
        navigator.control.checkpoint()
        try:
            screen=initial if attempt==0 else navigator.read()
            return observe(screen)
        except ValueError as exc:
            if attempt==3:
                raise ValueError(f'{stage}连续4次识别失败：{exc}') from exc
            if getattr(navigator,'journal',None):
                navigator.journal.emit('legendary_observation_retry',stage=stage,
                    attempt=attempt+1,max_attempts=3,message=str(exc),input_repeated=False)
            navigator.control.wait(.2)


def observe_forge(loop,preview):
    def inspect(screen):
        current=screen if isinstance(screen,ForgePreview) else loop.preview(screen)
        return current,read_charges(current.image)
    return retry_observation(loop.navigator,preview,inspect,'工坊剩余次数')


def observe_settlement(loop,before,preview,*,result_verified):
    """成品及精确扣款已确认时，允许净次数不变；必须再取独立帧确认。"""
    previous=None
    def inspect(screen):
        nonlocal previous
        current=screen if isinstance(screen,ForgePreview) else loop.preview(screen)
        charges=read_charges(current.image)
        if before.get('verification')=='result':
            if result_verified and charges in (before['charges']-1,before['charges']):
                return current,charges
            if charges==before['charges']-1:
                return current,charges
            # 结果未确认且次数没有减少，才辅助核对材料；不会重发制作。
            if charges==before['charges'] and auxiliary_material_match(loop,before,current):
                return current,charges
            raise ValueError(f"传说制作结果与次数尚未确认：{before['charges']}→{charges}")
        expected={key:before['resources'][key]-cost for key,cost in before['cost'].items()}
        if any(current.resources.get(key)!=value for key,value in expected.items()):
            previous=None
            raise ValueError('传说制作实际材料扣除与单件费用不一致')
        if charges==before['charges']-1:
            return current,charges
        if charges==before['charges'] and result_verified:
            if previous and previous.image!=current.image and previous.resources==current.resources:
                if getattr(loop.navigator,'journal',None):
                    loop.navigator.journal.emit('legendary_unchanged_charges_verified',
                        charges=charges,images=[previous.image,current.image],resources=current.resources,
                        result_verified=True,input_repeated=False)
                return current,charges
            previous=current
            raise ValueError('次数净值未减少，正在双帧复核已确认成品与材料')
        previous=None
        raise ValueError(f"传说制作次数变化异常：{before['charges']}→{charges}")
    return retry_observation(loop.navigator,preview,inspect,'传说制作结算')


def observe_modal(navigator,screen,gear_set,resources,track_gold=False,track_material=None):
    def inspect(current):
        if current.page!='legendary_craft_confirmation':
            raise ValueError('传说制作确认页尚未稳定')
        current.find('制作',(700,490,930,600))
        verify_set_selection(current,gear_set)
        costs={}
        if track_material is None:
            available,cost=parse_material(number(current,'legendary_material',(140,412,312,445),r'[0-9,]+/[0-9,]+'))
            if available!=resources['craft_material']:
                raise ValueError('传说弹窗材料与工坊预览不一致')
            costs={'craft_material':cost}
        elif track_material:
            try:
                available,cost=parse_material(number(current,'legendary_material',(140,412,312,445),r'[0-9,]+/[0-9,]+'))
                if available==resources.get('craft_material'):costs={'craft_material':cost}
            except ValueError:
                if getattr(navigator,'journal',None):navigator.journal.emit('craft_statistics_unavailable',image=current.source)
        if track_gold:
            try:costs['gold']=parse_amount(number(current,'cost',(650,507,750,560)))
            except ValueError:
                if track_material is None:raise
        return current,costs
    return retry_observation(navigator,screen,inspect,'传说制作弹窗')


def auxiliary_material_match(loop,before,current):
    """仅在结果不明确时读取原确认截图和当前余额；不猜测扣款。"""
    from .workflow_screen import inspect_screen
    try:
        original=inspect_screen(before['last_image'])
        available,cost=parse_material(number(original,'legendary_material',(140,412,312,445),r'[0-9,]+/[0-9,]+'))
        observed=inspect_screen(current.image)
        after,_=parse_material(number(observed,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
        return cost>0 and available-after==cost
    except (ValueError,OSError,KeyError):
        return False


def verify_set_selection(screen,gear_set):
    from PIL import Image
    word=screen.find(SET_LABELS[gear_set]+'套装',(560,400,1100,480))
    x,y=map(round,word['center'])
    # 文字上方的卡片边框为金色；白色图案本身不作选中证据。
    with Image.open(screen.source) as image:
        pixels=list(image.convert('RGB').crop((x-60,y-120,x+60,y-105)).getdata())
    if sum(r>170 and g>145 and r-b>25 for r,g,b in pixels)/len(pixels)<.05:
        raise ValueError('传说套装金色选中边框未确认；未制作')


def verify_legendary_result(screen,slot,gear_set):
    names={'weapon':'武器','helmet':'头盔','armor':'铠甲','necklace':'项链','ring':'戒指','boots':'鞋子'}
    if screen.page!='legendary_craft_result':
        raise ValueError('未确认单件传说制作结果')
    screen.find('传说'+names[slot],(450,160,800,300))
    matches=[word for word in screen.words if word['confidence']>=.9
             and word['text'].startswith(SET_LABELS[gear_set]+'套装')
             and 450<=word['center'][0]<800 and 490<=word['center'][1]<600]
    if len(matches)!=1:
        raise ValueError('传说成品套装与目标不符或未可靠识别')


def wait_legendary_result(navigator,screen,slot,gear_set):
    """页面按钮先出现，装备标题仍可能被金光遮住；仅等待，不重复制作。"""
    for attempt in range(8):
        try:
            verify_legendary_result(screen,slot,gear_set)
            return screen
        except ValueError:
            if screen.page not in {'legendary_craft_result','unknown','forge'} or attempt==7:
                raise
        if navigator.journal:
            navigator.journal.emit('legendary_result_read_retry',attempt=attempt+1,image=screen.source,input_repeated=False)
        navigator.control.wait(.3)
        screen=navigator.read()


def preview_legendary(navigator,options,ledger,gear_set,journal):
    from .disposal_guard import BatchEnhancementGuard,DisposalGuard
    group=SET_GROUPS[options.source_index]
    if gear_set not in group:
        raise ValueError('所选套装不属于当前打造来源')
    for cls,folder in ((BatchEnhancementGuard,'enhancement-pending'),(DisposalGuard,'disposal-pending')):
        cls(journal.directory.parent/folder,navigator.adb.serial).check_clear()
    loop=LegendaryForgeLoop(navigator,options,ledger,navigator.control,journal)
    loop.guard.check_clear()
    preview=loop.configure()
    from .craft_results import material_shortage
    preview,charges=observe_forge(loop,preview)
    if charges<=0:
        return {'state':'charges_exhausted','charges':0,'last_image':navigator.last_image,'committed':False}
    journal.emit('legendary_selection_configured',source_index=options.source_index,
                 slot=options.slot,gear_set=gear_set,image=preview.image)
    navigator.control.checkpoint()
    navigator.adb.tap(507,389)
    screen=loop.wait_for({'legendary_craft_confirmation','inventory_full'})
    if screen.page=='inventory_full' or material_shortage(screen):
        return {'state':'resources_exhausted' if material_shortage(screen) else 'inventory_full',
                'last_image':screen.source,'committed':False}
    # 弹窗先确认套装名称，再选目标。不同来源拥有3或4套，不假设位置相同。
    word=screen.find(SET_LABELS[gear_set]+'套装',(560,400,1100,480))
    try:
        verify_set_selection(screen,gear_set)
    except ValueError:
        navigator.control.checkpoint()
        navigator.adb.tap(*(round(value) for value in word['center']))
        navigator.control.wait(.3)
        screen=navigator.read()
    screen,costs=observe_modal(navigator,screen,gear_set,preview.resources,options.track_craft_gold,
                             track_material=options.track_craft_consumption)
    journal.emit('legendary_preview_ready',source_index=options.source_index,slot=options.slot,
                 gear_set=gear_set,image=screen.source,committed=False)
    return {'state':'preview_ready','source_index':options.source_index,'slot':options.slot,
            'gear_set':gear_set,'last_image':screen.source,'committed':False,
            'charges':charges,'resources':preview.resources,'cost':costs,'verification':'result'}


def run_legendary(navigator,options,ledger,journal):
    """按结果与传说次数逐件制作；材料统计可选，不使用重新制作。"""
    from .craft_reservation import CraftReservation
    from .disposal_guard import CraftSessionGuard
    from .tasks import Cancelled
    guard=CraftSessionGuard(journal.directory.parent/'craft-pending',navigator.adb.serial)
    operation_id=None
    completed=0
    state='failed'
    last_image=None
    error=None
    remaining_charges=None
    recovered_count=0
    statistics_complete=options.track_craft_consumption
    try:
        pending=guard.read()
        if pending and pending['before'].get('mode')=='legendary':
            operation_id=pending['operation_id']
            journal.emit('legendary_auto_recovery_started',reason='启动时发现未结算制作',input_repeated=False)
            recovery=settle_legendary(navigator,options,ledger,journal)
            recovered_count+=recovery['recovered']
            operation_id=None
        guard.check_clear()
        while options.legendary_count is None or completed<options.legendary_count:
            preview=preview_legendary(navigator,options,ledger,options.legendary_set,journal)
            last_image=preview['last_image']
            remaining_charges=preview.get('charges')
            if preview['state']!='preview_ready':
                state='complete' if options.legendary_count is None and preview['state']=='charges_exhausted' else preview['state']
                break
            result_mode=preview.get('verification')=='result'
            reservation=None if result_mode else CraftReservation(ledger,preview['resources'],preview['cost'])
            try:
                if result_mode:
                    if ledger.steps>=ledger.limits.max_steps:raise ValueError('达到任务操作次数上限')
                else:reservation.check_next()
            except ValueError:
                navigator.transition('cancel_legendary_craft')
                state='budget_reached';break
            screen=navigator.read()
            screen,costs=observe_modal(navigator,screen,options.legendary_set,preview['resources'],options.track_craft_gold,
                                     **({'track_material':options.track_craft_consumption} if result_mode else {}))
            if not result_mode and costs!=preview['cost']:
                raise ValueError('传说制作确认前材料变化')
            button=screen.find('制作',(700,490,930,600))
            navigator.control.checkpoint()
            operation_id=guard.begin('craft',{'mode':'legendary',**preview},
                                     {'image':screen.source},journal.directory)
            if reservation:reservation.mark_commit()
            journal.emit('legendary_commit_intent',operation_id=operation_id,preview=preview,image=screen.source)
            navigator.adb.tap(*(round(value) for value in button['center']))
            loop=LegendaryForgeLoop(navigator,options,ledger,navigator.control,journal,guard=guard)
            try:
                result=loop.wait_for({'legendary_craft_result','inventory_full'})
                from .craft_results import material_shortage
                if result_mode and (material_shortage(result) or result.page=='inventory_full'):
                    guard.settle(operation_id);operation_id=None
                    state='resources_exhausted' if material_shortage(result) else 'inventory_full'
                    break
                if result.page=='inventory_full':
                    raise ValueError('传说制作提交后显示满包，正在核对是否扣款')
                wait_legendary_result(navigator,result,options.slot,options.legendary_set)
                final=loop.settlement_preview()
                final,after_charges=observe_settlement(loop,preview,final,result_verified=True)
            except (ValueError,TimeoutError) as exc:
                journal.emit('legendary_auto_recovery_started',reason=str(exc),input_repeated=False)
                recovery=settle_legendary(navigator,options,ledger,journal)
                actual=recovery['actual']
                after_charges=recovery['remaining_charges']
                last_image=recovery['last_image']
                recovered_count+=recovery['recovered']
            else:
                if result_mode:
                    from .craft_results import record_consumption
                    actual=record_consumption(ledger,preview['resources'],final.resources,preview['cost'],journal) if options.track_craft_consumption else {}
                    ledger.steps+=1
                else:actual=reservation.settle(final.resources)
                guard.settle(operation_id)
                last_image=final.image
            operation_id=None
            completed+=1
            if result_mode and not actual:statistics_complete=False
            remaining_charges=after_charges
            journal.emit('legendary_craft_settled',completed=completed,actual=actual,
                         charges_before=preview['charges'],charges_after=after_charges,image=last_image)
        else:
            state='complete'
    except Cancelled as exc:
        state='stopped';journal.emit('legendary_stopped',message=str(exc))
    except Exception as exc:
        error=str(exc)
        journal.emit('legendary_failed',message=str(exc))
    return {'state':state,'completed':completed,'spent':dict(ledger.spent),
            'outcome_unknown':operation_id is not None,'last_image':navigator.last_image or last_image,
            'remaining_charges':remaining_charges,'message':error,'recovered':recovered_count,
            'consumption_tracking':options.track_craft_consumption,
            'consumption_complete':statistics_complete and completed>0}


def settle_legendary(navigator,options,ledger,journal):
    """只核验既有提交的材料与次数，不再点击制作。"""
    import json
    from pathlib import Path
    from .disposal_guard import CraftSessionGuard
    from .craft_reservation import CraftReservation
    guard=CraftSessionGuard(journal.directory.parent/'craft-pending',navigator.adb.serial)
    record=guard.read()
    if not record or record['before'].get('mode')!='legendary':
        raise ValueError('没有可核验的传说制作回执')
    before=record['before']
    original=Path(record['run_directory']).resolve()
    if original.parent!=journal.directory.parent.resolve():
        raise ValueError('传说回执任务不属于当前工作区')
    events=[json.loads(line) for line in (original/'events.jsonl').read_text(encoding='utf8').splitlines()]
    commits=[e for e in events if e.get('kind')=='legendary_commit_intent'
             and e.get('operation_id')==record['operation_id']]
    expected={key:value for key,value in before.items() if key!='mode'}
    if len(commits)!=1 or commits[0].get('preview')!=expected or any(
            e.get('kind')=='legendary_craft_settled' for e in events[events.index(commits[0])+1:]):
        raise ValueError('传说提交日志不唯一、已结算或与回执冲突')
    if type(before.get('charges')) is not int or before['charges']<1:
        raise ValueError('传说回执缺少可靠次数')
    result_mode=before.get('verification')=='result'
    restored=replace(options,source_index=before['source_index'],slot=before['slot'],craft_count=1,
                     legendary_set=before['gear_set'],track_craft_gold='gold' in before['cost'],
                     track_craft_consumption=options.track_craft_consumption if result_mode else True)
    (journal.directory/'original-legendary-pending.json').write_text(
        json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    loop=LegendaryForgeLoop(navigator,restored,ledger,navigator.control,journal,guard=guard)
    from .workflow_screen import inspect_screen
    following=events[events.index(commits[0])+1:]
    if any(event.get('kind')=='legendary_commit_intent' for event in following):
        raise ValueError('原提交之后存在其他制作提交，不能混用结算截图')
    result_verified=False
    for event in following:
        if event.get('kind')!='workflow_screen' or event.get('page')!='legendary_craft_result':
            continue
        image=Path(event['image']).resolve()
        if image.parent!=original:raise ValueError('传说结果截图不属于原任务')
        try:
            verify_legendary_result(inspect_screen(image),before['slot'],before['gear_set'])
        except ValueError:
            continue
        result_verified=True
        break
    archived=None
    if result_verified:
        expected_resources={key:before['resources'][key]-cost for key,cost in before['cost'].items()}
        samples=[]
        seen=set()
        for event in reversed(following):
            if event.get('kind')!='workflow_screen' or event.get('page')!='forge':continue
            image=Path(event['image']).resolve()
            if image.parent!=original:raise ValueError('传说结算截图不属于原任务')
            if image in seen:continue
            seen.add(image)
            try:
                candidate=loop.preview(inspect_screen(image))
                count=read_charges(candidate.image)
            except ValueError:
                continue
            if count not in (before['charges']-1,before['charges']):continue
            if not result_mode and any(candidate.resources.get(key)!=value for key,value in expected_resources.items()):continue
            samples.append((candidate,count))
            if len(samples)==2:
                if (result_mode or samples[0][0].resources==candidate.resources) and samples[0][1]==count:
                    archived=(samples[0][0],candidate,count)
                    break
                samples=[samples[-1]]
    if archived:
        final,second,charges=archived
        journal.emit('legendary_archived_settlement_verified',images=[final.image,second.image],
                     charges=charges,resources=final.resources,input_repeated=False)
    else:
        screen=navigator.read()
        if screen.page not in {'legendary_craft_result','forge'}:
            raise ValueError('当前不是传说结果或工坊页，保留回执')
        if screen.page=='legendary_craft_result':
            wait_legendary_result(navigator,screen,before['slot'],before['gear_set'])
            result_verified=True
        # 当前未选部位时只恢复原选择，不提交制作。
        final=loop.configure()
        final,charges=observe_settlement(loop,before,final,result_verified=result_verified)
        second=loop.preview(navigator.read())
        second_charges=read_charges(second.image)
        if (second_charges!=charges if result_mode else
                (second.resources,second.cost,second_charges)!=(final.resources,final.cost,charges)):
            raise ValueError('传说核验双帧资源不稳定，保留回执')
    if guard.read()!=record:
        raise ValueError('传说待结算记录发生变化')
    if result_mode:
        from .craft_results import record_consumption
        actual=record_consumption(ledger,before['resources'],final.resources,before['cost'],journal) if restored.track_craft_consumption else {}
        ledger.steps+=1
    else:
        reservation=CraftReservation(ledger,before['resources'],before['cost'])
        reservation.mark_commit()
        actual=reservation.settle(final.resources)
    journal.emit('legendary_recovered',operation_id=record['operation_id'],actual=actual,
                 charges_before=before['charges'],charges_after=charges,input_repeated=False)
    guard.settle(record['operation_id'])
    return {'state':'complete','recovered':1,'completed':0,'spent':dict(ledger.spent),
            'outcome_unknown':False,'last_image':second.image,'actual':actual,'remaining_charges':charges}
