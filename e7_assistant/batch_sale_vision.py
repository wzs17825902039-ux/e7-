"""整理页取证：与已核对的普通批量页逐块对照，独立读取绿色勾选。"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import numpy as np
from PIL import Image

from .forge_loop import number
from .slot_vision import inspect_slots


def origin(index):
    if type(index) is not int or not 0<=index<16:
        raise ValueError('批量整理索引越界')
    row,col=divmod(index,4)
    return round(col*316.667*1280/1661),round(row*167.333*720/933)


def content_proof(before,after,index,after_index=None,*,strict=False,attributes_only=False):
    """允许整理遮罩的统一亮度缩放；每个属性块均须保持图形。"""
    if before.size!=(1280,720) or after.size!=before.size:
        raise ValueError('整理卡片比对只接受完整1280×720截图')
    dx,dy=origin(index)
    ax,ay=origin(index if after_index is None else after_index)
    # 排除绿色勾选、选中边框及整理模式隐藏的锁按钮。
    boxes=[(25,139,101,160),(27,198,102,215),(37,219,85,240),
           (110,140,185,157)]
    if attributes_only:
        # 强化阶段已在完整结果观察中读取；稳定帧只复核主副词条，
        # 不让装备大图、套装徽章或游戏综合分的光效阻塞属性判断。
        boxes=[(110,140,185,157)]
    boxes.extend((110,160+i*22,185,182+i*22) for i in range(4))
    evidence=[]
    if strict:
        before_gray,after_gray=before.convert('L'),after.convert('L')
    else:
        # 强化增量的橙色高亮会恢复白色；最大颜色通道保留同一字形的亮度，
        # 避免灰度加权把正常变色当成数字改变。严格的同帧核验仍使用原灰度。
        before_gray=Image.fromarray(np.asarray(before.convert('RGB')).max(axis=2))
        after_gray=Image.fromarray(np.asarray(after.convert('RGB')).max(axis=2))
    for box in boxes:
        before_box=tuple(v+(dx if i%2==0 else dy) for i,v in enumerate(box))
        after_box=tuple(v+(ax if i%2==0 else ay) for i,v in enumerate(box))
        a=np.asarray(before_gray.crop(before_box),dtype=float).ravel()
        b=np.asarray(after_gray.crop(after_box),dtype=float).ravel()
        # 紫装第四属性尚未解锁，空区域也必须像素一致；不将空白当身份。
        if a.std()<8:
            if np.abs(a-b).mean()>3:
                raise ValueError('整理空属性区域发生变化')
            if strict and np.abs(a-b).max()>12:
                raise ValueError('空属性区域出现局部像素变化')
            evidence.append({'blank':True})
            continue
        if b.std()<4:
            raise ValueError('整理装备内容被遮挡或消失')
        corr=float(np.corrcoef(a,b)[0,1])
        scale=float(((a-a.mean())*(b-b.mean())).sum()/((a-a.mean())**2).sum())
        error=float(np.abs(b-(a*scale+b.mean()-scale*a.mean())).mean())
        if not np.isfinite([corr,scale,error]).all() or corr<.995 or not .3<=scale<=1.1 or error>2:
            raise ValueError('整理装备内容与已登记装备不一致')
        if strict and np.abs(b-(a*scale+b.mean()-scale*a.mean())).max()>12:
            raise ValueError('属性字形存在局部变化，需要重新识别')
        evidence.append({'correlation':corr,'scale':scale,'mae':error})
    if sum(not x.get('blank',False) for x in evidence)<(4 if attributes_only else 5):
        raise ValueError('整理装备缺少足够内容证据')
    return evidence


def selected_state(image,index):
    dx,dy=origin(index)
    pixels=np.asarray(image.convert('RGB'),dtype=float)
    crop=pixels[160+dy:198+dy,38+dx:88+dx]
    mask=(crop[:,:,1]>65)&(crop[:,:,1]>crop[:,:,0]*1.25)&(crop[:,:,1]>crop[:,:,2]*1.4)
    with Image.open(Path(__file__).with_name('assets')/'batch-organize/check.png') as template:
        expected=np.asarray(template)>128
    iou=float((mask&expected).sum()/max(1,(mask|expected).sum()))
    border=pixels[126+dy:129+dy,30+dx:235+dx]
    yellow=(border[:,:,0]>130)&(border[:,:,1]>130)&(border[:,:,2]<border[:,:,0]*.9)
    ratio=float(yellow.mean())
    if iou>=.85 and ratio>=.4:
        return True
    if mask.sum()<=3 and ratio<=.02:
        return False
    raise ValueError('整理勾选图形与边框未一致确认')


@dataclass(frozen=True)
class OrganizedBatch:
    selected: tuple
    gold: int | None
    image: str
    evidence: tuple


def inspect_organized(screen,reference,count,track_gold=True,locked_indices=(),boosted_red_indices=()):
    if screen.page!='batch_organize' or type(count) is not int or not 1<=count<=16:
        raise ValueError('整理页或登记件数无效')
    selected_count=int(number(screen,'selected_count',(742,75,793,112),r'\[[0-9]{1,2}\]')[1:-1])
    gold=int(number(screen,'gold',(665,15,805,55)).replace(',','')) if track_gold else None
    with Image.open(reference) as before,Image.open(screen.source) as current:
        states=inspect_slots(current.convert('RGB').resize((1661,933)))
        if any(slot['state']!='empty' for slot in states[count:]):
            raise ValueError('整理页出现未登记装备或未知尾槽')
        if any(type(i) is not int or not 0<=i<count for i in locked_indices):
            raise ValueError('整理锁定索引无效')
        proofs=tuple(locked_organize_proof(before,current,index,attributes_only=index in boosted_red_indices) if index in locked_indices
                     else content_proof(before,current,index,attributes_only=index in boosted_red_indices) for index in range(count))
        selected=tuple(selected_state(current,index) for index in range(count))
    if any(selected[i] for i in locked_indices):
        raise ValueError('已锁保留装备在整理中被选中，禁止出售')
    if sum(selected)!=selected_count:
        raise ValueError('整理卡片勾选与标题计数不一致')
    return OrganizedBatch(selected,gold,screen.source,proofs)


def locked_organize_proof(before,after,index,*,attributes_only=False):
    """已知锁定装备在整理页有额外暗层与左上锁标；独立确认不可选状态。"""
    dx,dy=origin(index)
    with Image.open(Path(__file__).with_name('assets')/'batch-organize/locked.png') as template:
        expected=np.asarray(template.convert('RGB'),dtype=float)
    actual=np.asarray(after.convert('RGB').crop((20+dx,131+dy,37+dx,153+dy)),dtype=float)
    if actual.shape!=expected.shape or np.abs(actual-expected).mean()>3:
        raise ValueError('整理页已锁装备未确认左上锁标')
    if attributes_only:
        # 已锁装备在整理页不可选，暗层使词条失去可靠像素证据。
        # 此处只确认保护标记；解除整理暗层后的幸存者必须逐词条核对。
        return [{'locked':True,'content_check':'deferred_until_overlay_removed'}]
    # 锁遮住等级与极暗文字；仍用两处未遮挡图案核对原卡片，不核对暗层文字。
    evidence=[]
    for box in ((27,174,102,195),(27,198,102,215)):
        region=tuple(v+(dx if i%2==0 else dy) for i,v in enumerate(box))
        a=np.asarray(before.convert('L').crop(region),dtype=float).ravel()
        b=np.asarray(after.convert('L').crop(region),dtype=float).ravel()
        corr=float(np.corrcoef(a,b)[0,1])
        scale=float(((a-a.mean())*(b-b.mean())).sum()/max(1,((a-a.mean())**2).sum()))
        error=float(np.abs(b-(a*scale+b.mean()-scale*a.mean())).mean())
        if not np.isfinite([corr,scale,error]).all() or corr<.995 or not .1<=scale<=.3 or error>1:
            raise ValueError('整理已锁装备图案与原卡片不一致')
        evidence.append({'locked':True,'correlation':corr,'scale':scale,'mae':error})
    return evidence


@dataclass(frozen=True)
class SaleConfirmation:
    count: int
    gold: int
    powder: int
    digest: str
    image: str
    jewelry_powder: int = 0


def sale_confirmation_unchanged(before,after):
    """产物逐项相同；哈希变化仅允许已核验原图的微小渲染色差。"""
    fields=('count','gold','powder','jewelry_powder')
    if any(getattr(before,key)!=getattr(after,key) for key in fields):
        return False
    if before.digest==after.digest:
        return True
    crops=[]
    try:
        for proof in (before,after):
            with Image.open(proof.image) as image:
                if image.size!=(1280,720):return False
                crop=image.convert('RGB').crop((400,140,880,570))
                if hashlib.sha256(crop.tobytes()).hexdigest()!=proof.digest:
                    return False
                crops.append(np.asarray(crop,dtype=np.int16))
    except (OSError,ValueError):
        return False
    # 半透明弹窗的空白区域会透出装备光效；只比较交易前景。
    # 四块覆盖标题、完整件数句、全部产物和数值、取消/确认按钮。
    # 原图digest仍须逐张匹配，数值与类型也必须全部一致。
    for left,top,right,bottom in ((550,160,730,220),(430,240,850,290),
                                   (480,330,800,425),(400,490,850,570)):
        a,b=[crop[top-140:bottom-140,left-400:right-400] for crop in crops]
        difference=np.abs(a-b)
        if difference.max()>2 or difference.mean()>.1:
            return False
    return True


def verify_sale_survivors(screen,reference,items,rejected):
    """出售后保留原位置：逐块比对内容、锁和全部空槽，不重新猜测属性数字。"""
    from .lock_vision import inspect_batch_lock
    if screen.page!='batch_enhancement':raise ValueError('出售结果不是批量强化页')
    with Image.open(reference) as before,Image.open(screen.source) as after:
        occupied={index for index,item in enumerate(items) if item.token not in rejected}
        states=inspect_slots(after.convert('RGB').resize((1661,933)),
                             {i for i in occupied if items[i].equipment.enhancement_bonus},
                             {i:items[i].equipment.rarity for i in occupied})
        if [s['state'] for s in states]!=['occupied' if i in occupied else 'empty' for i in range(16)]:
            raise ValueError('出售结果的保留位置或空槽不符')
        for index in sorted(occupied):
            content_proof(before,after,index,index,attributes_only=items[index].equipment.enhancement_bonus)
            lock=inspect_batch_lock(after,'batch_enhancement',index,True)
            if lock['locked'] is not items[index].locked:
                raise ValueError('出售后保留装备锁状态变化')


def inspect_sale_confirmation(screen):
    if screen.page!='sale_confirmation':
        raise ValueError('未确认批量出售弹窗')
    screen.find('出售',(400,140,880,220),.95)
    screen.find('取消',(400,490,650,570),.95)
    screen.find('确认',(650,490,850,570),.95)
    matches=[re.fullmatch(r'确定要出售选中的([1-9]\d*)件道具[?？]',w['text'])
             for w in screen.words if w['confidence']>=.95
             and 400<=w['center'][0]<880 and 240<=w['center'][1]<290]
    matches=[m for m in matches if m]
    if len(matches)!=1 or not 1<=int(matches[0][1])<=16:
        raise ValueError('出售弹窗件数未唯一确认')
    with Image.open(screen.source) as image:
        if image.size!=(1280,720):
            raise ValueError('出售弹窗取证只支持1280×720完整截图')
        def matches_icon(name,box):
            with Image.open(Path(__file__).with_name('assets')/'batch-organize'/f'{name}-reward.png') as expected:
                a=np.asarray(expected.convert('RGB'),dtype=float)
                b=np.asarray(image.convert('RGB').crop(box),dtype=float)
                return bool(np.abs(a-b).mean()<=2 and np.corrcoef(a.ravel(),b.ravel())[0,1]>=.995)
        layouts=[]
        if matches_icon('gold',(552,339,619,388)):
            for key,template in (('powder','powder'),('jewelry_powder','jewelry-powder')):
                if matches_icon(template,(659,339,728,388)):
                    layouts.append({'gold':(540,390,635,425),key:(650,390,740,425)})
        if matches_icon('mixed-gold',(498,339,565,388)):
            # 两种产物的顺序会变化，分别按图标确认类型，不能固定左右映射。
            for middle,right in (('powder','jewelry_powder'),('jewelry_powder','powder')):
                names={'powder':'mixed-equipment-powder','jewelry_powder':'mixed-accessory-powder'}
                if (matches_icon(names[middle],(605,339,674,388))
                        and matches_icon(names[right],(713,339,782,388))):
                    layouts.append({'gold':(487,390,578,425),middle:(595,390,686,425),right:(703,390,794,425)})
        if len(layouts)!=1:
            raise ValueError('出售产物类型或布局尚未唯一确认')
        digest=hashlib.sha256(image.convert('RGB').crop((400,140,880,570)).tobytes()).hexdigest()
    amounts={key:int(number(screen,f'sale_{key}',box,r'[0-9,]+').replace(',',''))
             for key,box in layouts[0].items()}
    if any(value<=0 for value in amounts.values()):
        raise ValueError('出售收入数量未确认')
    return SaleConfirmation(int(matches[0][1]),amounts['gold'],amounts.get('powder',0),
                            digest,screen.source,amounts.get('jewelry_powder',0))
