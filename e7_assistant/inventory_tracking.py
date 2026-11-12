"""跨滚动的完整卡片配准；与同位置点击校验使用独立图形证据。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@lru_cache(maxsize=4)
def _pixels(source,size,modified):
    with Image.open(source) as image:
        if image.size!=(1280,720):
            raise ValueError('跨滚动卡片配准只标定1280×720画面')
        # 红/紫光效随时间流动；G通道保留金色套装图标和白色数值，抑制彩色光效。
        pixels=np.asarray(image.convert('RGB')).astype(np.float32)
        foreground=np.maximum(pixels[:,:,1]-60,0)
        # 1.2像素低通抑制亚像素滚动的采样差异；标定见tracking-calibration.json。
        return cv2.GaussianBlur(foreground,(0,0),1.2)


def _read(source):
    path=Path(source)
    stat=path.stat()
    return _pixels(str(path),stat.st_size,stat.st_mtime_ns)


def inspect_tracking(before,after,search_margin=3):
    result={'matched':False,'score':None,'mae':None}
    if type(search_margin) is not int or search_margin not in (3,6):
        raise ValueError('卡片配准仅支持已标定的3或6像素搜索范围')
    if not before.get('tracking_source') or not after.get('tracking_source'):
        return result
    a,b=before.get('tracking_box'),after.get('tracking_box')
    if (not a or not b or len(a)!=4 or len(b)!=4
            or any(type(v) is not int for v in (*a,*b))
            or (a[2]-a[0],a[3]-a[1])!=(73,98)
            or (b[2]-b[0],b[3]-b[1])!=(73,98)):
        return result
    if not (0<=a[0]<a[2]<=1280 and 0<=a[1]<a[3]<=720
            and search_margin<=b[0]<b[2]<=1280-search_margin
            and search_margin<=b[1]<b[3]<=720-search_margin):
        return result
    old,new=_read(before['tracking_source']),_read(after['tracking_source'])
    template=old[a[1]:a[3],a[0]:a[2]]
    search=new[b[1]-search_margin:b[3]+search_margin,b[0]-search_margin:b[2]+search_margin]
    if float(template.std())<8 or float(search.std())<8:
        return result
    # 游戏以非整数坐标绘制滚动内容；四倍插值允许四分之一像素平移配准。
    template=cv2.resize(template,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
    search=cv2.resize(search,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
    _,score,_,offset=cv2.minMaxLoc(cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED))
    x,y=offset
    best=search[y:y+392,x:x+292]
    error=float(np.abs(best.astype(float)-template.astype(float)).mean())
    return {'matched':bool(np.isfinite(score) and score>=.995 and error<=5),
            'score':score,'mae':error,'offset':(x/4-search_margin,y/4-search_margin)}
