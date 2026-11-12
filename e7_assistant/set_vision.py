"""使用工坊实机套装图标作模板；只在自定义筛选开启时调用。"""
from functools import lru_cache
from pathlib import Path

from PIL import Image

from .custom_targets import SET_GROUPS


def _gold(image):
    import numpy as np
    rgb=np.asarray(image.convert('RGB'),dtype=float)
    # 保留金色图案，去掉红/蓝底色和装备品质边框。
    gold=np.maximum(0,np.minimum(rgb[:,:,0],rgb[:,:,1])-rgb[:,:,2])
    return gold.astype('float32')


@lru_cache(maxsize=1)
def _templates():
    result={}
    for source,group in enumerate(SET_GROUPS):
        with Image.open(Path(__file__).with_name('assets')/'forge-sources'/f'source-{source}-sets.png') as im:
            for index,name in enumerate(group):
                x=round(index*34.7)
                result[name]=im.crop((x+2,2,x+31,35)).convert('RGB')
    return result


def inspect_batch_sets(path, indices):
    import cv2
    result={}
    with Image.open(path) as im:
        reference=im.convert('RGB').resize((1280,720))
    for index in indices:
        if type(index) is not int or not 0<=index<16:
            raise ValueError('套装识别槽位应为0～15')
        dx=round(index%4*244.03);dy=round(index//4*129.13)
        scores={name:0. for name in _templates()}
        patch=_gold(reference.crop((70+dx,177+dy,115+dx,227+dy)))
        if patch.max()-patch.min()<5:
            result[index]={'set':None,'score':0.,'margin':0.,'candidate':None}
            continue
        for name,template in _templates().items():
            for width in range(26,34):
                scaled=_gold(template.resize((width,round(width*33/29))))
                score=float(cv2.minMaxLoc(cv2.matchTemplate(patch,scaled,cv2.TM_CCOEFF_NORMED))[1])
                scores[name]=max(scores[name],score)
        ranked=sorted(scores.items(),key=lambda pair:pair[1],reverse=True)
        name,score=ranked[0];margin=score-ranked[1][1]
        result[index]={'set':name if score>=.88 and margin>=.06 else None,
                       'score':round(score,4),'margin':round(margin,4),'candidate':name}
    return result
