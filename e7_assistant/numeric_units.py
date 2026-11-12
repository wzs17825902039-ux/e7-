"""先确认百分号图形，再独立识别左侧数字；只恢复完整读数被拒绝的区域。"""
from functools import lru_cache
from pathlib import Path
import re
import cv2
import numpy as np
from PIL import Image


@lru_cache(maxsize=1)
def _percent_template():
    with Image.open(Path(__file__).with_name('assets')/'numeric-units/percent.png') as image:
        return np.asarray(image.convert('L')).copy()


@lru_cache(maxsize=1)
def _percent_templates():
    templates=[_percent_template()]
    # 原生列表的亚像素绘制会改变百分号抗锯齿；增加实际截图标定的
    # 完整字形模板，保留0.92阈值及独立数字的至少两票确认。
    for name in ('percent-selected.png','percent-subpixel.png'):
        with Image.open(Path(__file__).with_name('assets')/'numeric-units'/name) as image:
            templates.append(np.asarray(image.convert('L')).copy())
    return tuple(templates)


def read_percent_value(path,box):
    from .local_ocr import read_local_regions
    with Image.open(path) as image:
        if image.size!=(1280,720):return None
        x1,y1,x2,y2=box
        expanded=(max(0,x1-3),y1,x2,y2)
        pixels=np.asarray(image.convert('RGB').crop(expanded))
    neutral=pixels.max(2).astype(int)-pixels.min(2)<35
    mask=(neutral & (pixels.mean(2)>100)).astype('uint8')*255
    candidates=[]
    for template in _percent_templates():
        if any(a<b for a,b in zip(mask.shape,template.shape)):continue
        scores=cv2.matchTemplate(mask,template,cv2.TM_CCOEFF_NORMED)
        _,score,_,(x,y)=cv2.minMaxLoc(scores)
        if score>=.92 and x>=3:candidates.append((score,x,y,template,scores))
    if not candidates:return None
    score,x,y,template,scores=max(candidates,key=lambda item:item[0])
    # 单位必须是最后的完整前景；第二个分离的高匹配也拒绝。
    ys,xs=np.where(mask>0)
    if not len(xs) or abs(int(xs.max())-(x+template.shape[1]-1))>1:return None
    candidates=np.where(scores>=.92)
    if any(abs(int(cx)-x)>2 for cx in candidates[1]):return None
    number_box=(expanded[0],y1,expanded[0]+x,y2)
    values,details=read_local_regions(path,{'value':number_box})
    evidence=details['value'];value=values['value']
    if not re.fullmatch(r'\d+',value) or not evidence.get('accepted'):return None
    votes=[c for c in evidence.get('candidates',[]) if c['text']==value and c['confidence']>=.9]
    if len(votes)<2:return None
    return {'text':value+'%','confidence':min(c['confidence'] for c in votes),
            'accepted':True,'percent_match':float(score),'number_box':number_box,
            'numeric_evidence':evidence,'method':'percent_icon_then_numeric_ocr'}
