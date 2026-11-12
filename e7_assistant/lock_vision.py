"""背包详情与批量卡片锁按钮的独立双模板识别。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@lru_cache(maxsize=1)
def _templates():
    result = {}
    for state in ('locked', 'unlocked'):
        with Image.open(Path(__file__).with_name('assets') / 'locks' / (state + '.png')) as image:
            result[state] = np.asarray(image.convert('RGB')).astype(np.float32)
    return result


def inspect_detail_lock(image, page):
    """仅在已确认的完整1280×720背包详情页使用；未知返回None。"""
    if page not in ('inventory', 'inventory_manage') or image.size != (1280, 720):
        return {'locked': None, 'scores': {}, 'reason': '页面或尺寸未确认'}
    roi = np.asarray(image.convert('RGB').crop((1170, 166, 1215, 201))).astype(np.float32)
    scores = {state: float(cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)[0, 0])
              for state, template in _templates().items()}
    ranked = sorted(scores, key=scores.get, reverse=True)
    best, second = ranked
    # 相关性和绝对像素误差共同约束，避免相同形状在错误背景上被接受。
    error = float(np.mean(np.abs(roi - _templates()[best])))
    accepted = scores[best] >= .94 and scores[best] - scores[second] >= .15 and error <= 18
    return {'locked': (best == 'locked') if accepted else None,
            'scores': {key: round(value, 4) for key, value in scores.items()},
            'pixel_error': round(error, 3), 'reason': '双模板确认' if accepted else '锁按钮待复核'}


def batch_offset(index):
    if type(index) is not int or not 0 <= index < 16:
        raise ValueError('批量卡片位置必须为0～15')
    row,col=divmod(index,4)
    return round(col*316.667),round(row*167.333)


@lru_cache(maxsize=1)
def _batch_templates():
    result={}
    for state in ('locked','unlocked'):
        with Image.open(Path(__file__).with_name('assets')/'locks'/('batch-'+state+'.png')) as image:
            result[state]=np.asarray(image.convert('RGB')).astype(np.float32)
    return result


def inspect_batch_lock(image,page,index,occupied):
    dx,dy=batch_offset(index)
    if (page!='batch_enhancement' or occupied is not True
            or abs(image.width/image.height-16/9)>.02):
        return {'locked':None,'reason':'页面、尺寸或占用状态未确认'}
    reference=image.convert('RGB').resize((1661,933))
    roi=np.asarray(reference.crop((274+dx,172+dy,327+dx,213+dy))).astype(np.float32)
    scores={state:float(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED)[0,0])
            for state,template in _batch_templates().items()}
    best,second=sorted(scores,key=scores.get,reverse=True)
    error=float(np.abs(roi-_batch_templates()[best]).mean())
    accepted=(all(np.isfinite(v) for v in scores.values()) and scores[best]>=.94
              and scores[best]-scores[second]>=.15 and error<=18)
    alignment=None
    if not accepted:
        # 各槽位缩放取样相位不同；仅在标定按钮周围1像素内作四分之一像素配准。
        search=np.asarray(reference.crop((273+dx,171+dy,328+dx,214+dy))).astype(np.float32)
        search=cv2.resize(search,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
        aligned={}
        for state,template in _batch_templates().items():
            template=cv2.resize(template,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
            _,score,_,offset=cv2.minMaxLoc(cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED))
            x,y=offset
            aligned[state]=(score,float(np.abs(search[y:y+164,x:x+212]-template).mean()),
                            (x/4-1,y/4-1))
        first,runner=sorted(aligned,key=lambda key:aligned[key][0],reverse=True)
        score,aligned_error,offset=aligned[first]
        if (all(np.isfinite(v[0]) for v in aligned.values()) and score>=.94
                and score-aligned[runner][0]>=.15 and aligned_error<=18):
            best=first
            scores={key:value[0] for key,value in aligned.items()}
            error=aligned_error
            alignment=offset
            accepted=True
    return {'locked':(best=='locked') if accepted else None,
            'scores':scores,'pixel_error':error,'alignment':alignment,
            'reason':'双模板确认' if accepted else '批量锁按钮待复核'}


def verify_batch_lock_pixels(before,after,count,target,*,attributes_only=False):
    """已确认批量页的一次锁动作，只允许目标按钮与左上锁标变化。"""
    if before.size!=(1280,720) or after.size!=before.size:
        raise ValueError('锁动作画面尺寸未确认')
    if type(count) is not int or not 1<=count<=16 or type(target) is not int or not 0<=target<count:
        raise ValueError('锁动作登记数量或目标无效')
    if attributes_only:
        from .batch_sale_vision import content_proof
        for index in range(count):
            content_proof(before,after,index,strict=True,attributes_only=True)
            old=inspect_batch_lock(before,'batch_enhancement',index,True)['locked']
            new=inspect_batch_lock(after,'batch_enhancement',index,True)['locked']
            if old is None or new is None or (index==target and (old is not False or new is not True)) or (index!=target and new!=old):
                raise ValueError('上锁期间目标锁未确认或其他锁状态变化')
        return
    a=np.asarray(before.convert('RGB').resize((1661,933))).astype(float)
    b=np.asarray(after.convert('RGB').resize((1661,933))).astype(float)
    for index in range(count):
        dx,dy=batch_offset(index)
        # 排除卡片轮廓动画，保留装备图案、主副属性、分数与等级未遮挡部分。
        diff=np.abs(a[180+dy:315+dy,34+dx:325+dx]-b[180+dy:315+dy,34+dx:325+dx])
        mask=np.ones(diff.shape[:2],dtype=bool)
        if index==target:
            mask[:33,240:]=False  # 右上角锁按钮。
            mask[:18,:18]=False  # 左上角新增锁标遮住等级的部分。
        values=diff[mask]
        if float(values.mean())>3 or float((values>24).mean())>.01:
            raise ValueError('上锁期间装备内容或其他卡片发生变化')


def matches_locked_level(image,anchor,index):
    """比较本批已独立核验入口或锁动作后的等级图块，不从遮挡字形猜等级。"""
    dx,dy=batch_offset(index)
    box=(34+dx,182+dy,68+dx,210+dy)
    a=np.asarray(image.convert('RGB').resize((1661,933)).crop(box)).astype(float)
    with Image.open(anchor) as source:
        if source.size!=image.size:
            return False
        b=np.asarray(source.convert('RGB').resize((1661,933)).crop(box)).astype(float)
    return float(np.abs(a-b).mean())<=1 and float((np.abs(a-b)>8).mean())<=.005
