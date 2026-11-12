"""已勾选+3徽标的图形复核；模板由同帧右侧独立+3及选中前OCR交叉标注。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image,ImageEnhance


def inspect_numbered_inventory_badge(source,box):
    from .batch_badge_vision import read_numbered_badge
    with Image.open(source) as image:
        if image.size!=(1280,720) or box[2]-box[0]!=40 or box[3]-box[1]<27:
            return None
        crop=(box[0],box[1],box[2],box[1]+27)
        proof=read_numbered_badge(image.crop(crop))
        if proof is None:
            expanded=(crop[0]-8,crop[1]-8,crop[2]+8,crop[3]+8)
            proof=_read_detected_badge(image.convert('RGB').crop(expanded).tobytes())
    return ({'accepted':True,'enhancement':proof['value'],'method':'orange_plate_numbered_badge',
             'source':str(source),'crop':crop,'proof':proof} if proof else None)


@lru_cache(maxsize=128)
def _read_detected_badge(pixels):
    """武器白色图案干扰字形分割时，仅检测徽标及其8像素边距。"""
    import re
    from .local_ocr import _engine
    image=Image.frombytes('RGB',(56,43),pixels)
    original=image
    for gain in (1,2,2.5):
        image=ImageEnhance.Brightness(original).enhance(gain)
        plate=np.asarray(image.crop((8,8,48,35)),dtype=float)
        orange=((plate[:,:,0]>160)&(plate[:,:,1]>65)&(plate[:,:,1]<180)
                &(plate[:,:,2]<85)&(plate[:,:,0]>plate[:,:,1]*1.2)).astype('uint8')
        _,_,stats,_=cv2.connectedComponentsWithStats(orange,connectivity=8)
        if any(s[cv2.CC_STAT_AREA]>=100 and s[cv2.CC_STAT_TOP]<13 for s in stats[1:]):
            break
    else:
        return None
    candidates=[]
    for scale in (2,3):
        enlarged=image.resize((56*scale,43*scale),Image.Resampling.LANCZOS)
        result,_=_engine()(np.asarray(enlarged)[:,:,::-1].copy(),use_cls=False)
        matches=[]
        for polygon,text,confidence in result or []:
            if confidence<.95 or not re.fullmatch(r'\+([1-9]|1[0-5])',text):
                continue
            xs=[p[0]/scale for p in polygon];ys=[p[1]/scale for p in polygon]
            if min(xs)>=7 and max(xs)<=49 and min(ys)>=7 and max(ys)<=36:
                matches.append({'text':text,'confidence':float(confidence),'scale':scale})
        if len(matches)!=1:
            return None
        candidates.append(matches[0])
    if candidates[0]['text']!=candidates[1]['text']:
        return None
    return {'value':int(candidates[0]['text'][1:]),'source':'orange_plate_detected_glyph','brightness_gain':gain,
            'candidates':candidates}


@lru_cache(maxsize=1)
def _template():
    with Image.open(Path(__file__).with_name('assets')/'inventory-badges/selected-3.png') as image:
        return np.asarray(image.convert('RGB')).copy()


def inspect_selected_three(source,box):
    with Image.open(source) as image:
        if image.size!=(1280,720):
            return {'accepted':False,'reason':'未标定分辨率'}
        patch=np.asarray(ImageEnhance.Brightness(image.convert('RGB').crop(box)).enhance(2.5))
    template=_template()
    if patch.shape[0]<template.shape[0] or patch.shape[1]<template.shape[1]:
        return {'accepted':False,'reason':'裁切不足'}
    _,score,_,offset=cv2.minMaxLoc(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED))
    x,y=offset
    matched=patch[y:y+template.shape[0],x:x+template.shape[1]]
    error=float(np.abs(matched.astype(float)-template.astype(float)).mean())
    accepted=bool(np.isfinite(score) and score>=.995 and error<=5)
    return {'accepted':accepted,'enhancement':3 if accepted else None,'score':score,'pixel_error':error,
            'method':'selected_badge_template','source':str(source),'crop':box,'offset':offset}
