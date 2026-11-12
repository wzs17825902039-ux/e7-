"""批量页资源预览：持有、预留和剩余分别记录，实际扣款另行核对。"""
from dataclasses import dataclass, field
from pathlib import Path
import re


MATERIALS = (
    ('powder','装备强化粉末'), ('jewelry_powder','饰品强化粉末'),
    ('lesser_stone','下级装备强化石'), ('jewelry_lesser_stone','下级饰品强化石'),
    ('greater_stone','上级装备强化石'), ('jewelry_greater_stone','上级饰品强化石'),
    ('epic_stone','传说装备强化石'), ('jewelry_epic_stone','传说饰品强化石'),
)
NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)'


def parse_balance(text):
    match = re.fullmatch(rf'({NUMBER})(?:\(-({NUMBER})\))?', text)
    if not match:
        raise ValueError(f'材料余额或消耗格式未确认：{text!r}')
    remaining = int(match[1].replace(',',''))
    reserved = int(match[2].replace(',','')) if match[2] is not None else 0
    return remaining, reserved


def amount(text):
    if not re.fullmatch(NUMBER,text):
        raise ValueError('金币数字格式未确认')
    return int(text.replace(',',''))


def zero_match(image, _reference='zero.png'):
    """数字栏的完整零字形正证据；白图、空图、点状字形不能当0。"""
    import numpy as np
    import cv2
    from PIL import Image
    pixels = np.asarray(image.convert('RGB')).astype(int)
    mask = ((pixels.min(2)>130) & (pixels.max(2)-pixels.min(2)<100)).astype('uint8')*255
    bitmap = Image.fromarray(mask)
    bounds = bitmap.getbbox()
    if not bounds or not 8 <= bounds[2]-bounds[0] <= 24 or not 14 <= bounds[3]-bounds[1] <= 30:
        return 0.
    if _reference == 'zero.png':
        # 强化结果页零值的字体不同；两种模板分别执行完整原门槛。
        return max(zero_match(image, name) for name in ('zero-original', 'zero-result.png'))
    reference_name = 'zero.png' if _reference == 'zero-original' else _reference
    with Image.open(Path(__file__).with_name('assets')/'batch-materials'/reference_name) as reference:
        a = np.asarray(bitmap.crop(bounds).resize((20,28)))>128
        b = np.asarray(reference.resize((20,28)))>128
    # 小字的亚像素栅格可能使笔画相差1像素；允许局部偏移，但必须保留居中的单个孔洞。
    contours,hierarchy = cv2.findContours(a.astype('uint8'),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    holes = [contour for contour,relation in zip(contours,hierarchy[0])
             if relation[3]>=0 and cv2.contourArea(contour)>2] if hierarchy is not None else []
    if len(holes)!=1:
        return 0.
    hx,hy,hw,hh = cv2.boundingRect(holes[0])
    if not (8 <= hx+hw/2 <= 12 and 11 <= hy+hh/2 <= 17):
        return 0.
    if float((a&b).sum()/max(1,(a|b).sum())) < .8:
        return 0.
    kernel = np.ones((3,3),'uint8')
    near_b = cv2.dilate(b.astype('uint8'),kernel)>0
    near_a = cv2.dilate(a.astype('uint8'),kernel)>0
    return min(float((a&near_b).sum()/max(1,a.sum())),float((b&near_a).sum()/max(1,b.sum())))


@dataclass(frozen=True)
class BatchResources:
    available: dict
    remaining: dict
    reserved: dict
    gold_cost: int
    target: int | None
    image: str
    evidence: dict = field(default_factory=dict)

    @property
    def has_preview(self):
        return bool(self.gold_cost or any(self.reserved.values()))

    def cost(self):
        return {'gold':self.gold_cost, **self.reserved}


@dataclass(frozen=True)
class UntrackedBatchResources:
    target: int | None
    image: str
    available: None = None
    remaining: None = None
    reserved: None = None
    gold_cost: None = None

    @property
    def has_preview(self):
        return self.target is not None


def inspect_untracked_resources(screen):
    """只看阶段按钮状态，不读取任何金币或材料数字。"""
    from PIL import Image
    if screen.page != 'batch_enhancement':
        raise ValueError('未确认批量强化页')
    chosen = []
    with Image.open(screen.source) as source:
        image = source.convert('RGB').resize((1280,720))
        for index,target in enumerate((3,6,9,12,15)):
            pixels = list(image.crop((28+index*197,652,45+index*197,658)).getdata())
            white = sum(min(pixel)>150 for pixel in pixels)/len(pixels)
            if white >= .85:
                chosen.append(target)
            elif white > .05:
                raise ValueError('强化目标按钮状态不明确')
    if len(chosen)>1:
        raise ValueError('多个强化阶段同时选中')
    return UntrackedBatchResources(chosen[0] if chosen else None, screen.source)

def inspect_resources(screen, read_numbers=None):
    from PIL import Image
    if screen.page != 'batch_enhancement':
        raise ValueError('未确认批量强化页，不能读取资源预览')
    screen.find('强化材料',(995,75,1190,120))
    regions = {'gold':(665,15,805,55), 'cost':(1055,648,1146,686)}
    for index,(key,label) in enumerate(MATERIALS):
        screen.find(label,(1060,130+index*62,1250,160+index*62))
        regions[key] = (1168,156+index*62,1270,186+index*62)
    details = {}
    if read_numbers is None:
        from .local_ocr import read_local_regions
        native = {key:tuple(round(value*(screen.width/1280 if index%2==0 else screen.height/720))
                            for index,value in enumerate(box)) for key,box in regions.items()}
        values,details = read_local_regions(screen.source,native)
    else:
        values = read_numbers(screen.source,regions)
    # 极小0字形易被OCR读作标点；只用完整图形匹配提供独立正证据。
    raw_values,zero_scores,recovered = dict(values),{},[]
    with Image.open(screen.source) as source:
        reference = source.convert('RGB').resize((1661,933))
        for key,_ in MATERIALS:
            box = tuple(round(value*(1661/1280 if index%2==0 else 933/720))
                        for index,value in enumerate(regions[key]))
            proof = zero_match(reference.crop(box))
            zero_scores[key] = round(proof,4)
            if values[key] == '0' and proof < .9:
                raise ValueError('材料零值缺少完整字形证据')
            if proof >= .9:
                if values[key] not in ('','0'):
                    raise ValueError('零值图形与材料OCR冲突')
                if not values[key]:
                    recovered.append(key)
                values[key] = '0'
    available,remaining,reserved = {},{},{}
    gold = amount(values['gold'])
    available['gold'] = remaining['gold'] = gold
    for key,_ in MATERIALS:
        remaining[key],reserved[key] = parse_balance(values[key])
        available[key] = remaining[key]+reserved[key]
    with Image.open(screen.source) as source:
        image = source.convert('RGB').resize((1280,720))
        chosen = []
        for index,target in enumerate((3,6,9,12,15)):
            pixels = list(image.crop((28+index*197,652,45+index*197,658)).getdata())
            white = sum(min(pixel)>150 for pixel in pixels)/len(pixels)
            if white >= .85:
                chosen.append(target)
            elif white > .05:
                raise ValueError('强化目标按钮状态不明确')
    if len(chosen)>1:
        raise ValueError('出现多个强化目标选中状态')
    target = chosen[0] if chosen else None
    cost = amount(values['cost'])
    if cost and (target is None or not any(reserved.values())):
        raise ValueError('金币费用、目标阶段和材料预留不一致')
    if not cost and any(reserved.values()):
        raise ValueError('预留材料但金币费用为0')
    return BatchResources(available,remaining,reserved,cost,target,screen.source,
                          {'raw':raw_values,'zero_scores':zero_scores,'zero_recovered':recovered,
                           'ocr_details':details})


def verify_material_preview(before, prepared, target, items):
    if before.gold_cost or any(before.reserved.values()):
        raise ValueError('初始材料已经登记，不能当作未登记余额')
    if prepared.target != target or prepared.gold_cost <= 0:
        raise ValueError('目标或强化费用未确认')
    if prepared.available != before.available:
        raise ValueError('登记材料期间持有资源发生变化')
    if not any(prepared.reserved.values()):
        raise ValueError('没有登记强化材料')
    selected = [item for item in items if item.selected]
    if not selected:
        raise ValueError('没有选中需要强化的装备')
    jewelry = any(item.equipment.slot in ('ring','necklace') for item in selected)
    equipment = any(item.equipment.slot not in ('ring','necklace') for item in selected)
    for key,value in prepared.reserved.items():
        if value and ((key.startswith('jewelry_') and not jewelry) or
                      (not key.startswith('jewelry_') and not equipment)):
            raise ValueError('预留材料与选中装备类别不符')
    return prepared.cost()


def verify_actual_resources(before, prepared, after):
    if after.gold_cost or any(after.reserved.values()):
        raise ValueError('强化结果尚有材料登记，不能进行实际核账')
    actual = {key:before.available[key]-after.available[key] for key in before.available}
    expected = prepared.cost()
    if actual != expected:
        raise ValueError(f'实际扣款与预览不符：实际{actual}，预览{expected}')
    return actual
