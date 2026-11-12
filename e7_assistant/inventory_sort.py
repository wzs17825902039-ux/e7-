"""按用户标定的最大强化升序选装；不改变筛选条件。"""
from pathlib import Path

import numpy as np
from PIL import Image


def ascending_selected(source):
    with Image.open(source) as image,Image.open(Path(__file__).with_name('assets')/
            'inventory-sort/max-enhancement-ascending.png') as template:
        if image.size!=(1280,720):
            raise ValueError('排序图形仅标定1280×720')
        a=np.asarray(image.convert('RGB').crop((914,157,978,191)),dtype=float)
        b=np.asarray(template.convert('RGB'),dtype=float)
    return bool(np.abs(a-b).mean()<=4 and np.corrcoef(a.ravel(),b.ravel())[0,1]>=.99)


def ensure_ascending(navigator):
    screen=navigator.read()
    if screen.page!='inventory':
        raise ValueError('排序须从普通背包开始')
    # 排序图标可能与文字合并成“Y最大强化”，拉低整词置信度。
    # 普通背包已确认后按标定位置打开，再以菜单文字和箭头验证排序。

    def tap(action,point):
        if navigator.journal:
            navigator.journal.emit('inventory_sort_intent',action=action,x=point[0],y=point[1],image=screen.source)
        navigator.adb.tap(*point)
        navigator.control.wait(.3)
        return navigator.read()

    # 文本中心在部分背包状态不响应，实机按钮右侧内部950/107稳定打开。
    screen=tap('open',(950,107))
    for attempt in range(3):
        try:
            screen.find('显示内容',(275,145,400,200),.95)
            break
        except ValueError:
            if attempt==2:raise
            navigator.control.wait(.2)
            screen=navigator.read()
    word=screen.find('最大强化',(715,150,890,195),.95)
    if not ascending_selected(screen.source):
        screen=tap('ascending',(930,173))
        screen.find('最大强化',(715,150,890,195),.95)
        if not ascending_selected(screen.source):
            raise ValueError('最大强化升序箭头未确认，不按未知顺序选装')
    screen=tap('close',(1045,110))
    if screen.page!='inventory':
        raise ValueError('关闭排序后未回到背包')
    if navigator.journal:
        navigator.journal.emit('inventory_sort_verified',order='max_enhancement_ascending',image=screen.source)
    return screen
