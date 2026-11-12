"""完整打造链路的页面证据；识别结果不自行授权消耗操作。"""
from dataclasses import dataclass
from pathlib import Path
import re

from .vision import normalize


@dataclass(frozen=True)
class Screen:
    source: str
    page: str
    width: int
    height: int
    words: tuple

    def find(self, label, region=None, minimum_confidence=.9):
        """精确匹配文字及可选位置；重复按钮不得任取其一。"""
        matches = []
        for word in self.words:
            x, y = word['center']
            if (word['text'] == normalize(label) and word['confidence'] >= minimum_confidence
                    and (region is None or region[0] <= x < region[2] and region[1] <= y < region[3])):
                matches.append(word)
        if len(matches) != 1:
            raise ValueError(f'按钮{label!r}未唯一确认：{len(matches)}处')
        return matches[0]


def classify(words):
    texts = {w['text'] for w in words if w['confidence'] >= .85}
    def has(text):
        return normalize(text) in texts
    # 弹窗优先于底层页面，防止在背包满提示下继续点重新制作。
    if (has('整理说明') and has('包含+15强化装备。')
            and has('是否继续进行?') and has('确认') and has('取消') and has('不再显示')):
        return 'sale_level_warning'
    if (has('获得奖励') and has('点击关闭')
            and any(re.fullmatch(r'超过上限的经验值已作为强化粉[末未]返还[。.]?',text) for text in texts)):
        return 'enhancement_refund'
    if has('变更日期') and any('日期变更' in text and '前往大厅' in text for text in texts):
        return 'date_change'
    if has('联动签到奖励!') and (has('奖励已用邮件寄出')
            or has('签到奖励一天可获得一次。')
            and any(re.fullmatch(r'获得的奖励:\d+/\d+',text) for text in texts)):
        return 'attendance_reward'
    if has('辅助英雄友情点数抵达') and has('点击关闭'):
        return 'friendship_notice'
    if any('装备背包已满' in text for text in texts):
        return 'inventory_full'
    if has('制作传说装备') and has('取消') and has('制作'):
        return 'legendary_craft_confirmation'
    if has('萃取装备') and has('萃取'):
        return 'extract_confirmation'
    if has('出售装备') and has('出售'):
        return 'sale_confirmation'
    if (has('出售') and has('确认') and has('取消')
            and any(re.fullmatch(r'确定要出售选中的[1-9]\d*件道具[?？]',text) for text in texts)
            and any(w['text']=='出售' and w['confidence']>=.9
                    and 400<=w['center'][0]<880 and 140<=w['center'][1]<250 for w in words)):
        return 'sale_confirmation'
    if any(text in texts for text in ('金币不足','材料不足','网络连接中断','连接已断开')):
        return 'interruption'
    if any(re.fullmatch(r'制作装备(?:1|10)次', text) for text in texts) and has('制作'):
        return 'craft_confirmation'
    if has('制作完毕') and has('重新制作'):
        return 'craft_result'
    if has('制作完毕'):
        if all(has(label) for label in ('分享','锁定','出售','萃取')):
            return 'legendary_craft_result'
        # 顶栏裁图可见结果标题但不含浮层按钮时，要求完整复核。
        return 'unknown'
    if has('批量强化'):
        if has('自动选择') and has('出售'):
            return 'batch_organize'
        if (has('强化材料') or has('装备强化粉末')) and (has('全部解除') or has('全部选择')) and has('整理'):
            return 'batch_enhancement'
    if has('背包'):
        if has('取消') and has('清空') and any(re.fullmatch(r'批量强化\(\d+\)',text) for text in texts):
            return 'inventory_batch_selection'
        if has('快速选择'):
            return 'inventory_organize'
        if has('整理') and has('批量强化'):
            return 'inventory_manage'
        if has('管理'):
            return 'inventory'
        if (any(w['text']=='背包' and w['confidence']>=.9 and 65<=w['center'][0]<150
                and 10<=w['center'][1]<55 for w in words)
                and any(w['text']=='使用' and w['confidence']>=.9 and 1080<=w['center'][0]<1240
                        and 640<=w['center'][1]<715 for w in words)):
            return 'inventory_items'
    if has('钢铁工坊') and any('制作装备' in text for text in texts):
        return 'forge'
    if has('钢铁工坊') and has('宠物小屋') and has('好友'):
        return 'home_menu'
    if has('竞技场') and has('商店') and has('召唤') and has('战斗'):
        return 'home'
    return 'unknown'


def inspect_screen(path):
    from PIL import Image
    from .local_ocr import _engine
    source = Path(path)
    with Image.open(source) as image:
        width, height = image.size
    if abs(width/height-16/9) > .02:
        raise ValueError('流程识别需要完整16:9截图，拒绝裁剪图')
    detections, _ = _engine()(str(source), use_cls=False)
    words = []
    for polygon, text, confidence in detections or []:
        box = (min(p[0] for p in polygon)*1280/width, min(p[1] for p in polygon)*720/height,
               max(p[0] for p in polygon)*1280/width, max(p[1] for p in polygon)*720/height)
        words.append({'text':normalize(text), 'confidence':float(confidence), 'box':box,
                      'center':((box[0]+box[2])/2,(box[1]+box[3])/2)})
    page = classify(words)
    if page == 'unknown':
        from .inventory_mode_vision import inspect_zero_selection
        try:
            inspect_zero_selection(source,words)
        except ValueError:
            pass
        else:
            page = 'inventory_batch_selection_empty'
    if page=='unknown':
        from .navigation_vision import has_back_arrow
        if has_back_arrow(source):page='back_navigation'
    return Screen(str(source.resolve()), page, width, height, tuple(words))


def inspect_forge_screen(path):
    """打造等待只识别固定标题与按钮；其余页面走普通识别。"""
    import numpy as np
    from PIL import Image
    from .local_ocr import _engine
    source=Path(path)
    regions=((350,70,925,220),(350,490,925,710),(350,275,925,490))
    with Image.open(source) as image:
        width,height=image.size
        if (width,height)!=(1280,720):
            return inspect_screen(path)
        collage=Image.new('RGB',(575,609),(0,0,0))
        collage.paste(image.crop(regions[0]),(0,0))
        collage.paste(image.crop(regions[1]),(0,162))
        collage.paste(image.crop(regions[2]),(0,394))
    detections,_=_engine()(np.asarray(collage)[:,:,::-1].copy(),use_cls=False)
    words=[]
    for polygon,text,confidence in detections or []:
        left,top=min(p[0] for p in polygon),min(p[1] for p in polygon)
        right,bottom=max(p[0] for p in polygon),max(p[1] for p in polygon)
        if 0<=top<bottom<=150:
            offset_x,offset_y=350,70
        elif 162<=top<bottom<=382:
            offset_x,offset_y=350,490-162
        elif 394<=top<bottom<=609:
            offset_x,offset_y=350,275-394
        else:
            continue
        box=(left+offset_x,top+offset_y,right+offset_x,bottom+offset_y)
        words.append({'text':normalize(text),'confidence':float(confidence),'box':box,
                      'center':((box[0]+box[2])/2,(box[1]+box[3])/2)})
    page=classify(words)
    if page not in {'craft_confirmation','craft_result','inventory_full'}:
        return inspect_screen(path)
    return Screen(str(source.resolve()),page,width,height,tuple(words))


def inspect_navigation_screen(path,expected_pages):
    """操作导航只OCR标题、顶栏和按钮带；不送入装备列表。"""
    import numpy as np
    from PIL import Image
    from .local_ocr import _engine
    source=Path(path)
    header_pages={'inventory','inventory_organize','batch_enhancement','batch_organize','forge'}
    modal_pages={'craft_confirmation','extract_confirmation','sale_confirmation'}
    if set(expected_pages)<=header_pages:
        region=(0,0,1280,145)
    elif set(expected_pages)<=modal_pages:
        region=(350,140,925,580)
    else:
        return inspect_screen(path)
    with Image.open(source) as image:
        if image.size!=(1280,720):
            return inspect_screen(path)
        crop=image.crop(region)
    header=region==(0,0,1280,145)
    if header:
        # 检测模型按短边放大到736；直接送入细长顶栏反而会被大幅放大。
        # 将两半顶栏放进方形画布，只识别这些按钮，映射回原始坐标。
        packed=Image.new('RGB',(640,640),(0,0,0))
        packed.paste(crop.crop((0,0,640,145)),(0,0))
        packed.paste(crop.crop((640,0,1280,145)),(0,157))
        crop=packed
    detections,_=_engine()(np.asarray(crop)[:,:,::-1].copy(),use_cls=False)
    words=[]
    for polygon,text,confidence in detections or []:
        left,top=min(p[0] for p in polygon),min(p[1] for p in polygon)
        right,bottom=max(p[0] for p in polygon),max(p[1] for p in polygon)
        dx,dy=region[:2]
        if header:
            if 0<=top<bottom<=145:
                dx,dy=0,0
            elif 157<=top<bottom<=302:
                dx,dy=640,-157
            else:continue
        box=(left+dx,top+dy,right+dx,bottom+dy)
        words.append({'text':normalize(text),'confidence':float(confidence),'box':box,
                      'center':((box[0]+box[2])/2,(box[1]+box[3])/2)})
    page=classify(words)
    if page not in expected_pages:
        return inspect_screen(path)
    return Screen(str(source.resolve()),page,1280,720,tuple(words))


def inspect_batch_controls(path):
    """批量页读取控件及奖励标题带，异常页面回退完整识别。"""
    import numpy as np
    from PIL import Image
    from .local_ocr import _engine
    source=Path(path)
    regions=(((0,0,640,145),0),((640,0,1280,145),157),
             ((0,630,640,720),314),((640,630,1280,720),416),
             ((320,140,960,260),518))
    with Image.open(source) as image:
        if image.size!=(1280,720):return inspect_screen(path)
        packed=Image.new('RGB',(640,640),(0,0,0))
        for box,top in regions:packed.paste(image.crop(box),(0,top))
    detections,_=_engine()(np.asarray(packed)[:,:,::-1].copy(),use_cls=False)
    words=[]
    for polygon,text,confidence in detections or []:
        left,top=min(p[0] for p in polygon),min(p[1] for p in polygon)
        right,bottom=max(p[0] for p in polygon),max(p[1] for p in polygon)
        fits=[(region,y) for region,y in regions if y<=top<bottom<=y+region[3]-region[1]]
        if len(fits)!=1:continue
        region,y=fits[0]
        box=(left+region[0],top+region[1]-y,right+region[0],bottom+region[1]-y)
        words.append({'text':normalize(text),'confidence':float(confidence),'box':box,
                      'center':((box[0]+box[2])/2,(box[1]+box[3])/2)})
    page=classify(words)
    required={f'+{target}阶段' for target in (3,6,9,12,15)}|{'强化'}
    recognized={word['text'] for word in words if word['confidence']>=.9}
    # 强化粉末返还弹层保留底层按钮；仅凭顶底控件可能误认成可操作批量页。
    if any(word['confidence']>=.85 and (word['text']=='获得奖励'
           or re.fullmatch(r'超过上限的经验值已作为强化粉[末未]返还[。.]?',word['text']))
           for word in words):
        return inspect_screen(path)
    if page!='batch_enhancement' or not required<=recognized:return inspect_screen(path)
    return Screen(str(source.resolve()),page,1280,720,tuple(words))


def inspect_selection_screen(path):
    """背包选装只读标题、按钮、计数和空详情提示，不OCR装备属性。"""
    import numpy as np
    from PIL import Image
    from .local_ocr import _engine
    source=Path(path)
    regions=(((0,0,640,145),0),((640,0,1280,145),157),
             ((850,640,1270,710),314),((920,400,1200,490),396),
             ((960,168,1160,218),498))
    with Image.open(source) as image:
        if image.size!=(1280,720):return inspect_screen(path)
        packed=Image.new('RGB',(640,640),(0,0,0))
        for box,top in regions:packed.paste(image.crop(box),(0,top))
    detections,_=_engine()(np.asarray(packed)[:,:,::-1].copy(),use_cls=False)
    words=[]
    for polygon,text,confidence in detections or []:
        left,top=min(p[0] for p in polygon),min(p[1] for p in polygon)
        right,bottom=max(p[0] for p in polygon),max(p[1] for p in polygon)
        fits=[(region,y) for region,y in regions if y<=top<bottom<=y+region[3]-region[1]]
        if len(fits)!=1:continue
        region,y=fits[0]
        box=(left+region[0],top+region[1]-y,right+region[0],bottom+region[1]-y)
        words.append({'text':normalize(text),'confidence':float(confidence),'box':box,
                      'center':((box[0]+box[2])/2,(box[1]+box[3])/2)})
    page=classify(words)
    if page=='unknown':
        from .inventory_mode_vision import inspect_zero_selection
        try:inspect_zero_selection(source,words)
        except ValueError:pass
        else:page='inventory_batch_selection_empty'
    if page not in {'inventory_batch_selection','inventory_batch_selection_empty'}:
        return inspect_screen(path)
    return Screen(str(source.resolve()),page,1280,720,tuple(words))
