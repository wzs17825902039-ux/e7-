"""固定批量面板的占用 / 空槽 / 未知证据；匹配分数不是概率。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def _edges(image):
    gray = np.asarray(image.convert('L'))
    return np.stack((cv2.Sobel(gray, cv2.CV_32F, 1, 0),
                     cv2.Sobel(gray, cv2.CV_32F, 0, 1)), axis=-1)


@lru_cache(maxsize=1)
def _empty_template():
    with Image.open(Path(__file__).with_name('assets') / 'batch-slots/empty-watermark.png') as image:
        return _edges(image)[5:-5, 5:-5].copy()


@lru_cache(maxsize=1)
def _sold_template():
    with Image.open(Path(__file__).with_name('assets')/'batch-slots/sold-watermark.png') as image:
        return _edges(image)[5:-5,5:-5].copy()


def boosted_indices(items):
    return {i for i,item in enumerate(items) if item.equipment.enhancement_bonus}


@lru_cache(maxsize=256)
def _locked_stat_score(size,pixels):
    from .batch_vision import _vector
    patch=Image.frombytes('RGB',size,pixels)
    with Image.open(Path(__file__).with_name('assets')/'stat-icons/locked-stat-row.png') as template:
        expected=np.asarray(_vector(template))
    return float(np.dot(_vector(patch),expected))


def inspect_slots(reference,boosted_red_indices=(),registered_rarities=None,initial_indices=()):
    """输入1661×933标准图；空槽必须匹配水印，不能由OCR缺失推断。"""
    if reference.size != (1661, 933):
        raise ValueError('槽位识别需要标准尺寸画面')
    boosted=set(boosted_red_indices)
    if any(type(i) is not int or not 0<=i<16 for i in boosted):raise ValueError('强化加成红装位置无效')
    registered=dict(registered_rarities or {})
    if any(type(i) is not int or not 0<=i<16 or rarity not in ('red','purple')
           for i,rarity in registered.items()):raise ValueError('已登记批次品质无效')
    if any(i in registered and registered[i]!='red' for i in boosted):
        raise ValueError('强化加成登记与红装品质不符')
    initial=set(initial_indices)
    if any(type(i) is not int or i not in registered for i in initial):
        raise ValueError('初始词条计数缺少已确认的+0槽位登记')
    from .batch_vision import _rarity
    result = []
    for index in range(16):
        row, column = divmod(index, 4)
        x, y = 20 + round(column * 316.667), 166 + round(row * 167.333)
        roi = reference.crop((x + 90, y + 24, x + 215, y + 146))
        score = float(cv2.matchTemplate(_edges(roi), _empty_template(),
                                        cv2.TM_CCOEFF_NORMED).max())
        sold_score=float(cv2.matchTemplate(_edges(roi),_sold_template(),cv2.TM_CCOEFF_NORMED).max())
        if index in registered:
            # 正式批次的品质已由入口标题确认。只核对属性区域仍有装备，
            # 不再根据会流动/变色的装备大图或外框重复猜红紫品质。
            from .batch_vision import match_icon
            visible=[]
            fourth_confidence=0.
            dx,dy=x-20,y-166
            for stat_row in range(4):
                try:
                    _,confidence=match_icon(reference.crop((144+dx,212+dy+stat_row*28,
                                                           174+dx,237+dy+stat_row*28)))
                    visible.append(stat_row)
                    if stat_row==3:fourth_confidence=confidence
                except ValueError:
                    pass
            if index in initial:
                # 仅用于独立确认尚未强化的+0装备；+12紫装的四词条不能改判红装。
                fourth=reference.crop((144+dx,296+dy,174+dx,321+dy)).convert('RGB')
                locked_score=_locked_stat_score(fourth.size,fourth.tobytes())
                rarity=None
                if visible[:3]==[0,1,2]:
                    if locked_score>=.9 and locked_score>=fourth_confidence+.04:
                        rarity='purple'
                    elif 3 in visible and fourth_confidence>=locked_score+.04:
                        rarity='red'
                if rarity is not None and rarity!=registered[index]:
                    raise ValueError('初始副词条数量与已登记品质不符')
            else:
                rarity=registered[index] if len(visible)>=3 else None
        else:
            try:
                rarity = _rarity(reference, x, y)
            except ValueError:
                rarity = None
        if index in boosted and index not in registered:
            # 仅使用入口标题已确认或同批已登记的类型，不从紫色外圈推断品质。
            patch=np.asarray(reference.crop((x+18,y+15,x+100,y+106))).astype(float)
            r,g,b=(patch[:,:,channel] for channel in range(3))
            purple=((r>55)&(r>g*1.5)&(b>g*1.3)).mean()
            red=((r>65)&(r>g*1.6)&(r>b*1.6)).mean()
            rarity='red' if rarity=='red' or purple>.15 and red>.10 else None
        level = np.asarray(reference.crop((x + 13, y + 16, x + 48, y + 44)))
        yellow = ((level[:, :, 0] > 140) & (level[:, :, 1] > 120)
                  & (level[:, :, 2] < 140)).sum()
        occupied = rarity is not None and (index in registered or yellow >= 10)
        empty = rarity is None and max(score,sold_score) >= .72
        state = 'occupied' if occupied and max(score,sold_score) < .72 else 'empty' if empty else 'unknown'
        result.append({'index': index, 'state': state, 'empty_match': round(score, 4),
                       'sold_match':round(sold_score,4),
                       'rarity': rarity, 'level_pixels': int(yellow)})
    return result
