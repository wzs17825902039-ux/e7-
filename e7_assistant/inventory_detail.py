"""背包右侧装备详情；作为跨页核对的属性快照，不用图标哈希冒充唯一ID。"""
import hashlib
import json
import re

from .rules import Equipment
from .vision import ATTRIBUTE_NAMES, SLOT_NAMES


class UnsupportedEquipment(ValueError):
    """已高置信度识别特殊装备；只允许取消本次选择并保留。"""


def read_selection_header(screen,candidate):
    """仅核对选中装备的品质/部位标题，不读取任何属性或装备等级。"""
    if screen.page!='inventory_batch_selection':
        raise ValueError('未确认批量选择页面')
    special=[w for w in screen.words if '异界' in w['text']
             and 850<=w['center'][0]<1250 and 140<=w['center'][1]<280]
    if special:
        title_words=sorted((w for w in screen.words
                            if 960<=w['center'][0]<1160 and 165<=w['center'][1]<212),
                           key=lambda w:(w['center'][1],w['center'][0]))
        title=''.join(w['text'] for w in title_words)
        match=re.fullmatch(r'异界传说(武器|头盔|铠甲|项链|戒指|鞋子)',title)
        if not match or any(w['confidence']<.95 for w in title_words):
            raise ValueError('异界红装品质和部位标题未完整确认')
        return {'rarity':'red','slot':SLOT_NAMES[match[1]],'level':None,
                'enhancement':candidate['enhancement'],'enhancement_bonus':True}
    headers=[w['text'] for w in screen.words if w['confidence']>=.9
             and 960<=w['center'][0]<1160 and 170<=w['center'][1]<210
             and re.fullmatch(r'(英雄|传说)(武器|头盔|铠甲|项链|戒指|鞋子)',w['text'])]
    if len(headers)!=1:
        raise ValueError('选中装备品质和部位未唯一确认')
    rarity='purple' if headers[0].startswith('英雄') else 'red'
    if rarity!=candidate['rarity']:
        raise ValueError('选中装备品质与列表不符')
    slot=SLOT_NAMES[headers[0][2:]]
    if rarity=='purple' and slot=='boots':
        raise UnsupportedEquipment('紫装鞋子按当前规则不强化，取消本次选择并保留')
    return {'rarity':rarity,'slot':slot,
            'level':None,'enhancement':candidate['enhancement']}


def detail_fingerprint(equipment, main):
    fields = {key:getattr(equipment,key) for key in
              ('rarity','level','enhancement','slot','stats','game_score')}
    fields['main'] = tuple(main)
    if equipment.enhancement_bonus:
        fields['enhancement_bonus'] = True
    return hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode('utf8')).hexdigest()


def read_detail(screen, candidate, read_numbers=None, *, allow_unknown_level=False, policy=None):
    ignore_level = policy is not None and policy.ignore_equipment_level
    if screen.page != 'inventory_batch_selection':
        raise ValueError('只有背包批量选择页可登记初始装备')
    special=[word for word in screen.words if '异界' in word['text']
             and 850 <= word['center'][0] < 1250 and 140 <= word['center'][1] < 280]
    bonus_header=read_selection_header(screen,candidate) if special else None
    headers = [word['text'] for word in screen.words if word['confidence'] >= .9
               and 960 <= word['center'][0] < 1160 and 170 <= word['center'][1] < 210
               and re.fullmatch(r'(英雄|传说)(武器|头盔|铠甲|项链|戒指|鞋子)', word['text'])]
    if bonus_header is None and len(headers) != 1:
        raise ValueError('详情品质和部位未唯一确认')
    if bonus_header:
        rarity,slot=bonus_header['rarity'],bonus_header['slot']
    else:
        header = headers[0]
        rarity = 'purple' if header.startswith('英雄') else 'red'
        slot = SLOT_NAMES[header[2:]]
    enhancement = candidate['enhancement']
    if (not bonus_header and candidate['rarity'] != rarity or type(enhancement) is not int
            or not 0 <= enhancement < 15
            or not (ignore_level or candidate['level'] == 85 or allow_unknown_level and candidate['level'] is None)):
        raise ValueError('详情与刚选中的+0～+14装备不符')
    badges = [int(word['text'][1:]) for word in screen.words
              if word['confidence'] >= .9 and re.fullmatch(r'\+\d{1,2}',word['text'])
              and 920 <= word['center'][0] < 980 and 150 <= word['center'][1] < 200]
    if badges and badges != [enhancement]:
        raise ValueError('详情强化徽标与选中装备不符，可能仍显示此前装备')
    regions = {'level': (883, 173, 915, 204), 'score': (1165, 468, 1230, 496),
               'main': (1150, 328, 1230, 357)}
    if ignore_level:
        del regions['level']
    if enhancement:
        # 只裁切橙色徽标，避免相邻装备图案和品质标题干扰局部数字读取。
        regions['enhancement'] = (934, 166, 971, 190)
    labels = []
    count = 3 if rarity == 'purple' and enhancement < 12 else 4
    for row in range(count):
        cy = 382 + row * 22.5
        names = [word['text'] for word in screen.words if word['confidence'] >= .9
                 and 880 <= word['center'][0] < 1110 and abs(word['center'][1] - cy) < 10]
        if len(names) != 1 or names[0] not in ATTRIBUTE_NAMES:
            raise ValueError(f'详情第{row+1}条属性名未确认')
        labels.append(names[0])
        regions[f'stat{row}'] = (1160, round(cy - 11), 1230, round(cy + 11))
    if read_numbers is None:
        from .local_ocr import read_local_regions
        native = {key: tuple(round(value * (screen.width/1280 if index % 2 == 0 else screen.height/720))
                             for index, value in enumerate(box)) for key, box in regions.items()}
        values, _ = read_local_regions(screen.source, native)
    else:
        values = read_numbers(screen.source, regions)
    if (not ignore_level and values.get('level') != '85') or not re.fullmatch(r'\d{1,3}', values.get('score', '')):
        raise ValueError('详情等级或分数未可靠读取')
    if enhancement:
        badge = re.fullmatch(r'\+?([1-9]|1[0-4])', values.get('enhancement', ''))
        if not badge or int(badge[1]) != enhancement:
            raise ValueError('详情强化等级未独立核对，不继承列表等级')
    main_labels = [word['text'] for word in screen.words if word['confidence'] >= .9
                   and 880 <= word['center'][0] < 1110 and 328 <= word['center'][1] < 357]
    if len(main_labels) != 1 or main_labels[0] not in ATTRIBUTE_NAMES:
        raise ValueError('详情主属性名未确认')
    main = values.get('main', '')
    if not re.fullmatch(r'\d+%?', main):
        raise ValueError('详情主属性值未确认')
    main_name=main_labels[0]
    percent=main.endswith('%')
    if (int(main.rstrip('%'))<=0 or main_name=='速度' and percent
            or main_name in ('暴击率','暴击伤害','效果命中','效果抗性') and not percent):
        raise ValueError('详情主属性单位或数值错误')
    main_key=ATTRIBUTE_NAMES[main_name][0 if percent else 1]
    from .rules import RIGHT_MAIN_STATS
    if slot in RIGHT_MAIN_STATS and main_key not in RIGHT_MAIN_STATS[slot]:
        raise ValueError('详情主属性不适用于该部位')
    stats = {}
    for row, name in enumerate(labels):
        match = re.fullmatch(r'(\d+)(%)?', values.get(f'stat{row}', ''))
        if not match or int(match[1]) <= 0:
            raise ValueError('详情副属性值未可靠读取')
        percent = bool(match[2])
        if (name == '速度' and percent) or (name in ('暴击率','暴击伤害','效果命中','效果抗性') and not percent):
            raise ValueError('详情副属性单位错误')
        key = ATTRIBUTE_NAMES[name][0 if percent else 1]
        if key in stats:
            raise ValueError('详情副属性重复')
        stats[key] = int(match[1])
    level = None if ignore_level else 85
    fields = {'rarity':rarity, 'level':level, 'enhancement':enhancement, 'slot':slot, 'stats':stats,
              'main':(main_labels[0],main), 'game_score':int(values['score'])}
    equipment = Equipment('inventory:pending', rarity, level, enhancement, slot, stats,
                          slot in {'weapon','helmet','armor'} or policy is not None
                          and main_key in policy.right_main_stats.get(slot,[]), True, int(values['score']))
    equipment.enhancement_bonus=bonus_header is not None
    if slot in RIGHT_MAIN_STATS:
        equipment.main_stat=main_key
        from .rules import FLATS
        if main_key in FLATS and stats.get('speed',0)<=0:
            equipment.main_stat_usable=False
    fingerprint = detail_fingerprint(equipment, fields['main'])
    equipment.equipment_id = 'inventory:' + fingerprint
    return {'equipment':equipment, 'fingerprint':fingerprint, 'main':fields['main'], 'source':screen.source}
