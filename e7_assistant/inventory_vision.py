"""背包批量选装页：只报告完整可见卡片，强化等级不由OCR空值推断。"""
import hashlib
import re
from statistics import median
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageEnhance


# 88与90只用于遍历时识别并保留；强化投入仍只允许普通85。
TRACKED_LEVELS={'85':85,'88':88,'90':90}


class InventoryObservationIncomplete(ValueError):
    """未形成完整行观测；只可重新截图，不可提交覆盖或发送新手势。"""


def inventory_context(screen,evidence=None):
    regional=[word for word in screen.words
              if 840<=word['center'][0]<1125 and 80<=word['center'][1]<130]
    texts=[word['text'] for word in regional if word['confidence']>=.95]
    regions={}
    if regional and not any(re.fullmatch(r'\d+/\d+',text) for text in texts):
        regions['inventory_count']=(1022,90,1123,124)
    if regional and not any(re.fullmatch(r'[\u4e00-\u9fff]{1,8}',text) for text in texts):
        regions['inventory_sort']=(876,90,977,124)
    if regions:
        from .local_ocr import read_local_regions
        native={key:tuple(round(v*(screen.width/1280 if i%2==0 else screen.height/720))
                          for i,v in enumerate(box)) for key,box in regions.items()}
        values,details=read_local_regions(screen.source,native,minimum_confidence=.95)
        if evidence is not None:
            evidence.update(details)
        for key,value in values.items():
            pattern=r'\d+/\d+' if key=='inventory_count' else r'[\u4e00-\u9fff]{1,8}'
            if re.fullmatch(pattern,value):
                texts.append(value)
    return tuple(sorted(texts))


def _level_region(pixels, box, scale_x, scale_y):
    """排除卡框及孤立装饰；不修改OCR字符串或数字笔画。"""
    import cv2
    x1, y1, x2, y2 = box
    crop = (x1 + round(6 * scale_x), y1 + round(5 * scale_y),
            x2, y2 - round(5 * scale_y))
    if not (0 <= crop[0] < crop[2] <= pixels.shape[1]
            and 0 <= crop[1] < crop[3] <= pixels.shape[0]):
        raise ValueError('等级裁切区域越界或过小')
    patch = pixels[crop[1]:crop[3], crop[0]:crop[2]]
    r, g, b = (patch[:, :, i] for i in range(3))
    yellow = ((r > 65) & (g > 50) & (g > r * .45) & (b < g * .7)).astype('uint8')
    count, labels, stats, _ = cv2.connectedComponentsWithStats(yellow, connectivity=8)
    removed = []
    for index in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[index])
        # 小于字高的孤立金色斑点会被读成句点；细长的数字1仍保留。
        if height <= round(4 * scale_y) and width <= round(4 * scale_x):
            yellow[labels == index] = 0
            removed.append({'box': (x, y, x + width, y + height), 'area': area})
    return crop, np.where(yellow, 255, 40).astype('uint8'), removed


def _read_levels(path, regions, evidence=False, _retry=True, _vertical_retry=True):
    from .local_ocr import read_local_regions
    with Image.open(path) as image:
        pixels = np.asarray(image.convert('RGB')).astype(float)
    canvas = np.full(pixels.shape[:2], 40, dtype='uint8')
    adjusted, preparation = {}, {}
    for key, box in regions.items():
        crop, patch, removed = _level_region(pixels, box, pixels.shape[1]/1280, pixels.shape[0]/720)
        adjusted[key] = crop
        canvas[crop[1]:crop[3], crop[0]:crop[2]] = patch
        preparation[key] = {'crop': crop, 'removed_small_components': removed}
    masked = Image.fromarray(canvas).convert('RGB')
    with tempfile.TemporaryDirectory(prefix='e7-inventory-levels-') as directory:
        target = Path(directory) / 'levels.png'
        masked.save(target)
        result = read_local_regions(target, adjusted)
        for key, details in result[1].items():
            details['preparation'] = preparation[key]
        if _retry:
            rejected={key:box for key,box in regions.items() if not result[0][key]}
            if rejected:
                # 两个不同边界的裁切分别重新OCR，必须都接受同一个完整等级。
                # 不删除冲突候选，不补数字，不覆盖已有可接受的等级。
                dx=max(1,round(2*pixels.shape[1]/1280))
                left,_left=_read_levels(path,{k:(max(0,b[0]-dx),*b[1:]) for k,b in rejected.items()},True,False)
                expanded,_expanded=_read_levels(path,{k:(max(0,b[0]-dx),b[1],min(pixels.shape[1],b[2]+dx),b[3])
                                               for k,b in rejected.items()},True,False)
                for key in rejected:
                    original=result[1][key]
                    original['margin_retries']={'left':_left[key],'expanded':_expanded[key]}
                    value=left[key]
                    conflicts=any(re.fullmatch(r'\d{2,3}',c['text']) and c['text']!=value and c['confidence']>=.9
                                  for c in original.get('candidates',()))
                    if value in TRACKED_LEVELS and value==expanded[key] and not conflicts:
                        result[0][key]=value
                        result[1][key]={**_expanded[key],'recovery':'independent_margin_consensus',
                                        'original':original}
            # 金色装饰与数字在二值图中可能粘连；低置信度数字不作为等级。
            # 单字或弱完整候选只触发两个原色边界的独立复核，不补字或降门槛。
            color_regions={key:preparation[key]['crop'] for key in regions
                     if (re.fullmatch(r'\d',result[0][key])
                         or (not result[0][key] and any(re.fullmatch(r'\d',c['text']) and c['confidence']>=.9
                                                       for c in result[1][key].get('candidates',())))
                         or (not result[0][key] and any(c['text'] in TRACKED_LEVELS and .7<=c['confidence']<.9
                                                       for c in result[1][key].get('candidates',()))))}
            if color_regions:
                color,color_proof=read_local_regions(path,color_regions)
                dx=max(1,round(2*pixels.shape[1]/1280))
                wider,wider_proof=read_local_regions(path,{key:(max(0,b[0]-dx),b[1],b[2],b[3])
                                                         for key,b in color_regions.items()})
                for key in color_regions:
                    original=result[1][key]
                    original['color_retries']={'original':color_proof[key],'left':wider_proof[key]}
                    value=color[key]
                    masked_observations=(original,*original.get('margin_retries',{}).values())
                    conflicts=any(re.fullmatch(r'\d{2,3}',c['text']) and c['text']!=value and c['confidence']>=.9
                                  for view in masked_observations
                                  for c in (view,*view.get('candidates',())))
                    if (conflicts and value in TRACKED_LEVELS and value==wider[key]
                            and pixels.shape[:2]==(720,1280)):
                        original_conflict=any(re.fullmatch(r'\d{2,3}',c['text']) and c['text']!=value
                                              and c['confidence']>=.9
                                              for c in (original,*original.get('candidates',())))
                        tracked_conflict=any(c['text'] in TRACKED_LEVELS and c['text']!=value
                                             and c['confidence']>=.9 for view in masked_observations
                                             for c in (view,*view.get('candidates',())))
                        # 原始完整数字冲突不能覆盖；仅扩边中非目标等级的冲突可另行取证。
                        if not original_conflict and not tracked_conflict:
                            import subprocess
                            from .vision import read_regions
                            try:
                                secondary=read_regions(path,{'level':color_regions[key]},language='en-US')['level']
                                proof={'engine':'windows','text':secondary,'crop':color_regions[key],
                                       'accepted':secondary==value,'confidence':None}
                                conflicts=secondary!=value
                            except (RuntimeError,OSError,ValueError,subprocess.SubprocessError) as exc:
                                proof={'engine':'windows','accepted':False,'error':str(exc),'confidence':None}
                            original['secondary_level_evidence']=proof
                    if value in TRACKED_LEVELS and value==wider[key] and not conflicts:
                        result[0][key]=value
                        result[1][key]={**color_proof[key],
                                        'recovery':('secondary_color_consensus' if original.get('secondary_level_evidence',{}).get('accepted')
                                                    else 'original_color_consensus'),
                                        'original':original}
        if _retry and _vertical_retry:
            # 数字下沿被行定位误差裁掉时，只提出两个新裁切；不补笔画或降低置信度。
            pending={}
            for key,box in regions.items():
                proof=result[1][key]
                sources=[proof,*proof.get('margin_retries',{}).values(),*proof.get('color_retries',{}).values()]
                observed={c['text'] for item in sources for c in item.get('candidates',())
                          if re.fullmatch(r'\d{2,3}',c['text']) and c['confidence']>=.9}
                observed.update(item['text'] for item in sources if item.get('accepted')
                                and item.get('confidence',0)>=.9 and re.fullmatch(r'\d{2,3}',item.get('text','')))
                crop=preparation[key]['crop']
                ink=int(np.count_nonzero(canvas[crop[1]:crop[3],crop[0]:crop[2]]==255))
                if (result[0][key] not in TRACKED_LEVELS and ink>=12
                        and len(observed)<=1 and observed.issubset(TRACKED_LEVELS)):
                    pending[key]=box
            if pending:
                shift=max(1,round(2*pixels.shape[0]/720))
                shifted={}
                for name,delta in (('down2',shift),('down3',shift+1)):
                    boxes={key:(box[0],box[1]+delta,box[2],box[3]+delta)
                           for key,box in pending.items() if box[3]+delta<=pixels.shape[0]}
                    shifted[name]=_read_levels(path,boxes,True,_vertical_retry=False) if boxes else ({},{})
                for key in pending:
                    original=result[1][key]
                    original['vertical_retries']={name:proof[key] for name,(_,proof) in shifted.items() if key in proof}
                    value=shifted['down2'][0].get(key)
                    # 原裁切、水平扩边和原色复核中的高置信度完整数字冲突都不能覆盖。
                    sources=[original,*original.get('margin_retries',{}).values(),
                             *original.get('color_retries',{}).values()]
                    conflict=any(re.fullmatch(r'\d{2,3}',c['text']) and c['text']!=value and c['confidence']>=.9
                                 for proof in sources for c in proof.get('candidates',()))
                    if value in TRACKED_LEVELS and value==shifted['down3'][0].get(key) and not conflict:
                        result[0][key]=value
                        result[1][key]={**shifted['down2'][1][key],
                                        'recovery':'independent_vertical_consensus','original':original}
        return result if evidence else result[0]


def inspect_inventory(screen, read_numbers=None, read_badges=None, *, ignore_levels=False):
    if screen.page not in {'inventory_batch_selection','inventory_batch_selection_empty'}:
        raise ValueError('未确认背包批量选择页面')
    with Image.open(screen.source) as source:
        if abs(source.width / source.height - 16 / 9) > .02:
            raise ValueError('选装识别需要完整16:9截图')
        width, height = source.size
        image = source.convert('RGB').resize((1661, 933))
    counts = [int(match[1]) for word in screen.words
              if word['confidence'] >= .9 and (match := re.fullmatch(r'批量强化\((\d+)\)', word['text']))]
    mode_evidence = None
    count_evidence = None
    if screen.page == 'inventory_batch_selection_empty':
        from .inventory_mode_vision import inspect_zero_selection
        mode_evidence = inspect_zero_selection(screen.source,screen.words)
        counts = [mode_evidence['selected_count']]
    if len(counts) != 1 or not 0 <= counts[0] <= 16:
        # 低置信度全图文字只能提出局部读取候选，不能直接作为计数。
        pending=[word for word in screen.words if .8<=word['confidence']<.9
                 and 1000<=word['center'][0]<1250 and 630<=word['center'][1]<710
                 and re.fullmatch(r'批量强化\((?:[0-9]|1[0-6])\)',word['text'])]
        if not counts and len(pending)==1:
            from .local_ocr import read_local_regions
            regions={key:tuple(round(v*(width/1280 if i%2==0 else height/720)) for i,v in enumerate(box))
                     for key,box in {'count_outer':(1025,650,1205,696),
                                     'count_inner':(1040,657,1195,690)}.items()}
            values,details=read_local_regions(screen.source,regions)
            for key in regions:
                evidence=details[key]
                if (evidence.get('accepted') and evidence.get('confidence',0)>=.9
                        and re.fullmatch(r'批量强化\((?:[0-9]|1[0-6])\)',values.get(key,''))
                        and values[key]!=pending[0]['text']):
                    raise ValueError('局部批量计数与全图候选冲突')
            if not all(details[key].get('accepted') and details[key].get('confidence',0)>=.9
                       and values.get(key)==pending[0]['text'] for key in regions):
                raise InventoryObservationIncomplete('局部批量计数尚未形成双裁切共识，只可重读')
            counts=[int(re.fullmatch(r'批量强化\((\d+)\)',values['count_outer'])[1])]
            count_evidence={'accepted':True,'global_candidate':pending[0],'crops':details}
        else:
            raise ValueError('批量选择数量未唯一确认')
    from .inventory_tail_vision import inspect_tail
    tail = inspect_tail(screen)
    tail['row'] = None
    # 按等级字样定位行，可适应滚动后行位置变化；不使用固定页号推算坐标。
    anchors,merged_anchors,plain_anchor_columns = [],[],[]
    for word in screen.words:
        px, py = word['center'][0] * 1661 / 1280, word['center'][1] * 933 / 720
        # 全图检测可能将等级与相邻装备图案合并（如85元m）；仅借此提出行位置。
        # 每格等级仍必须由独立的局部OCR确认，绝不从这个前缀赋值。
        columns=[col for col in range(7) if abs(px-(213+128.5*col))<18]
        if 190<=py<=800 and len(columns)==1:
            if word['text'] in TRACKED_LEVELS and word['confidence']>=.9:
                anchors.append(py)
                plain_anchor_columns.append((py,columns[0]))
            elif (word['confidence']>=.7
                  and re.fullmatch(r'(85|88|90)[^\d]{1,4}',word['text'])):
                merged_anchors.append((py,columns[0]))
    # 合并文本的低置信度不作为等级证据；至少两列同高度才提出行候选。
    plain_anchors=tuple(anchors)
    anchors.extend(y for y,col in merged_anchors
                   if not any(abs(y-known_y)<=10 for known_y in plain_anchors)
                   and len({c for other_y,c in merged_anchors if abs(other_y-y)<=10})>=2)
    groups = []
    for y in sorted(anchors):
        if not groups or abs(y - median(groups[-1])) > 10:
            groups.append([y])
        else:
            groups[-1].append(y)
    rows = [round(median(group) - 14) for group in groups
            if 190 <= median(group) - 14
            and median(group) - 14 + 150 <= 815]
    if ignore_levels:
        from .inventory_grid_vision import locate_rows
        try:
            rows=locate_rows(screen.source,tail)
        except ValueError as exc:
            raise InventoryObservationIncomplete(str(exc)) from exc
    def confirm_local_row(candidate,prefix):
        boxes={}
        if ignore_levels:
            # 默认模式只接受上方独立图形定位的行，绝不回退等级/属性OCR。
            return False
        for col in range(7):
            x=196+round(col*128.5)
            boxes[f'{prefix}_{col}']=tuple(round(v*(width/1661 if i%2==0 else height/933))
                for i,v in enumerate((x-2,candidate,x+33,candidate+32)))
        values=(_read_levels(screen.source,boxes) if read_numbers is None
                else read_numbers(screen.source,boxes))
        return all(values.get(key) in TRACKED_LEVELS for key in boxes)
    if not rows:
        # 等级字样可能被整页检测全部漏掉。主属性数字只提出裁切位置，
        # 各行位置须互相印证，并逐格通过原有局部等级OCR，不能据布局填等级。
        numeric_groups=[]
        candidates=[]
        for word in screen.words:
            if word['confidence'] < .95 or not re.fullmatch(r'[1-9]\d*(?:,\d{3})*%?',word['text']):
                continue
            px,py=word['center'][0]*1661/1280,word['center'][1]*933/720
            columns=[col for col in range(7) if abs(px-(244+128.5*col))<18]
            if len(columns)==1 and 190<=py-123 and py-123+150<=815:
                candidates.append((py,columns[0]))
        for py,col in sorted(candidates):
            if not numeric_groups or abs(py-median([p[0] for p in numeric_groups[-1]]))>10:
                numeric_groups.append([])
            numeric_groups[-1].append((py,col))
        proposed=[round(median([p[0] for p in group])-123) for group in numeric_groups
                  if sorted(col for _,col in group)==list(range(7))]
        if len(proposed)!=3:
            # 主属性数字只定位行，不赋予等级：至少一行七列完整，另外两行
            # 各有四列且横跨五个列距；仍须随后把三行21个等级全部独立读出。
            sparse=[group for group in numeric_groups if len({col for _,col in group})>=4
                    and max(col for _,col in group)-min(col for _,col in group)>=5]
            if len(sparse)==3 and any(sorted(col for _,col in group)==list(range(7)) for group in sparse):
                proposed=[round(median([p[0] for p in group])-123) for group in sparse]
        if len(proposed)!=3 and len(numeric_groups)==3:
            # 全图可能三行都漏字：两侧行各六列且跨全宽，中间行至少四列。
            # 这仅提出几何候选；下方仍独立核验21个局部等级，不能补值。
            columns=[{col for _,col in group} for group in numeric_groups]
            if (all(len(columns[i])>=6 and max(columns[i])-min(columns[i])>=5 for i in (0,2))
                    and len(columns[1])>=4):
                proposed=[round(median([p[0] for p in group])-123) for group in numeric_groups]
        if (len(proposed)!=3 or not 190<=proposed[0]<=365
                or any(not 155<=b-a<=190 for a,b in zip(proposed,proposed[1:]))):
            raise InventoryObservationIncomplete('没有确认完整可见的装备等级行，不能视为背包已空')
        if not all(confirm_local_row(y,f'level_numeric_anchor_{i}') for i,y in enumerate(proposed)):
            raise InventoryObservationIncomplete('主属性网格已定位，但局部等级未全部确认')
        rows=proposed
    if rows[0] > 365:
        recovered=False
        candidate=None
        if len(rows)==1 and rows[0]>537:
            # 只剩最下方等级锚点时，上面两行均须有宽主属性网格、至少一行七列，
            # 并逐格独立读出14个等级；不能只恢复中间行而遗漏最上方一行。
            leading=[rows[0]-344,rows[0]-172]
            complete=True
            full_row=False
            for proposed in leading:
                columns=set()
                for word in screen.words:
                    if word['confidence']<.95 or not re.fullmatch(r'[1-9]\d*(?:,\d{3})*%?',word['text']):
                        continue
                    px,py=word['center'][0]*1661/1280,word['center'][1]*933/720
                    if abs(py-(proposed+123))<=10:
                        columns.update(col for col in range(7) if abs(px-(244+128.5*col))<18)
                full_row=full_row or columns==set(range(7))
                complete=complete and len(columns)>=4 and max(columns)-min(columns)>=5
            if (190<=leading[0]<=365 and complete and full_row
                    and all(confirm_local_row(y,f'level_two_leading_{i}') for i,y in enumerate(leading))):
                rows=leading+rows
                recovered=True
        if len(rows)==2 and 155<=rows[1]-rows[0]<=190:
            candidate=2*rows[0]-rows[1]
        elif len(rows)==1:
            # 中间行有两个等级锚点，或上一行四列主属性数字跨越至少五个列距，
            # 才复用已标定行距提出上方裁切。数字仅作位置证据，七个等级仍分别读取。
            proposed=rows[0]-172
            main_columns=set()
            for word in screen.words:
                if word['confidence']<.95 or not re.fullmatch(r'[1-9]\d*(?:,\d{3})*%?',word['text']):
                    continue
                px,py=word['center'][0]*1661/1280,word['center'][1]*933/720
                if abs(py-(proposed+123))<=10:
                    main_columns.update(col for col in range(7) if abs(px-(244+128.5*col))<18)
            level_columns={col for py,col in plain_anchor_columns if abs(py-14-rows[0])<=10}
            if len(level_columns)>=2 or (level_columns and len(main_columns)>=4
                                        and max(main_columns)-min(main_columns)>=5):
                candidate=proposed
        if candidate is not None and 190<=candidate<=365 and confirm_local_row(candidate,'level_leading_anchor'):
            rows.insert(0,candidate)
            recovered=True
        if not recovered:
            raise InventoryObservationIncomplete('顶部可见行锚点缺失，不能从后续行开始跳选')
    if tail['end_verified'] and tail['tail_count'] is not None:
        candidates = ([y for y in rows if abs((y-7)*720/933-tail['row_top'])<=8] if 'row_top' in tail else
                      [y for y in rows if y>760] if ignore_levels else [round(median(group)-14) for group in groups
                      if abs((median(group)-14)*720/933-604) <= 8])
        if len(candidates)==1:
            if candidates[0] in rows:
                tail['row']=rows.index(candidates[0])
            elif not rows or candidates[0]>rows[-1]:
                tail['row']=len(rows)
                rows.append(candidates[0])
    if any(not 155 <= b-a <= 190 for a,b in zip(rows,rows[1:])):
        # 整页检测可能漏掉整行文字。间距仅用于提出裁切位置，不能赋予等级。
        # 仅恢复一个完整中间行，七格必须分别通过既有局部OCR共识。
        gaps=[(a,b) for a,b in zip(rows,rows[1:]) if not 155<=b-a<=190]
        recovered=False
        if len(gaps)==1 and 310<=gaps[0][1]-gaps[0][0]<=380 and tail['row'] is None:
            candidate=round(sum(gaps[0])/2)
            if confirm_local_row(candidate,'level_anchor'):
                rows=sorted([*rows,candidate])
                recovered=all(155<=b-a<=190 for a,b in zip(rows,rows[1:]))
        if not recovered:
            raise InventoryObservationIncomplete('可见行锚点存在间断，不能跳过未识别行')
    if len(rows)==2 and tail['row'] is None:
        candidate=rows[-1]+rows[-1]-rows[-2]
        # 整页OCR也可能漏掉最下面一整行；越出完整可见区域绝不尝试补行。
        if 190<=candidate and candidate+150<=815 and confirm_local_row(candidate,'level_trailing_anchor'):
            rows.append(candidate)
    if len(rows)==1 and tail['row'] is None:
        # 七列网格在1661×933参考画面中行距标定为172像素。
        # 整页OCR可能只定位第一行；行距只提出局部读取位置，绝不填写等级。
        # 必须仍在完整可见范围内，且新行七格等级全部独立接受。
        candidate=rows[0]+172
        while candidate+150<=815:
            if not confirm_local_row(candidate,'level_single_anchor_'+str(len(rows))):
                raise InventoryObservationIncomplete('单行定位后下方完整区域未确认，不能跳过装备')
            rows.append(candidate)
            candidate+=172
    regions = {}
    for row, y in enumerate(rows):
        columns = tail['tail_count'] if row == tail['row'] else 7
        for col in range(columns):
            x = 196 + round(col * 128.5)
            box = (x - 2, y, x + 33, y + 32)
            regions[f'level{row}_{col}'] = tuple(round(value * (width / 1661 if i % 2 == 0 else height / 933))
                                                  for i, value in enumerate(box))
    if ignore_levels:
        numbers,level_evidence = {},{'scope':'not_requested'}
    elif read_numbers is None:
        numbers,level_evidence = _read_levels(screen.source,regions,evidence=True)
    else:
        numbers,level_evidence = read_numbers(screen.source,regions),{}
    records = []
    badge_evidence = {}
    for row, y in enumerate(rows):
        columns = tail['tail_count'] if row == tail['row'] else 7
        for col in range(columns):
            x = 196 + round(col * 128.5)
            tick = np.asarray(image.crop((x + 20, y + 45, x + 65, y + 85))).astype(float)
            tr, tg, tb = (tick[:, :, i] for i in range(3))
            green = ((tg > 100) & (tg > tr * 1.2) & (tg > tb * 1.4)).mean()
            selected = True if green >= .08 else False if green < .01 else None
            pixels = np.asarray(image.crop((x + 85, y + 7, x + 94, y + 42))).astype(float)
            r, g, b = (pixels[:, :, i] for i in range(3))
            purple = ((r > 25) & (r > g * 1.6) & (b > r * .35) & (b > g * 1.5)).mean()
            red = ((r > 25) & (r > g * 1.6) & (r > b * 3)).mean()
            rarity = 'purple' if purple > .35 and purple > red * 1.4 else 'red' if red > .35 and red > purple * 1.4 else None
            rarity_evidence={'body_purple':round(float(purple),4),'body_red':round(float(red),4),
                             'source':'body' if rarity else None}
            if rarity is None:
                # 右侧主体可能被流动光效盖住；下框光晕独立确认，不从未知猜品质。
                frame=np.asarray(image.crop((x+6,y+100,x+76,y+105))).astype(float)
                r,g,b=(frame[:,:,i] for i in range(3))
                fp=((r>25)&(r>g*1.6)&(b>r*.35)&(b>g*1.5)).mean()
                fr=((r>25)&(r>g*1.6)&(r>b*3)).mean()
                rarity='purple' if fp>.35 and fp>fr*1.4 else 'red' if fr>.35 and fr>fp*1.4 else None
                rarity_evidence.update(frame_purple=round(float(fp),4),frame_red=round(float(fr),4),
                                       source='frame' if rarity else None)
            # 品质紫色光晕位于金色卡框之外；分成两段，避免内部红色图案误判红装。
            glow=[]
            for start,end in ((10,35),(40,65)):
                patch=image.crop((x+101,y+start,x+104,y+end))
                if selected is True:
                    patch=ImageEnhance.Brightness(patch).enhance(2.5)
                edge=np.asarray(patch).astype(float)
                er,eg,eb=(edge[:,:,i] for i in range(3))
                glow.append(float(((er>eg*1.25)&(eb>eg*1.8)&(eb>er*1.25)&(eb>60)).mean()))
            rarity_evidence['outer_purple_glow']=glow
            if rarity=='red' and any(value>.1 for value in glow):
                rarity=None
                rarity_evidence['source']=None
            if rarity!='purple' and all(value>.6 for value in glow):
                rarity='purple'
                rarity_evidence['source']='outer_purple_glow'
            if rarity is None and all(value<=.1 for value in glow):
                # 白金色刀刃可遮挡右侧；顶部与左上内角须独立给出同一品质。
                # 两个不相交区域均需更高颜色占比，不以降低主体门槛恢复未知。
                votes=[]
                for name,box in (
                        # 排除最上两像素中性外框，只取原区域内的背景色；
                        # 与左内角仍须独立通过同一颜色占比门槛。
                        ('top',(x+35,y+2,x+70,y+7)),
                        ('left_corner',(x+5,y+18,x+13,y+32))):
                    border=np.asarray(image.crop(box)).astype(float)
                    r,g,b=(border[:,:,i] for i in range(3))
                    bp=((r>25)&(r>g*1.6)&(b>r*.35)&(b>g*1.5)).mean()
                    br=((r>25)&(r>g*1.6)&(r>b*3)).mean()
                    vote=('purple' if bp>.55 and bp>br*1.4 else
                          'red' if br>.55 and br>bp*1.4 else None)
                    votes.append(vote)
                    rarity_evidence.update({f'border_{name}_purple':round(float(bp),4),
                                            f'border_{name}_red':round(float(br),4)})
                if votes[0] is not None and votes[0]==votes[1]:
                    rarity=votes[0]
                    rarity_evidence['source']='border_consensus'
            if rarity is None and selected is True and all(value<=.1 for value in glow):
                # 勾选遮罩压暗背景，两个独立内框恢复亮度后仍须满足原颜色占比。
                votes=[]
                for name,box in (('top',(x+35,y+2,x+70,y+7)),
                                 ('left_corner',(x+5,y+18,x+13,y+32))):
                    border=np.asarray(ImageEnhance.Brightness(image.crop(box)).enhance(2.5)).astype(float)
                    r,g,b=(border[:,:,i] for i in range(3))
                    bp=((r>25)&(r>g*1.6)&(b>r*.35)&(b>g*1.5)).mean()
                    br=((r>25)&(r>g*1.6)&(r>b*3)).mean()
                    votes.append('purple' if bp>.55 and bp>br*1.4 else
                                 'red' if br>.55 and br>bp*1.4 else None)
                    rarity_evidence.update({f'selected_border_{name}_purple':round(float(bp),4),
                                            f'selected_border_{name}_red':round(float(br),4)})
                if votes[0] is not None and votes[0]==votes[1]:
                    rarity=votes[0]
                    rarity_evidence['source']='selected_border_consensus'
            badge_image = image.crop((x + 65, y - 14, x + 117, y + 26))
            badge = np.asarray(badge_image).astype(float)
            r, g, b = (badge[:, :, i] for i in range(3))
            orange_mask=((r > 160) & (g > 65) & (g < 180) & (b < 85) & (r > g * 1.2)).astype('uint8')
            brightness_gain = 1
            if selected is True and orange_mask.mean() < .08:
                # 勾选遮罩会同时压暗徽标。恢复亮度后仍使用同一颜色和OCR门槛，
                # 不把前一帧的等级带入当前观测，也不将识别失败回填为+0。
                brightness_gain = 2.5
                badge = np.asarray(ImageEnhance.Brightness(badge_image).enhance(brightness_gain)).astype(float)
                r, g, b = (badge[:, :, i] for i in range(3))
                orange_mask=((r > 160) & (g > 65) & (g < 180) & (b < 85) & (r > g * 1.2)).astype('uint8')
            orange = orange_mask.mean()
            import cv2
            _,_,components,_=cv2.connectedComponentsWithStats(orange_mask,connectivity=8)
            # 徽标位于裁框上半部；下沿红装图案（如头盔尖角）被选中亮度恢复后
            # 也可能变橙，不能把仅从下半部开始的图案当成未读出的强化徽标。
            badge_components=[c[cv2.CC_STAT_AREA] for c in components[1:]
                              if c[cv2.CC_STAT_TOP]<orange_mask.shape[0]//2]
            orange_component=(max(badge_components,default=0)/orange_mask.size)
            badge_words = [int(match[1]) for word in screen.words
                           if word['confidence'] >= .9 and (match := re.fullmatch(r'\+(\d{1,2})', word['text']))
                           and x + 65 <= word['center'][0] * 1661 / 1280 < x + 117
                           and y - 14 <= word['center'][1] * 933 / 720 < y + 26]
            enhancement = (badge_words[0] if orange >= .08 and len(badge_words) == 1
                           and 1 <= badge_words[0] <= 15 else 0 if orange_component <= .025 and not badge_words else None)
            if enhancement is None and orange >= .08 and not badge_words:
                key=f'badge{row}_{col}'
                native=tuple(round(value*(width/1661 if i%2==0 else height/933))
                             for i,value in enumerate((x+65,y-14,x+117,y+26)))
                graph=None
                if read_badges is None and selected is True:
                    from .inventory_badge_vision import inspect_selected_three
                    graph=inspect_selected_three(screen.source,native)
                if read_badges is None and not (graph and graph['accepted']):
                    from .inventory_badge_vision import inspect_numbered_inventory_badge
                    graph=inspect_numbered_inventory_badge(screen.source,native)
                if graph and graph['accepted']:
                    values={key:str(graph['enhancement'])}
                    badge_evidence[key]=graph
                elif read_badges is None:
                    from .local_ocr import read_local_regions
                    if brightness_gain == 1:
                        values,evidence=read_local_regions(screen.source,{key:native})
                    else:
                        with Image.open(screen.source) as original:
                            restored=ImageEnhance.Brightness(original.convert('RGB').crop(native)).enhance(brightness_gain)
                        with tempfile.TemporaryDirectory(prefix='e7-selected-badge-') as directory:
                            target=Path(directory)/'badge.png'
                            restored.save(target)
                            values,evidence=read_local_regions(target,{key:(0,0,*restored.size)})
                        evidence[key]['preparation']={'source':screen.source,'native_crop':native,
                                                      'brightness_gain':brightness_gain}
                    badge_evidence[key]=evidence[key]
                else:
                    values=read_badges(screen.source,{key:native})
                match=re.fullmatch(r'\+?([1-9]|1[0-5])',values.get(key,''))
                if match:
                    enhancement=int(match[1])
            level = TRACKED_LEVELS.get(numbers.get(f'level{row}_{col}'))
            known = rarity is not None and (ignore_levels or level is not None) and enhancement is not None and selected is not None
            # 仅用于同一画面点击前复核，不能当作跨排序/跨滚动的唯一装备ID。
            signature = hashlib.sha256(image.crop((x, y + 4, x + 60, y + 43)).tobytes()).hexdigest()
            vector = np.asarray(image.crop((x, y + 4, x + 60, y + 43)).convert('L').resize((24, 16))).astype(float).ravel()
            vector -= vector.mean()
            norm = float(np.linalg.norm(vector))
            vector = (vector / norm).tolist() if norm else []
            center=(round((x+48)*1280/1661),round((y+65)*720/933))
            tracking=({'tracking_source':screen.source,
                       'tracking_box':(153+99*col,center[1]-50,226+99*col,center[1]+48)}
                      if (width,height)==(1280,720) else {})
            records.append({'row': row, 'column': col, 'center': center, 'rarity': rarity, 'level': level,
                            'enhancement': enhancement, 'selected': selected, 'signature': signature,
                            'identity_vector': vector,
                            'identity_box':(x,y+4,x+60,y+43),
                            'eligible': known and (ignore_levels or level == 85) and enhancement < 15, 'known': known,
                            'orange_ratio': round(float(orange), 4), 'green_ratio': round(float(green), 4),
                            'orange_component_ratio':round(float(orange_component),4),
                            'rarity_evidence':rarity_evidence,
                            **tracking})
    context_evidence={}
    context = inventory_context(screen,context_evidence)
    return {'page': screen.page, 'source': screen.source, 'selected_count': counts[0],
            **({'level_scope':'ignored'} if ignore_levels else {}),
            'mode_evidence':mode_evidence,
            'count_evidence':count_evidence,
            'tail_layout':tail,
            'level_evidence':level_evidence,
            'badge_evidence':badge_evidence,
            'inventory_context':context,
            'context_evidence':context_evidence,
            'cards': records, 'scan_complete': False,
            'notice': '仅完整可见行；未确认滚动终点，不能据此判定没有剩余+0～+14候选装备'}
