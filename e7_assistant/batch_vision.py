"""国服4×4批量强化面板：属性图标匹配与数字OCR分离。"""

from dataclasses import asdict
from functools import lru_cache
import hashlib
import importlib.util
import math
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageOps

from .rules import Equipment
from .vision import read_regions
from .workflow import BatchItem


REFERENCE_SIZE = (1661, 933)
ICON_NAMES = ("atk", "crit", "cdmg", "speed", "resistance", "def", "hp", "effectiveness")


def _vector(image):
    image = ImageOps.grayscale(image).resize((24, 24))
    values = list(image.getdata())
    floor = sorted(values)[len(values) // 5]
    values = [max(0, value - floor) for value in values]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else [0] * len(values)


@lru_cache(maxsize=1)
def _templates():
    result = {}
    for name in ICON_NAMES:
        with Image.open(Path(__file__).with_name("assets") / "stat-icons" / (name + ".png")) as image:
            result[name] = _vector(image)
    return result


def match_icon(image):
    rgb = image.convert('RGB')
    return _match_icon_cached(rgb.size, rgb.tobytes())


def match_main_icon(reference,dx,dy):
    try:
        return match_icon(reference.crop((144+dx,180+dy,174+dx,205+dy)))
    except ValueError as original:
        # 主属性图标比副属性大，抗性图标下沿会被旧框截掉。两个完整裁切
        # 均独立通过原匹配门槛且标签一致才接受，不降低相似度/间隔阈值。
        try:
            a=match_icon(reference.crop((142+dx,175+dy,176+dx,210+dy)))
            b=match_icon(reference.crop((144+dx,176+dy,174+dx,209+dy)))
        except ValueError:
            # 主属性命中图标的横向齿轮比副属性宽，过高裁切反而压扁轮廓。
            # 两个完整框须各自达到更高的0.9相似度，仍保留原间隔门槛。
            a=match_icon(reference.crop((142+dx,177+dy,176+dx,207+dy)))
            b=match_icon(reference.crop((141+dx,177+dy,177+dx,207+dy)))
            if min(a[1],b[1])<.9:raise original
        if a[0]!=b[0]:
            raise ValueError('主属性图标双裁切冲突') from original
        return a[0],min(a[1],b[1])


@lru_cache(maxsize=512)
def _match_icon_cached(size, pixels):
    import numpy as np
    image = Image.frombytes('RGB', size, pixels)
    vectors = []
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            shifted = Image.new("RGB", image.size, image.convert("RGB").getpixel((0, 0)))
            shifted.paste(image, (dx, dy))
            vectors.append(_vector(shifted))
    names=list(_templates())
    # 与原25个平移向量逐项点积相同，交给矩阵运算，避免Python嵌套循环。
    similarities=np.asarray(vectors,dtype=np.float64) @ np.asarray([_templates()[name] for name in names],dtype=np.float64).T
    scores=sorted(((float(score),name) for name,score in zip(names,similarities.max(axis=0))),reverse=True)
    best, name = scores[0]
    if best < .78 or best - scores[1][0] < .04:
        raise ValueError(f"副属性图标无法可靠确认：{name}，相似度{best:.3f}")
    return name, best


def _box(x1, y1, x2, y2):
    return (round(x1 * 1280 / 1661), round(y1 * 720 / 933),
            round(x2 * 1280 / 1661), round(y2 * 720 / 933))


def _rarity(image, x, y):
    pixels = list(image.crop((x + 18, y + 15, x + 100, y + 106)).getdata())
    purple = sum(r > 55 and r > g * 1.5 and b > g * 1.3 for r, g, b in pixels)
    red = sum(r > 65 and r > g * 1.6 and r > b * 1.6 for r, g, b in pixels)
    if purple / len(pixels) > .15 and purple > red * 1.4:
        return "purple"
    if red / len(pixels) > .15 and red > purple * 1.4:
        return "red"
    raise ValueError("批量装备品质颜色未确认")


def _is_level85(image):
    def mask(bitmap):
        return [r > 140 and g > 120 and b < 140 and r > b * 1.2
                for r, g, b in bitmap.convert("RGB").crop((6, 7, 30, 26)).getdata()]
    with Image.open(Path(__file__).with_name("assets") / "stat-icons" / "level85.png") as template:
        expected = mask(template)
    actual = mask(image)
    union = sum(a or b for a, b in zip(actual, expected))
    return bool(union) and sum(a and b for a, b in zip(actual, expected)) / union >= .72


@lru_cache(maxsize=1)
def _absent_badge_templates():
    folder=Path(__file__).with_name('assets')/'batch-slots'
    result=[]
    for path in sorted(folder.glob('no-enhancement-badge*.png')):
        with Image.open(path) as image:
            result.append(image.convert('RGB').copy())
    return tuple(result)


@lru_cache(maxsize=1)
def _numbered_badge_templates():
    folder=Path(__file__).with_name('assets')/'batch-slots'
    result=[]
    for path in sorted(folder.glob('enhancement-badge-[0-9][0-9]*.png')):
        with Image.open(path) as image:
            result.append((int(path.stem.split('-')[2]),image.convert('RGB').copy()))
    return tuple(result)


def read_badge_level(reference,dx,dy,text):
    """读数优先；拒识只有匹配已确认的无徽标背景才可作为+0。"""
    import numpy as np
    match=re.fullmatch(r'\+?([1-9]|1[0-5])',text)
    if match:
        return int(match[1])
    if text:
        raise ValueError('强化徽标数字不合法')
    patch=reference.crop((100+dx,168+dy,140+dx,195+dy)).convert('RGB')
    b=np.asarray(patch,dtype=float)
    # 极小的橙色徽标可能OCR拒识；允许已人工核对的完整徽标图形提供独立证据。
    matches=[]
    for level,template in _numbered_badge_templates():
        a=np.asarray(template,dtype=float)
        difference=np.abs(b-a)
        if difference.mean()<=3 and np.percentile(difference,95)<=8:
            matches.append(level)
    if len(set(matches))==1:
        return matches[0]
    if matches:
        raise ValueError('强化徽标图形匹配不唯一')
    # 遮罩可降低背景亮度，但不能改变背景结构或引入徽标字形。
    for template in _absent_badge_templates():
        a=np.asarray(template,dtype=float)
        scale=float((a*b).sum()/max(1,(a*a).sum()))
        difference=np.abs(b-a*scale)
        if .3<=scale<=1.15 and difference.mean()<=3 and np.percentile(difference,95)<=8:
            return 0
    # 徽标是橙色底板，装备图案的行列重采样不应要求新增背景模板。
    # 在多个亮度下检查上半区连通分量；有任何候选都拒绝推断+0。
    # 同时要求真实纹理，空白、遮挡或过暗裁框不能作为无徽标证据。
    import cv2
    if b.std()>=10 and (b.max(axis=2)>50).sum()>=100:
        components=[]
        for gain in (1,2.5,4,8):
            r,g,blue=np.minimum(b*gain,255).transpose(2,0,1)
            mask=((r>160)&(g>65)&(g<180)&(blue<85)&(r>g*1.2)).astype('uint8')
            _,_,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=8)
            components.extend(s[cv2.CC_STAT_AREA] for s in stats[1:]
                              if s[cv2.CC_STAT_TOP]<mask.shape[0]//2)
        if not components:
            return 0
    raise ValueError('强化徽标未可靠读取，且未确认无徽标背景')


def _raw_stat_value(details):
    raw=[c for c in details.get('candidates',[]) if c['variant']=='raw'
         and c['confidence']>=.9 and re.fullmatch(r'\d+%?',c['text'])]
    return raw[0]['text'] if len(raw)==1 else None


def _stat_crop_consensus(original,expanded,shifted):
    """原框/左扩/右移的原色读数一致，且右移框独立通过原投票规则。"""
    value=_raw_stat_value(original)
    if (not value or _raw_stat_value(expanded)!=value or _raw_stat_value(shifted)!=value
            or shifted.get('accepted') is not True or shifted.get('text')!=value):
        return None
    for evidence in (original,expanded,shifted):
        for candidate in evidence.get('candidates',[]):
            if (candidate['variant'] in ('raw','detected','guided')
                    and candidate['confidence']>=.9 and re.fullmatch(r'\d+%?',candidate['text'])
                    and candidate['text']!=value):
                return None
    return value


def _stat_guided_crop_consensus(original,shifted):
    """原框原色与检测框读数一致，右移框再独立通过原投票规则。"""
    value=_raw_stat_value(original)
    guided=[c for c in original.get('candidates',[]) if c['variant']=='guided'
            and c['confidence']>=.9 and c['text']==value]
    if (not value or len(guided)!=1 or shifted.get('accepted') is not True
            or shifted.get('text')!=value or _raw_stat_value(shifted)!=value):
        return None
    for evidence in (original,shifted):
        if any(c['variant'] in ('raw','detected','guided') and c['confidence']>=.9
               and re.fullmatch(r'\d+%?',c['text']) and c['text']!=value
               for c in evidence.get('candidates',[])):
            return None
    return value


def inspect_selection_flags(path,count):
    """仅检查批量卡片的选中边框；属性仍由输入前后的完整观察核验。"""
    if type(count) is not int or not 1<=count<=16:
        raise ValueError('批量卡片数量无效')
    with Image.open(path) as source:
        if source.size!=(1280,720):raise ValueError('批量选择检查需要1280×720截图')
        reference=source.convert('RGB').resize(REFERENCE_SIZE)
    result=[]
    for index in range(count):
        row,col=divmod(index,4)
        x,y=20+round(col*316.667),166+round(row*167.333)
        result.append(any(sum(b>100 and g>90 and b>r*1.1 for r,g,b in
                              reference.crop((x+20,by,x+275,by+1)).getdata())/255>.6
                          for by in range(y-4,y+6)))
    return result


def verify_selection_page(reference,path,count):
    """选择期间用已核验页面的多处静态区域辨认页面，避免重复整页OCR。"""
    from PIL import ImageChops,ImageStat
    with Image.open(reference) as a,Image.open(path) as b:
        if a.size!=b.size or a.size!=(1280,720):
            raise ValueError('调整选择时截图尺寸变化')
        a,b=a.convert('RGB'),b.convert('RGB')
        # 勾选不同强化阶段的装备会改变阶段按钮的启用状态，即使仍有选中项。
        # 因此底部按钮不是静态页面锚点，不能参与此处像素一致性检查。
        # 顶部静态区域始终核验，属性与资源仍在整组选完后完整复核。
        # 右上召唤广播及阴影会覆盖至y100；锚点取阴影下方。
        boxes=[(0,0,300,55),(860,105,980,125),(1000,105,1260,125)]
        for box in boxes:
            difference=ImageChops.difference(a.crop(box),b.crop(box))
            if max(ImageStat.Stat(difference).mean)>.5:
                raise ValueError('调整选择时页面区域变化，停止输入')
    return inspect_selection_flags(path,count)


def verify_stable_batch_pixels(reference,path,items):
    """首次完整OCR后的第二帧：逐块核对字形、选中、锁及槽位，不重复读数字。"""
    from .batch_sale_vision import content_proof
    from .slot_vision import inspect_slots
    from .lock_vision import inspect_batch_lock
    if not items or len(items)>16:
        raise ValueError('稳定性核验缺少批量装备')
    with Image.open(reference) as before,Image.open(path) as after:
        if before.size!=(1280,720) or after.size!=before.size:
            raise ValueError('稳定性截图尺寸不符')
        from .slot_vision import boosted_indices
        slots=inspect_slots(after.convert('RGB').resize(REFERENCE_SIZE),boosted_indices(items),
                            {i:item.equipment.rarity for i,item in enumerate(items)})
        if [s['state'] for s in slots]!=['occupied']*len(items)+['empty']*(16-len(items)):
            raise ValueError('稳定性复核槽位发生变化')
        if inspect_selection_flags(path,len(items))!=[i.selected for i in items]:
            raise ValueError('稳定性复核选中集合发生变化')
        for index,item in enumerate(items):
            content_proof(before,after,index,strict=True,attributes_only=True)
            lock=inspect_batch_lock(after,'batch_enhancement',index,True)
            if lock['locked'] is not item.locked:
                raise ValueError('稳定性复核锁状态不符')


def inspect_batch(path, slot, batch_id="batch", engine=None, verified_level_anchors=None,
                  entry_details=None, ignore_levels=False, require_score=True,
                  known_items=None, reference_path=None,ignore_purple_main=False,
                  purple_speed_only=False,speed_rows=None,retry_report=None,boosted_red_indices=(),
                  registered_rarities=None,initial_indices=()):
    """返回可复核的16张卡片候选；任一卡片关键字段失败则整页不可执行。"""
    source = Path(path)
    engine = engine or ("rapidocr" if importlib.util.find_spec("rapidocr_onnxruntime") else "windows")
    ocr_details = {}
    detections = None
    if engine == 'rapidocr':
        from .local_ocr import _engine
        detections, _ = _engine()(str(source), use_cls=False)
    def read(path, regions, language="en-US"):
        if engine == "rapidocr":
            from .local_ocr import read_local_regions,stat_number_box
            native_regions = {key: (round(box[0] * width / 1661), round(box[1] * height / 933),
                                    round(box[2] * width / 1661), round(box[3] * height / 933))
                              for key, box in regions.items()}
            # 保留数字完整左笔画：某些列原框会裁掉8左侧，被多种预处理一致误读为3。
            native_regions={key:stat_number_box(box) if key.startswith('stat') else box
                            for key,box in native_regions.items()}
            values, details = read_local_regions(source, native_regions, detections=detections)
            ocr_details.update(details)
            return values
        if engine != "windows":
            raise ValueError("未知批量OCR引擎")
        return read_regions(path, {key: _box(*box) for key, box in regions.items()}, language=language)
    with Image.open(source) as raw:
        width, height = raw.size
        if abs(width / height - 16 / 9) > .02:
            raise ValueError("批量页面必须是完整16:9画面，不能使用裁剪截图")
        raw_image = raw.convert('RGB')
        reference = raw_image.resize(REFERENCE_SIZE)
        normalized = reference.resize((1280, 720))
    from .slot_vision import inspect_slots
    boosted=set(boosted_red_indices)
    registered=dict(registered_rarities or {})
    if known_items:
        from .slot_vision import boosted_indices
        boosted.update(boosted_indices(known_items))
        for index,item in enumerate(known_items):
            if index in registered and registered[index]!=item.equipment.rarity:
                raise ValueError('已登记批次品质冲突')
            registered[index]=item.equipment.rarity
    slots = inspect_slots(reference,boosted,registered,initial_indices)
    speed_rows=dict(speed_rows or {}) if purple_speed_only else {}
    for index,speed_row in speed_rows.items():
        if (type(index) is not int or not 0<=index<16 or type(speed_row) is not int
                or not 0<=speed_row<4 or slots[index]['state']!='occupied' or slots[index]['rarity']!='purple'):
            raise ValueError('紫装速度行登记与当前批量槽位不符')
    reused={}
    if retry_report and retry_report.get('source'):
        from copy import deepcopy
        import numpy as np
        # 仅入口只读重试复用同位置整张卡片逐像素相同的成功结果。
        # 徽标、主副属性、锁、选择框任何像素改变，都重新识别该卡片。
        with Image.open(retry_report['source']) as previous:
            prior=previous.convert('RGB').resize(REFERENCE_SIZE)
        for record in retry_report.get('records',[]):
            index=record['index']
            if (not 0<=index<16 or slots[index]['state']!='occupied'
                    or record.get('main_issue') or not record['equipment'].get('recognition_ok')
                    or record['equipment'].get('enhancement_bonus',False)!=(index in boosted)
                    or slots[index]['rarity']!=record['equipment']['rarity']):continue
            dx,dy=round(index%4*316.667),round(index//4*167.333)
            box=(20+dx,164+dy,330+dx,323+dy)
            if np.array_equal(np.asarray(prior.crop(box)),np.asarray(reference.crop(box))):
                reused[index]={**deepcopy(record),'content_source':'entry_retry_unchanged_pixels',
                               'reference':retry_report['source']}
                if purple_speed_only and index in retry_report.get('speed_rows',{}):
                    speed_rows[index]=retry_report['speed_rows'][index]
    if known_items and reference_path and len(known_items)<=16:
        from .batch_sale_vision import content_proof
        from .lock_vision import inspect_batch_lock
        flags=inspect_selection_flags(source,len(known_items))
        with Image.open(reference_path) as previous:
            for index,known in enumerate(known_items):
                if (known.selected or flags[index] or slots[index]['state']!='occupied'
                        or slots[index]['rarity']!=known.equipment.rarity):continue
                try:
                    content_proof(previous,raw_image,index,strict=True,attributes_only=True)
                    lock=inspect_batch_lock(reference,'batch_enhancement',index,True)
                    if lock['locked'] is not known.locked:continue
                except ValueError:
                    continue
                reused[index]={'index':index,'equipment':asdict(known.equipment),
                               'selected':False,'locked':known.locked,
                               'main':{'stat':known.equipment.main_stat},
                               'main_issue':None,'content_source':'unchanged_pixels',
                               'reference':str(reference_path)}
    if purple_speed_only:
        for index,slot_state in enumerate(slots):
            if (slot_state['state']!='occupied' or slot_state['rarity']!='purple'
                    or index in reused):continue
            # 正式驱动已固定每件装备的读取范围；不能在观察中途删去完整副属性。
            if known_items and index<len(known_items):
                if known_items[index].equipment.observation_scope=='full':
                    speed_rows.pop(index,None)
                    continue
            if index in speed_rows:continue
            row,col=divmod(index,4)
            dx,dy=round(col*316.667),round(row*167.333)
            matches=[]
            for stat_row in range(4):
                try:
                    name,_=match_icon(reference.crop((144+dx,212+dy+stat_row*28,174+dx,237+dy+stat_row*28)))
                except ValueError:
                    continue
                if name=='speed':matches.append(stat_row)
            if len(matches)>1:raise ValueError('同一卡片出现多处速度行候选')
            if matches:speed_rows[index]=matches[0]
    with tempfile.TemporaryDirectory(prefix="e7-batch-") as directory:
        normalized_path = Path(directory) / "normalized.png"
        normalized.save(normalized_path)
        title = read(normalized_path, {"title": (80, 10, 255, 70)}, language="zh-Hans-CN")["title"]
        if title != "批量强化":
            raise ValueError("未确认批量强化页面")
        fields = {}
        for start in range(0, 16, 16):
            regions = {}
            for index in range(start, start + 16):
                if slots[index]['state'] != 'occupied':
                    continue
                if index in reused:
                    continue
                row, column = divmod(index, 4)
                dx, dy = round(column * 316.667), round(row * 167.333)
                regions[f"badge{index}"] = (100 + dx, 164 + dy, 144 + dx, 201 + dy)
                if not ignore_levels:
                    regions[f"level{index}"] = (33 + dx, 182 + dy, 64 + dx, 210 + dy)
                if require_score and index not in speed_rows:
                    regions[f"score{index}"] = (40 + dx, 282 + dy, 101 + dx, 316 + dy)
                if not(ignore_purple_main and slots[index]['rarity']=='purple'):
                    regions[f"main{index}"] = (177 + dx, 172 + dy, 325 + dx, 205 + dy)
                for stat_row in ([speed_rows[index]] if index in speed_rows else range(4)):
                    y = 211 + dy + stat_row * 28
                    regions[f"stat{index}_{stat_row}"] = (177 + dx, y, 325 + dx, y + 27)
            english = read(normalized_path, regions) if regions else {}
            if engine == 'rapidocr':
                # 主属性60的左笔画也可能被固定框裁切；仅对拒识项扩大后重新投票。
                main_wider={key:(box[0]-5,*box[1:]) for key,box in regions.items()
                            if key.startswith('main') and not re.fullmatch(r'\d+%?',english.get(key,''))}
                if main_wider:
                    original_main={key:ocr_details.get(key) for key in main_wider}
                    english.update(read(normalized_path,main_wider))
                    for key in main_wider:
                        ocr_details[key]['original_crop']=original_main[key]
                        ocr_details[key]['expanded_left']=5
                # 小尺寸下，固定框可能切掉6的左笔画；只对拒识项扩大左边界后重读。
                wider = {key:(box[0]-2,*box[1:]) for key,box in regions.items()
                         if key.startswith('stat') and not re.fullmatch(r'\d+%?(?:\(.*)?',english.get(key,''))}
                original = {key:ocr_details.get(key) for key in wider}
                if wider:
                    english.update(read(normalized_path,wider))
                    for key in wider:
                        ocr_details[key]['original_crop'] = original[key]
                        ocr_details[key]['expanded_left'] = 2
                # 变换后的百分号可能多出一个0；只为三处原色一致的拒识项取证。
                shifted={key:(regions[key][0]+2,*regions[key][1:]) for key in wider
                         if not english.get(key) and _raw_stat_value(original[key] or {})}
                if shifted:
                    expanded={key:ocr_details[key] for key in shifted}
                    read(normalized_path,shifted)
                    for key in shifted:
                        fresh=ocr_details[key]
                        value=_stat_crop_consensus(original[key],expanded[key],fresh)
                        guided_value=_stat_guided_crop_consensus(original[key],fresh)
                        value=value or guided_value
                        ocr_details[key]={**expanded[key],'shifted_right':2,'shifted_crop':fresh,
                                          'raw_crop_consensus':bool(value)}
                        if value:
                            english[key]=value
                            confidence=min(next(c['confidence'] for c in evidence['candidates']
                                                if c['variant']=='raw')
                                           for evidence in ((original[key],fresh) if guided_value else
                                                            (original[key],expanded[key],fresh)))
                            ocr_details[key].update(text=value,confidence=confidence,accepted=True)
            retry = {key: value for key, value in regions.items()
                     if key.startswith("stat") and not re.fullmatch(r"\d+%?(?:\(.*)?", english.get(key, ""))}
            if retry and engine == "windows":
                english.update(read(normalized_path, retry, language="zh-Hans-CN"))
            if engine=='rapidocr':
                from .numeric_units import read_percent_value
                for key,box in retry.items():
                    native_box=tuple(round(v*(width/1661 if i%2==0 else height/933)) for i,v in enumerate(box))
                    evidence=read_percent_value(source,native_box)
                    if evidence:
                        english[key]=evidence['text']
                        ocr_details[key]={'original_rejection':ocr_details.get(key),**evidence}
            fields.update(english)
    items, records, issues = [], [], []
    for index in range(16):
        if slots[index]['state'] == 'empty':
            continue
        if slots[index]['state'] == 'unknown':
            issues.append(f"卡片{index + 1}：槽位占用状态未确认")
            continue
        if isinstance(slot,dict) and index not in slot:
            issues.append(f'卡片{index + 1}：出现未登记位置的装备')
            continue
        if index in reused:
            record=reused[index]
            records.append(record)
            items.append(BatchItem(str(index),Equipment(**record['equipment']),record['selected'],record['locked']))
            continue
        row, column = divmod(index, 4)
        dx, dy = round(column * 316.667), round(row * 167.333)
        x, y = 20 + dx, 166 + dy
        try:
            rarity = slots[index]['rarity']
            from .lock_vision import inspect_batch_lock,matches_locked_level
            lock=inspect_batch_lock(reference,'batch_enhancement',index,True)
            anchored=(not ignore_levels and lock['locked'] is True and index in (verified_level_anchors or {})
                      and matches_locked_level(raw_image,verified_level_anchors[index],index))
            entry_anchor=(not ignore_levels and lock['locked'] is True and index in (entry_details or {})
                          and not re.fullmatch(r'\d{2,3}',fields[f'level{index}']))
            if not ignore_levels and fields[f"level{index}"] != "85" and not _is_level85(
                    reference.crop((34 + dx, 182 + dy, 68 + dx, 210 + dy))) and not anchored and not entry_anchor:
                raise ValueError("未确认85级装备")
            try:
                enhancement = read_badge_level(reference,dx,dy,fields[f"badge{index}"])
            except ValueError:
                from .batch_badge_vision import read_numbered_badge
                evidence=read_numbered_badge(reference.crop((100+dx,168+dy,140+dx,195+dy)))
                if not evidence:
                    raise
                enhancement=evidence['value']
                ocr_details[f'badge{index}']={'original_rejection':ocr_details.get(f'badge{index}'),**evidence}
            stats, confidences = {}, {}
            stat_count=3 if rarity=='purple' and enhancement<12 else 4
            if index in speed_rows and speed_rows[index]>=stat_count:
                raise ValueError('登记速度行不属于当前强化阶段的已解锁词条')
            for stat_row in ([speed_rows[index]] if index in speed_rows else range(stat_count)):
                icon = reference.crop((144 + dx, 212 + dy + stat_row * 28,
                                       174 + dx, 237 + dy + stat_row * 28))
                name, confidence = match_icon(icon)
                if index in speed_rows and name!='speed':
                    raise ValueError('登记的速度行图标发生变化')
                raw_value = fields[f"stat{index}_{stat_row}"]
                # 选中高亮可能使整行 OCR 返回空串；百分号图形和数字独立裁框仍可取证。
                if not raw_value and engine=='rapidocr':
                    from .numeric_units import read_percent_value
                    from .local_ocr import stat_number_box
                    key=f'stat{index}_{stat_row}'
                    y=211+dy+stat_row*28
                    box=(177+dx,y,325+dx,y+27)
                    native=tuple(round(v*(width/1661 if i%2==0 else height/933))
                                 for i,v in enumerate(box))
                    evidence=read_percent_value(source,stat_number_box(native))
                    if evidence:
                        raw_value=evidence['text']
                        ocr_details[key]=evidence
                match = re.match(r"^(\d+)(%)?(?:\(.*)?$", raw_value)
                if not match:
                    raise ValueError("副属性数字未可靠读取：" + repr(raw_value))
                value, percentage = int(match[1]), bool(match[2])
                if name in ("atk", "hp", "def"):
                    name += "_pct" if percentage else "_flat"
                elif percentage != (name != "speed"):
                    raise ValueError("副属性单位不匹配")
                if name in stats or value <= 0:
                    raise ValueError("副属性重复或数值无效")
                # 对已支持的普通装备用宽松上界拦截7%→70%等明显误读；不修补数字。
                if percentage and value>10*(1+min(5,enhancement//3)):
                    evidence=None
                    if engine=='rapidocr':
                        from .numeric_units import read_percent_value
                        from .local_ocr import stat_number_box
                        key=f'stat{index}_{stat_row}'
                        y=211+dy+stat_row*28
                        box=(177+dx,y,325+dx,y+27)
                        native=tuple(round(v*(width/1661 if i%2==0 else height/933))
                                     for i,v in enumerate(box))
                        evidence=read_percent_value(source,stat_number_box(native))
                    if not evidence or not 0<int(evidence['text'][:-1])<=10*(1+min(5,enhancement//3)):
                        raise ValueError('百分比副属性超过当前强化阶段的宽松上界')
                    # 从单位图形和独立数字裁框重新取证，不从原读数推测正确数字。
                    ocr_details[key]={'out_of_range_rejection':ocr_details.get(key),**evidence}
                    value=int(evidence['text'][:-1])
                stats[name] = value
                confidences[name] = round(confidence, 4)
            score = fields.get(f"score{index}")
            if require_score and index not in speed_rows and not re.fullmatch(r"\d{1,3}", score or ''):
                raise ValueError("装备分数未可靠读取")
            selected = any(sum(b > 100 and g > 90 and b > r * 1.1 for r, g, b in
                               reference.crop((x + 20, by, x + 275, by + 1)).getdata()) / 255 > .6
                           for by in range(y - 4, y + 6))
            identity = hashlib.sha256(reference.crop((x + 20, y + 45, x + 95, y + 104)).tobytes()).hexdigest()
            card_slot = slot[index] if isinstance(slot, dict) else slot
            from .rules import SLOTS
            if card_slot not in SLOTS:
                raise ValueError('批量卡片部位未指定或无效')
            item = Equipment(f"{batch_id}:{index}:{identity}", rarity, None if ignore_levels else 85, enhancement, card_slot,
                             stats, card_slot in {"weapon", "helmet", "armor"}, True, int(score) if score else None,
                             observation_scope='purple_speed' if index in speed_rows else 'full',
                             enhancement_bonus=index in boosted)
            main, main_issue = None, None
            try:
                if not(ignore_purple_main and rarity=='purple'):
                    main_name, _ = match_main_icon(reference,dx,dy)
                    main_match = re.fullmatch(r'(\d+)(%)?', fields[f'main{index}'])
                    if not main_match or int(main_match[1]) <= 0:
                        raise ValueError('主属性数字未确认')
                    percentage = bool(main_match[2])
                    if main_name in ('atk','hp','def'):
                        main_name += '_pct' if percentage else '_flat'
                    elif percentage != (main_name != 'speed'):
                        raise ValueError('主属性单位不符')
                    main = {'stat':main_name, 'value':int(main_match[1])}
            except ValueError as exc:
                main_issue = str(exc)
            if entry_anchor:
                verify_detail_entry_level(entry_details[index],item,main,selected)
            items.append(BatchItem(str(index), item, selected,lock['locked']))
            records.append({"index": index, "equipment": asdict(item), "selected": selected,
                            "main": main, "main_issue": main_issue,
                            "locked": lock['locked'], "lock_evidence":lock,
                            "level_source":('not_requested' if ignore_levels else 'verified_inventory_detail' if entry_anchor else
                                            'verified_lock_transition' if anchored else 'visible_glyph'),
                            "icon_confidences": confidences})
        except ValueError as exc:
            issues.append(f"卡片{index + 1}：{exc}")
    return {"page": "batch_enhancement", "source": str(source.resolve()), "records": records,
            "speed_rows":speed_rows,
            "slots": slots,
            "issues": issues, "items": items, "automation_ready": False,
            "engine": engine, "ocr_details": ocr_details,
            "notice": "批量OCR候选；部位由调用方指定，尚需装备部位与稳定身份复核"}


def verify_detail_entry_level(entry,item,main,selected):
    """原生选装顺序已核对后，仍须逐项匹配独立详情，不能只凭调用方提供85。"""
    from .inventory_detail import detail_fingerprint
    from .vision import ATTRIBUTE_NAMES
    try:
        expected=Equipment(**entry['equipment'])
        label,value=entry['main']
        fingerprint=entry['fingerprint']
        source=entry['source']
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('缺少完整背包详情等级证据') from exc
    if (not isinstance(source,str) or not source or not expected.recognition_ok or expected.level!=85
            or not 0<=expected.enhancement<15 or selected is not True
            or not isinstance(label,str) or label not in ATTRIBUTE_NAMES
            or not isinstance(value,str) or not re.fullmatch(r'\d+%?',value)
            or fingerprint!=detail_fingerprint(expected,(label,value))):
        raise ValueError('背包详情等级证据无效或装备未勾选')
    for field in ('rarity','level','enhancement','slot','stats','game_score'):
        if getattr(expected,field)!=getattr(item,field):
            raise ValueError('批量卡片与背包详情不一致：'+field)
    if expected.enhancement_bonus!=item.enhancement_bonus:
        raise ValueError('批量卡片与背包详情强化加成分类不一致')
    key=ATTRIBUTE_NAMES[label][0 if value.endswith('%') else 1]
    if main!={'stat':key,'value':int(value.rstrip('%'))}:
        raise ValueError('批量主属性与背包详情不一致')
