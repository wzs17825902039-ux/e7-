"""选装固定坐标及已配准卡片的特征核验；不推断装备属性。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@lru_cache(maxsize=256)
def _features(source,box,size,modified):
    with Image.open(source) as image:
        if image.size!=(1280,720):raise ValueError('特征核验仅标定1280×720')
        patch=np.asarray(image.convert('L').crop(box))
    keypoints,descriptors=cv2.SIFT_create(nfeatures=160,contrastThreshold=.01).detectAndCompute(patch,None)
    return np.asarray([k.pt for k in keypoints],dtype=float),descriptors


def stationary_features(before,after):
    """相互最近邻、分布于图案与底部的至少12点，须共同证明零实际位移。"""
    return _matching_features(before,after,False)


def aligned_card_features(before,after):
    """各自裁框内的零位移特征；调用方必须独立证明跨行对应与配准。"""
    return _matching_features(before,after,True)


def _matching_features(before,after,relative):
    result={'matched':False}
    box=before.get('tracking_box')
    if (not box or len(box)!=4 or any(type(v) is not int for v in box)
            or (box[2]-box[0],box[3]-box[1])!=(73,98)
            or not 0<=box[0]<box[2]<=1280 or not 0<=box[1]<box[3]<=720):return result
    features=[]
    try:
        for card in (before,after):
            crop=card.get('tracking_box') if relative else box
            if (not crop or len(crop)!=4 or any(type(v) is not int for v in crop)
                    or (crop[2]-crop[0],crop[3]-crop[1])!=(73,98)
                    or not 0<=crop[0]<crop[2]<=1280 or not 0<=crop[1]<crop[3]<=720):return result
            path=Path(card['tracking_source']);stat=path.stat()
            features.append(_features(str(path.resolve()),tuple(crop),stat.st_size,stat.st_mtime_ns))
    except (OSError,ValueError,KeyError):return result
    (a,da),(b,db)=features
    if da is None or db is None or len(da)<12 or len(db)<12:return result
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    def matches(x,y):
        return {pair[0].queryIdx:pair[0].trainIdx for pair in matcher.knnMatch(x,y,k=2)
                if len(pair)==2 and pair[0].distance<.7*pair[1].distance}
    forward,reverse=matches(da,db),matches(db,da)
    pairs=[];seen=set()
    for i,j in forward.items():
        if reverse.get(j)!=i:continue
        location=tuple(np.round(a[i]*2).astype(int))
        if location in seen:continue
        seen.add(location);pairs.append((i,j))
    if len(pairs)<12:return result
    old=np.asarray([a[i] for i,j in pairs]);new=np.asarray([b[j] for i,j in pairs])
    delta=new-old
    stable=np.max(np.abs(delta),axis=1)<=.5
    if stable.sum()<12:return result
    points=old[stable];median=np.median(delta[stable],axis=0);span=np.ptp(points,axis=0)
    result.update(matches=len(pairs),stationary=int(stable.sum()),ratio=float(stable.mean()),
                  median_offset=median.tolist(),span=span.tolist())
    result['matched']=bool(stable.mean()>=.9 and np.max(np.abs(median))<=.25
                           and span[0]>=35 and span[1]>=50
                           and (points[:,1]<33).sum()>=2 and (points[:,1]>65).sum()>=2)
    return result
