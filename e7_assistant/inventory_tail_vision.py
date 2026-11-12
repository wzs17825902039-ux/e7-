"""固定背包末行的装备/空格/未知与滚动条底端证据。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@lru_cache(maxsize=16)
def _template(name):
    with Image.open(Path(__file__).with_name('assets')/'inventory-tail'/(name+'.png')) as image:
        return np.asarray(image.convert('RGB')).copy()


def _match(pixels, template):
    a,b = pixels.astype(float),template.astype(float)
    error = float(np.abs(a-b).mean())
    score = float(cv2.matchTemplate(cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY),
                                   cv2.cvtColor(template,cv2.COLOR_RGB2GRAY),
                                   cv2.TM_CCOEFF_NORMED)[0,0])
    return error,score


def _short_tail(image):
    # 三行以内的短列表没有底部滚动条，末行也不在固定600px处。
    # 只支持有独立实机标定的第三行；不从未检测到卡片推断空白。
    for name,box in (('short-bottom',(146,544,816,710)),):
        x1,y1,x2,y2=box
        error,score=_match(image[y1:y2,x1:x2],_template(name))
        if error>3 or not np.isfinite(score) or score<.95:return None
    edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),25,65)>0
    cells=[]
    for column in range(7):
        x=145+99*column
        occupied=any(all(r>=.9 for r in (
            edges[y-3:y+5,x+5:x+81].any(axis=0).mean(),
            edges[y+106:y+116,x+5:x+81].any(axis=0).mean(),
            edges[y+10:y+101,x-3:x+6].any(axis=1).mean(),
            edges[y+10:y+101,x+81:x+94].any(axis=1).mean())) for y in range(417,424))
        empty=False
        if column:
            left=146+99*column
            error,score=_match(image[419:534,left:min(left+83,816)],_template(f'short-empty-{column}'))
            empty=error<=3 and np.isfinite(score) and score>=.95
        cells.append({'column':column,'state':'occupied' if occupied and not empty else
                      'empty' if empty and not occupied else 'unknown'})
    count=next((n for n in range(1,8) if [c['state'] for c in cells]==['occupied']*n+['empty']*(7-n)),None)
    if count is None:return None
    return {'end_verified':True,'tail_count':count,'cells':cells,'row_top':419,
            'method':'calibrated_short_third_row','notice':'下方完整空背景及末行连续占用均已核验，不依赖滚动条显隐'}


def _compact_tail(image):
    background=_template('compact-background')
    edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),25,65)>0
    contours,_=cv2.findContours(edges.astype(np.uint8)*255,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    candidates=sorted({y for contour in contours for x,y,w,h in [cv2.boundingRect(contour)]
                       if abs(x-145)<=4 and 82<=w<=94 and 108<=h<=116
                       and (147<=y<=170 or 280<=y<=305)},reverse=True)
    for y in candidates:
        lower=y+125
        error,score=_match(image[lower:710,146:816],background[lower-145:])
        if error>3 or not np.isfinite(score) or score<.95:continue
        cells=[]
        for column in range(7):
            x=145+99*column
            occupied=all(r>=.9 for r in (
                edges[y-3:y+5,x+5:x+81].any(axis=0).mean(),
                edges[y+106:y+116,x+5:x+81].any(axis=0).mean(),
                edges[y+10:y+101,x-3:x+6].any(axis=1).mean(),
                edges[y+10:y+101,x+81:x+94].any(axis=1).mean()))
            empty=False
            if column:
                left=99*column;right=min(left+83,670)
                error,score=_match(image[y:y+115,146+left:146+right],background[y-145:y-30,left:right])
                empty=error<=3 and np.isfinite(score) and score>=.95
            cells.append({'column':column,'state':'occupied' if occupied and not empty else
                          'empty' if empty and not occupied else 'unknown'})
        count=next((n for n in range(1,8) if [c['state'] for c in cells]==['occupied']*n+['empty']*(7-n)),None)
        if count is not None:
            return {'end_verified':True,'tail_count':count,'cells':cells,'row_top':y,
                    'method':'calibrated_compact_list','notice':'短列表末行及下方完整空背景已核验'}
    return None


def inspect_tail(screen):
    if screen.page not in {'inventory_batch_selection','inventory_batch_selection_empty'}:
        raise ValueError('尾行识别仅支持已确认的批量选择页')
    with Image.open(screen.source) as source:
        if source.size != (1280,720):
            return {'end_verified':False,'tail_count':None,'cells':[],
                    'notice':'末行背景模板尚未标定其他分辨率'}
        image = np.asarray(source.convert('RGB'))
    error,score = _match(image[698:712,818:830],_template('bottom-cap'))
    bottom = error <= 3 and np.isfinite(score) and score >= .95
    cells = []
    for col in range(7):
        x = 146+99*col
        patch = image[600:710,x:min(x+83,816)]
        empty_error,empty_score = (None,None) if col == 0 else _match(patch,_template(f'empty-{col}'))
        # 空背景匹配有绝对像素差门槛，不由OCR空读或未找到装备推断空格。
        empty = col > 0 and empty_error <= 3 and np.isfinite(empty_score) and empty_score >= .95
        glyph = image[601:628,x:x+34].astype(float)
        r,g,b = (glyph[:,:,i] for i in range(3))
        yellow = int(((r>140)&(g>100)&(b<120)&(r>g*.9)).sum())
        body = patch.astype(float)
        r,g,b = (body[:,:,i] for i in range(3))
        color = float(((r>40)&(r>g*1.6)&((r>b*2)|(b>g*1.5))).mean())
        occupied = yellow >= 15 and color >= .06
        state = 'empty' if empty and not occupied else 'occupied' if occupied and not empty else 'unknown'
        cells.append({'column':col,'state':state,'background_mae':empty_error,
                      'background_match':empty_score,'level_pixels':yellow,'color_ratio':color})
    count = next((n for n in range(1,8)
                  if [c['state'] for c in cells] == ['occupied']*n+['empty']*(7-n)),None)
    if not bottom or count is None:
        short=_compact_tail(image) or _short_tail(image)
        if short is not None:return short
    return {'end_verified':bool(bottom),'tail_count':count,'cells':cells,
            'bottom_cap_mae':error,'bottom_cap_match':score,
            'notice':'底端证据不等于已从顶部扫描；末行装备仍须逐件读取等级和属性'}
