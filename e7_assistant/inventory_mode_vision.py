"""批量选择零勾选布局：以分类页签图形和明确空详情交叉确认。"""
from functools import lru_cache
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image


@lru_cache(maxsize=1)
def _all_tab():
    with Image.open(Path(__file__).with_name('assets')/'inventory-mode/all-tab.png') as image:
        return np.asarray(image.convert('L'))


def inspect_zero_selection(source, words):
    """不从数值OCR空读填0；仅确认已标定的零选择布局。"""
    def unique(label, region):
        found = [word for word in words if word['text'] == label
                 and word['confidence'] >= .95
                 and region[0] <= word['center'][0] < region[2]
                 and region[1] <= word['center'][1] < region[3]]
        return len(found) == 1
    if not (unique('背包',(40,10,150,60))
            and unique('取消',(1100,70,1270,140))
            and unique('未选择道具。',(920,400,1200,490))):
        raise ValueError('未确认批量零选择页的背包、取消和空详情文案')
    if any(word['text'] in {'快速选择','清空','整理','萃取','出售','管理'}
           or re.fullmatch(r'批量强化\(\d+\)',word['text'])
           for word in words):
        raise ValueError('页面包含整理、其他管理模式或批量计数，不能按零选择布局处理')
    with Image.open(source) as image:
        if abs(image.width/image.height-16/9) > .02:
            raise ValueError('零选择布局需要完整16:9截图')
        reference = image.convert('RGB').resize((1280,720))
    tab = np.asarray(reference.crop((143,90,231,145)).convert('L'))
    score = float(cv2.matchTemplate(tab,_all_tab(),cv2.TM_CCOEFF_NORMED).max())
    # 有勾选时出现的绿色批量按钮是反证；没有它本身不构成零选择证据。
    footer = np.asarray(reference.crop((1005,640,1220,710))).astype(float)
    r,g,b = (footer[:,:,i] for i in range(3))
    green = float(((g>r*1.2)&(g>b*1.2)&(g>35)).mean())
    if not np.isfinite(score) or score < .95 or green > .03:
        raise ValueError('分类页签或底栏图形与零选择布局不符')
    return {'selected_count':0,'all_tab_match':round(score,4),
            'footer_green_ratio':round(green,4),'empty_detail_confirmed':True}
