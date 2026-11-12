"""小型强化徽标：先确认橙色底板，再剥离背景、读取白色字形。"""
from functools import lru_cache
import re

from PIL import Image


def read_numbered_badge(image):
    rgb=image.convert('RGB')
    return _read_numbered_badge(rgb.size,rgb.tobytes())


@lru_cache(maxsize=256)
def _read_numbered_badge(size,pixels):
    import cv2
    import numpy as np
    from .local_ocr import _engine
    image=np.asarray(Image.frombytes('RGB',size,pixels),dtype=float)
    if size!=(40,27):
        return None
    # 不对装备背景或空白OCR猜数字。暗层只恢复亮度，不改变颜色比例。
    for gain in (1,2,2.5):
        restored=np.minimum(image*gain,255)
        r,g,b=restored.transpose(2,0,1)
        orange=((r>160)&(g>65)&(g<180)&(b<85)&(r>g*1.2)).astype('uint8')
        _,_,stats,_=cv2.connectedComponentsWithStats(orange,connectivity=8)
        if not any(s[cv2.CC_STAT_AREA]>=100 and s[cv2.CC_STAT_TOP]<13 for s in stats[1:]):
            continue
        white=(restored.min(axis=2)>.78*restored.max(axis=2))&(restored.min(axis=2)>150)
        # 排除底板外的白色装备图案和边框；保留加号与数字的完整字形。
        white[:3]=False;white[-5:]=False;white[:,:5]=False;white[:,-2:]=False
        ys,xs=np.where(white)
        if len(xs)<25:
            continue
        glyph=white[ys.min():ys.max()+1,xs.min():xs.max()+1]
        bitmap=Image.fromarray(np.uint8(~glyph)*255)
        candidates=[]
        for scale,padding in ((4,8),(6,16)):
            enlarged=np.asarray(bitmap.resize((bitmap.width*scale,bitmap.height*scale),Image.Resampling.LANCZOS))
            padded=cv2.copyMakeBorder(enlarged,padding,padding,padding,padding,
                                      cv2.BORDER_CONSTANT,value=255)
            result,_=_engine()(cv2.cvtColor(padded,cv2.COLOR_GRAY2BGR),use_det=False,use_cls=False)
            if not result or len(result)!=1:
                break
            text,confidence=result[0]
            if not re.fullmatch(r'\+([1-9]|1[0-5])',text) or confidence<.95:
                break
            candidates.append({'text':text,'confidence':float(confidence),'scale':scale})
        if len(candidates)==2 and candidates[0]['text']==candidates[1]['text']:
            return {'value':int(candidates[0]['text'][1:]),'source':'orange_plate_white_glyph',
                    'brightness_gain':gain,'candidates':candidates}
        # 低分辨率下加号和6可能连成一块，被整段OCR读成+b6。
        # 先独立确认加号形状，再对两个相邻裁框、两种尺度的纯数字取一致结果。
        split=_read_split_digits(white)
        if not split:
            # 保留抗锯齿灰阶，避免二值化损坏6的细颈；仍独立验证加号及四次高置信读数。
            intensity=np.clip((restored.min(axis=2)-40)/180*255,0,255)
            split=_read_split_digits(white,intensity)
        if split:
            return {**split,'brightness_gain':gain}
    return None


def _read_split_digits(white,intensity=None):
    import cv2
    import numpy as np
    from .local_ocr import _engine
    choices=[]
    for cut in range(12,25):
        left=white[:,:cut]
        ys,xs=np.where(left)
        if not len(xs):continue
        glyph=left[ys.min():ys.max()+1,xs.min():xs.max()+1]
        height,width=glyph.shape
        if not (7<=height<=14 and 7<=width<=14 and .65<=width/height<=1.4):continue
        yy,xx=np.indices(glyph.shape);cy,cx=(np.array(glyph.shape)-1)/2
        score=0.
        for thickness in (.22,.3,.38,.46):
            # 低分辨率十字中心可能落在相邻半像素；校准位置，不降低匹配阈值。
            for shift_x in (-.5,0,.5):
                for shift_y in (-.5,0,.5):
                    cross=(abs(xx-cx-shift_x)<=width*thickness/2)|(abs(yy-cy-shift_y)<=height*thickness/2)
                    score=max(score,float((cross&glyph).sum()/max(1,(cross|glyph).sum())))
        if score>=.8:choices.append((score,cut))
    if not choices:return None
    for score,cut in sorted(choices,reverse=True):
        candidates=[]
        for scale in (4,6,5,8):
            pair=[]
            for start in (cut,cut+1):
                bitmap=(Image.fromarray(np.uint8(~white[4:-5,start:32])*255) if intensity is None else
                        Image.fromarray(np.uint8(255-intensity[4:-5,start:32])))
                if bitmap.width<3:break
                enlarged=np.asarray(bitmap.resize((bitmap.width*scale,bitmap.height*scale),Image.Resampling.LANCZOS))
                padded=cv2.copyMakeBorder(enlarged,16,16,16,16,cv2.BORDER_CONSTANT,value=255)
                result,_=_engine()(cv2.cvtColor(padded,cv2.COLOR_GRAY2BGR),use_det=False,use_cls=False)
                if not result or len(result)!=1:break
                text,confidence=result[0]
                if not re.fullmatch(r'([1-9]|1[0-5])',text) or confidence<.95:break
                pair.append({'text':text,'confidence':float(confidence),'scale':scale,'start':start})
            if len(pair)==2:
                candidates.extend(pair)
                if len({c['text'] for c in candidates})!=1:return None
                if len(candidates)==4:
                    return {'value':int(candidates[0]['text']),'source':'orange_plate_split_digits',
                            'plus_match':score,'candidates':candidates}
    return None
