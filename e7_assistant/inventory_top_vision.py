"""顶部滚动条端点取证；回弹图像本身不构成已稳定的扫描起点。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@lru_cache(maxsize=1)
def _head_template():
    with Image.open(Path(__file__).with_name('assets')/'inventory-top/head-cap.png') as image:
        return np.asarray(image.convert('RGB')).copy()


def inspect_top(screen):
    from .inventory_vision import inventory_context
    result={'head_visible':False,'source':screen.source,'inventory_context':inventory_context(screen)}
    if screen.page not in {'inventory_batch_selection','inventory_batch_selection_empty'}:
        return result
    with Image.open(screen.source) as image:
        if image.size!=(1280,720):
            return result
        patch=np.asarray(image.convert('RGB').crop((818,156,830,172)))
    template=_head_template()
    error=float(np.abs(patch.astype(float)-template.astype(float)).mean())
    score=float(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED)[0,0])
    if not (np.isfinite(score) and score>=.95 and error<=3):
        from .inventory_tail_vision import inspect_tail
        tail=inspect_tail(screen)
        if (tail.get('method')=='calibrated_compact_list' and tail['end_verified']
                and 147<=tail['row_top']<=163):
            return {**result,'head_visible':True,'method':'calibrated_single_row_list'}
    return {**result,'head_visible':bool(np.isfinite(score) and score>=.95 and error<=3),
            'head_cap_match':score,'head_cap_mae':error}


def verify_top_anchor(anchor,report):
    from .inventory_scan import rows
    if (not anchor or anchor.get('method')!='visible_head_then_settled'
            or anchor.get('head_visible') is not True or not anchor.get('head_source')
            or anchor.get('stable_source')!=report['source']
            or not anchor.get('inventory_context')
            or tuple(anchor['inventory_context'])!=tuple(report.get('inventory_context',()))
            or report['selected_count']!=0):
        raise ValueError('顶部证据与本次稳定扫描起点不一致')
    first=rows(report)[0]
    tail=report.get('tail_layout',{})
    partial=(tail.get('method')=='calibrated_compact_list' and tail.get('end_verified') is True
             and tail.get('row')==0 and tail.get('tail_count')==len(first))
    if (len(first)!=7 and not partial) or any(abs(card['center'][1]-211)>2 for card in first):
        raise ValueError('顶部列表仍在回弹或首行位置未确认')
    return True


def context_pixels_equal(*sources):
    """瞬态OCR漏字时，仅允许三张上下文区域逐像素相同的截图互证。"""
    patches=[]
    for source in sources:
        with Image.open(source) as image:
            if image.size!=(1280,720):
                return False
            patches.append(np.asarray(image.convert('RGB').crop((840,80,1125,130))).copy())
    return len(patches)>=2 and all(np.array_equal(patches[0],p) for p in patches[1:])
