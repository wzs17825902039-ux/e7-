"""原生1/10次打造与结果页重新制作；材料核对仅用于可选统计与异常恢复。"""
from dataclasses import dataclass
import re

from .craft_reservation import CraftReservation
from .crafting import SLOTS, parse_material
from .live import parse_amount
from .local_ocr import read_local_regions
from .tasks import Cancelled


@dataclass(frozen=True)
class ForgePreview:
    resources: dict
    cost: dict
    slot: str
    count: int
    source_index: int
    image: str
    verification: str = 'material'


class ForgeBudgetReached(ValueError):
    pass


def _dimmed_number(source,box,pattern):
    """暗色结果遮罩上保留完整数字框；亮点不能决定裁边或拉伸范围。"""
    import numpy as np
    from PIL import Image,ImageEnhance,ImageOps
    from .local_ocr import _engine
    with Image.open(source) as image:
        patch=image.crop(box).convert('RGB')
    inference=_engine()
    candidates=[]
    for variant in (patch,ImageEnhance.Brightness(patch).enhance(5),
                    ImageOps.autocontrast(patch,cutoff=2),ImageOps.autocontrast(patch,cutoff=5)):
        raw,_=inference(np.asarray(variant)[:,:,::-1].copy(),use_det=False,use_cls=False)
        candidates.append(raw[0] if raw else ('',0))
    text=candidates[1][0]
    if (not re.fullmatch(pattern,text)
            or any(value!=text or confidence<.95 for value,confidence in candidates[1:])
            or (candidates[0][1]>=.9 and re.fullmatch(pattern,candidates[0][0])
                and candidates[0][0]!=text)):
        raise ValueError('暗色数字完整区域识别未达成共识')
    return text


def number(screen,key,box,pattern=r'[0-9,]+',contrast=False):
    full_values=[w['text'] for w in screen.words if w['confidence']>=.9
            and box[0]<=w['center'][0]<box[2] and box[1]<=w['center'][1]<box[3]
            and re.fullmatch(pattern,w['text'])]
    if len(full_values)==1 and not contrast:
        return full_values[0]
    values,_=read_local_regions(screen.source,{key:box},contrast=contrast)
    if not re.fullmatch(pattern,values[key]):
        if contrast:
            recovered=_dimmed_number(screen.source,box,pattern)
            if any(value!=recovered for value in full_values):
                raise ValueError(f'{key}完整区域与整页读数冲突')
            return recovered
        raise ValueError(f'{key}未可靠识别')
    return values[key]


def verify_selection(screen,options,fields=('source','slot','count')):
    from PIL import Image
    if screen.page!='forge':
        raise ValueError('未确认普通制作页面')
    if not any(re.fullmatch(r'制作装备[【〖].+[】〗]',w['text']) and w['confidence']>=.9 for w in screen.words):
        raise ValueError('制作来源标题未确认')
    with Image.open(screen.source) as image:
        image=image.convert('RGB')
        def blue(box):
            pixels=list(image.crop(box).getdata())
            return sum(b>120 and g>110 and b>r*1.1 for r,g,b in pixels)/len(pixels)
        index=options.source_index
        if 'source' in fields and blue((155+index*100,132,244+index*100,139))<.15:
            raise ValueError('打造来源选中状态未确认')
        selected=[]
        for name,(x,y) in SLOTS.items():
            pixels=list(image.crop((x-42,y-42,x+42,y-36)).getdata())
            ratio=sum(b>70 and g>60 and b>r*1.15 and g>r*1.1 for r,g,b in pixels)/len(pixels)
            if ratio>.15:
                selected.append(name)
        if 'slot' in fields and selected!=[options.slot]:
            raise ValueError('打造部位选中状态未确认')
        chosen,other=(1168,1250) if options.craft_count==1 else (1250,1168)
        if 'count' in fields and (min(image.getpixel((chosen,495)))<150 or max(image.getpixel((other,495)))>150):
            raise ValueError('实际制作次数与设置不符')


class LiveForgeLoop:
    def __init__(self,navigator,options,ledger,control,journal,guard=None):
        from .disposal_guard import CraftSessionGuard
        self.navigator,self.options,self.ledger=navigator,options,ledger
        self.control,self.journal=control,journal
        self.guard=guard if guard is not None else CraftSessionGuard(
            journal.directory.parent/'craft-pending',navigator.adb.serial)
        self.session_id=None

    def preview(self,screen):
        verify_selection(screen,self.options)
        if not self.options.track_craft_gold:
            resources={};costs={}
            if self.options.track_craft_consumption:
                try:
                    available,cost=parse_material(number(screen,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
                    resources={'craft_material':available};costs={'craft_material':cost}
                except ValueError:
                    self.journal.emit('craft_statistics_unavailable',image=screen.source)
            return ForgePreview(resources,costs,self.options.slot,self.options.craft_count,
                                self.options.source_index,screen.source,'result')
        available,cost=parse_material(number(screen,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
        resources={'craft_material':available};costs={'craft_material':cost}
        if self.options.track_craft_gold:
            resources['gold']=parse_amount(number(screen,'gold',(665,15,805,55)))
            costs['gold']=parse_amount(number(screen,'cost',(985,645,1085,695)))
        return ForgePreview(resources,costs,self.options.slot,self.options.craft_count,
                            self.options.source_index,screen.source)

    def configure(self,select_count=True):
        screen=self.navigator.navigate('forge')
        selections=[('source',(200+self.options.source_index*100,108)),
                    ('slot',SLOTS[self.options.slot])]
        if select_count:
            selections.append(('count',(1186 if self.options.craft_count==1 else 1240,497)))
        for field,point in selections:
            if screen.page!='forge':
                raise ValueError('选择打造参数时页面发生变化')
            try:
                verify_selection(screen,self.options,fields=(field,))
            except ValueError:
                pass
            else:
                continue
            self.control.checkpoint()
            self.navigator.adb.tap(*point)
            self.control.wait(.5)
            screen=self.navigator.read()
        return self.preview(screen)

    def wait_for(self,pages):
        for _ in range(10):
            self.control.wait(.2)
            screen=getattr(self.navigator,'read_forge',self.navigator.read)()
            from .craft_results import material_shortage
            if material_shortage(screen):
                return screen
            if screen.page in pages:
                return screen
            if screen.page in {'interruption','unknown'}:
                continue  # 动画期间只读取，不再次点击。
            if screen.page in {'extract_confirmation','sale_confirmation'}:
                raise ValueError('打造遇到意外处置弹窗，未确认')
        raise TimeoutError('未确认打造结果，禁止再次发送制作')

    def verify_confirmation(self,screen,preview):
        from PIL import Image
        from .batch_vision import _vector
        if screen.page!='craft_confirmation':
            raise ValueError('未确认制作弹窗')
        screen.find(f'制作装备{preview.count}次',(400,140,850,220))
        cost={}
        if preview.verification!='result':
            cost={'craft_material':parse_amount(number(screen,'material',(395,405,465,455)))}
        if self.options.track_craft_gold:
            cost['gold']=parse_amount(number(screen,'cost',(650,507,750,560)))
        if preview.verification!='result' and cost!=preview.cost:
            raise ValueError('确认弹窗费用与预览不一致')
        # 核对弹窗装备图与刚选中的部位图，不依赖装备名字OCR。
        x,y=SLOTS[preview.slot]
        with Image.open(preview.image) as before,Image.open(screen.source) as current:
            expected=_vector(before.crop((x-32,y-32,x+32,y+32)))
            observed=_vector(current.crop((635,361,701,427)))
        if sum(a*b for a,b in zip(expected,observed))<.94:
            raise ValueError('制作弹窗装备图与目标部位不一致')

    def settlement_preview(self):
        screen=self.navigator.navigate('forge')
        for attempt in range(3):
            try:
                return self.preview(screen)
            except ValueError as exc:
                if str(exc)!='material未可靠识别' or attempt==2:
                    raise
                self.journal.emit('craft_settlement_read_retry',attempt=attempt+1,
                                  image=screen.source,input_repeated=False)
                self.control.wait(.3)
                screen=self.navigator.read()

    def run(self):
        try:
            self.guard.check_clear()
            preview=self.configure()
        except Cancelled as exc:
            state='stopped'
            self.journal.emit('craft_stopped',message=str(exc),outcome_unknown=False)
        except Exception as exc:
            state='failed'
            self.journal.emit('craft_failed',message=str(exc),outcome_unknown=False)
        else:
            return self.run_by_results(preview)
        result={'state':state,'batches':0,'spent':dict(self.ledger.spent),'outcome_unknown':False,
                'craft_gold_tracked':self.options.track_craft_gold,'reservation':None}
        self.journal.emit('craft_session_finished',**result)
        return result

    def run_by_results(self,preview):
        """统一制作循环；默认由结果推进，旧预算模式仅附加预留与核账。"""
        from dataclasses import asdict
        from .craft_results import material_shortage,record_consumption
        confirmed=0;pending=False;state='failed';actual={};reservation=None
        try:
            if preview.verification!='result':
                reservation=CraftReservation(self.ledger,preview.resources,preview.cost)
                try:reservation.check_next()
                except ValueError as exc:raise ForgeBudgetReached(str(exc)) from exc
            screen=self.navigator.read()
            if material_shortage(screen):
                state='resources_exhausted'
            else:
                if reservation:
                    fresh=self.preview(screen)
                    if (fresh.resources,fresh.cost)!=(preview.resources,preview.cost):
                        raise ValueError('制作前资源或费用发生变化')
                else:
                    verify_selection(screen,self.options)
                word=screen.find('制作',(1100,635,1260,710))
                self.navigator.adb.tap(*(round(v) for v in word['center']))
                screen=self.wait_for({'craft_confirmation','inventory_full'})
                while True:
                    if screen.page=='inventory_full':state='inventory_full';break
                    if material_shortage(screen):state='resources_exhausted';break
                    if self.ledger.steps>=self.ledger.limits.max_steps:
                        state='budget_reached';break
                    self.verify_confirmation(screen,preview)
                    button=screen.find('制作',(770,500,880,565))
                    self.control.checkpoint()
                    if reservation:reservation.check_next()
                    if self.session_id is None:
                        self.session_id=self.guard.begin('craft',asdict(preview)|{'confirmed_batches':confirmed},
                                                         {'image':screen.source},self.journal.directory)
                        self.journal.emit('craft_session_started',operation_id=self.session_id,
                                          pending_record=str(self.guard.path))
                    self.journal.emit('craft_commit_intent',operation_id=self.session_id,image=screen.source,
                                      verification=preview.verification,next_cost=preview.cost if reservation else {},
                                      accounting=reservation.evidence() if reservation else {'confirmed_attempts':confirmed})
                    if reservation:reservation.mark_commit()
                    pending=True
                    self.navigator.adb.tap(*(round(v) for v in button['center']))
                    auxiliary=False
                    try:
                        result=self.wait_for({'craft_result','inventory_full'})
                    except (ValueError,TimeoutError):
                        if reservation:raise
                        result=self.auxiliary_result(preview,confirmed+1)
                        auxiliary=True
                    if result.page!='craft_result' and not auxiliary:
                        if material_shortage(result) or result.page=='inventory_full':
                            if reservation:raise ValueError('预算模式已提交制作但未看到结果，保留回执')
                            self.guard.settle(self.session_id);self.session_id=None;pending=False
                            state='resources_exhausted' if material_shortage(result) else 'inventory_full'
                            break
                        raise ValueError('未确认制作结果，未重新点击制作')
                    if reservation and self.options.track_craft_gold:
                        reservation.observe_gold(parse_amount(number(result,'gold',(665,15,805,55),contrast=True)))
                    self.journal.emit('craft_result_observed',operation_id=self.session_id,image=result.source,
                                      verification='material' if auxiliary else 'result',
                                      accounting=reservation.evidence() if reservation else {'confirmed_attempts':confirmed+1})
                    if not reservation:
                        self.guard.settle(self.session_id);self.session_id=None;pending=False
                        self.ledger.steps+=1
                    confirmed+=1
                    if reservation:
                        try:reservation.check_next()
                        except ValueError:
                            state='budget_reached';break
                    if self.ledger.steps>=self.ledger.limits.max_steps:
                        state='budget_reached';break
                    button=result.find('制作',(1100,635,1260,710)) if auxiliary else result.find('重新制作',(750,615,925,695))
                    self.control.checkpoint()
                    self.journal.emit('craft_repeat_open_intent',image=result.source)
                    self.navigator.adb.tap(*(round(v) for v in button['center']))
                    screen=self.wait_for({'craft_confirmation','inventory_full'})
            if reservation:
                final=self.settlement_preview()
                actual=reservation.settle(final.resources)
                self.journal.emit('craft_session_settled',actual=actual,batches=confirmed,reason=state,image=final.image)
                if self.session_id is not None:
                    self.guard.settle(self.session_id);self.session_id=None
                pending=False
            elif self.options.track_craft_consumption and confirmed and not pending:
                try:
                    final=self.settlement_preview()
                    actual=record_consumption(self.ledger,preview.resources,final.resources,
                        {key:value*confirmed for key,value in preview.cost.items()},self.journal)
                except (ValueError,TimeoutError) as exc:
                    self.journal.emit('craft_statistics_unavailable',message=str(exc))
        except ForgeBudgetReached as exc:
            state='budget_reached';self.journal.emit('craft_budget_reached',message=str(exc))
        except Cancelled as exc:
            state='stopped';self.journal.emit('craft_stopped',message=str(exc),outcome_unknown=pending)
        except Exception as exc:
            state='failed'
            self.journal.emit('craft_failed',message=str(exc),outcome_unknown=pending)
        result={'state':state,'batches':confirmed,'spent':dict(self.ledger.spent),'outcome_unknown':pending,
                'craft_gold_tracked':self.options.track_craft_gold,'consumption_tracking':self.options.track_craft_consumption,
                'consumption_complete':bool(actual),'reservation':reservation.evidence() if reservation else None}
        self.journal.emit('craft_session_finished',**result)
        return result

    def auxiliary_result(self,preview,batches):
        """仅在结果重读失败后比较原始截图；核对失败保留记录，绝不重发。"""
        from .workflow_screen import inspect_screen
        original=inspect_screen(preview.image)
        available,cost=parse_material(number(original,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
        screen=self.navigator.navigate('forge')
        verify_selection(screen,self.options)
        after,_=parse_material(number(screen,'material',(1020,582,1168,625),r'[0-9,]+/[0-9,]+'))
        if cost<=0 or available-after!=cost*batches:
            raise ValueError('结果未确认且辅助材料核对不符，未重复制作')
        self.journal.emit('craft_auxiliary_material_verified',batches=batches,image=screen.source,input_repeated=False)
        return screen
