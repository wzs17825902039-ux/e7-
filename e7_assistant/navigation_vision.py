"""只识别左上角明亮的返回箭头；不以坐标存在推定按钮存在。"""
from functools import lru_cache


def _shape(mask):
    import cv2
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    if count<2:return None
    index=1+stats[1:,4].argmax()
    x,y,w,h,area=map(int,stats[index])
    if area<20 or not .45<=w/h<=1.1:return None
    return cv2.resize((labels[y:y+h,x:x+w]==index).astype('uint8'),(40,48),interpolation=cv2.INTER_NEAREST)


@lru_cache(maxsize=1)
def _reference():
    import cv2
    import numpy as np
    from PIL import Image
    from .runtime_paths import resource_root
    with Image.open(resource_root()/'e7_assistant/assets/navigation/back-arrow-reference.png') as image:
        pixels=np.asarray(image.convert('RGB'))
    return _shape((pixels.min(axis=2)>150).astype('uint8'))


def has_back_arrow(path):
    import numpy as np
    from PIL import Image
    with Image.open(path) as image:
        if image.size!=(1280,720):return False
        pixels=np.asarray(image.convert('RGB'))[6:58,8:61]
    # 排除暗化遮罩和彩色图标，只允许白/浅米色的箭头轮廓。
    values=pixels.astype(int)
    mask=((values.min(axis=2)>160)&(values.max(axis=2)-values.min(axis=2)<65)).astype('uint8')
    shape=_shape(mask)
    reference=_reference()
    if shape is None or reference is None:return False
    intersection=np.logical_and(shape,reference).sum()
    union=np.logical_or(shape,reference).sum()
    return bool(union and intersection/union>=.84)
