"""紫装速度专读：不读取总分及其他副属性，不把未读字段补成零。"""
from dataclasses import asdict, replace
import re
from PIL import Image

from .batch_vision import _rarity, _is_level85, match_icon, _raw_stat_value, _stat_crop_consensus,read_badge_level
from .local_ocr import read_local_regions,stat_number_box
from .lock_vision import inspect_batch_lock, matches_locked_level
from .slot_vision import inspect_slots


def inspect_purple_speed_batch(screen, expected, speed_rows, verified_level_anchors, inference=None, *, ignore_levels=False):
    with Image.open(screen.source) as source:
        raw=source.convert('RGB')
        reference=raw.resize((1661,933))
    slots=inspect_slots(reference,registered_rarities={i:item.equipment.rarity for i,item in enumerate(expected)})
    if [slot['state'] for slot in slots] != ['occupied']*len(expected)+['empty']*(16-len(expected)):
        raise ValueError('速度专读的占用槽位与登记不符')
    # 固定字段直接做数字识别；不为速度专读运行整页文字检测。
    detections=None
    regions,metadata={},{}
    def native(box):
        return tuple(round(v*(screen.width/1661 if i%2==0 else screen.height/933)) for i,v in enumerate(box))
    for index,item in enumerate(expected):
        row,col=divmod(index,4)
        dx,dy=round(col*316.667),round(row*167.333)
        if item.equipment.rarity!='purple' or slots[index]['rarity']!='purple':
            raise ValueError('速度专读仅用于已核对的紫装')
        lock=inspect_batch_lock(reference,'batch_enhancement',index,True)
        anchored=(not ignore_levels and lock['locked'] is True and index in verified_level_anchors
                  and matches_locked_level(raw,verified_level_anchors[index],index))
        if not ignore_levels and not anchored and not _is_level85(reference.crop((34+dx,182+dy,68+dx,210+dy))):
            regions[f'level{index}']=native((33+dx,182+dy,64+dx,210+dy))
        speed_row=speed_rows.get(index)
        if type(speed_row) is not int or not 0<=speed_row<4:
            raise ValueError('速度专读缺少有效的本批速度行登记')
        name,_=match_icon(reference.crop((144+dx,212+dy+speed_row*28,174+dx,237+dy+speed_row*28)))
        if name!='speed':
            raise ValueError('登记的速度行图标发生变化')
        y=211+dy+speed_row*28
        regions[f'stat{index}_speed']=stat_number_box(native((177+dx,y,325+dx,y+27)))
        regions[f'badge{index}']=native((100+dx,164+dy,144+dx,201+dy))
        x,y=20+dx,166+dy
        selected=any(sum(b>100 and g>90 and b>r*1.1 for r,g,b in
                         reference.crop((x+20,by,x+275,by+1)).getdata())/255>.6 for by in range(y-4,y+6))
        metadata[index]=(lock,selected)
    values,details=read_local_regions(screen.source,regions,detections=detections,_inference=inference)
    rejected={key:box for key,box in regions.items() if key.startswith('stat')
              and not re.fullmatch(r'[1-9]\d?',values.get(key,''))}
    if rejected:
        wider={key:(max(0,box[0]-2),*box[1:]) for key,box in rejected.items()}
        more,expanded=read_local_regions(screen.source,wider,detections=detections,_inference=inference)
        for key,value in more.items():
            if re.fullmatch(r'[1-9]\d?',value):
                values[key]=value
        shifted={key:(box[0]+2,*box[1:]) for key,box in rejected.items()
                 if not values.get(key) and _raw_stat_value(details[key])
                 and _raw_stat_value(details[key])==_raw_stat_value(expanded[key])}
        if shifted:
            _,third=read_local_regions(screen.source,shifted,detections=detections,_inference=inference)
            for key in shifted:
                consensus=_stat_crop_consensus(details[key],expanded[key],third[key])
                if consensus:
                    values[key]=consensus
    records=[]
    for index,item in enumerate(expected):
        lock,selected=metadata[index]
        if f'level{index}' in regions and values[f'level{index}']!='85':
            raise ValueError('速度专读未确认85级装备')
        row,col=divmod(index,4)
        dx,dy=round(col*316.667),round(row*167.333)
        try:
            enhancement=read_badge_level(reference,dx,dy,values[f'badge{index}'])
        except ValueError as exc:
            from .batch_badge_vision import read_numbered_badge
            evidence=read_numbered_badge(reference.crop((100+dx,168+dy,140+dx,195+dy)))
            if not evidence:
                raise ValueError(f'第{index+1}件强化徽标未可靠读取') from exc
            enhancement=evidence['value']
            details[f'badge{index}']={'original_rejection':details.get(f'badge{index}'),**evidence}
        if speed_rows[index]==3 and enhancement<12:
            raise ValueError('登记速度行不属于当前强化阶段的已解锁词条')
        speed=values[f'stat{index}_speed']
        if not re.fullmatch(r'[1-9]\d?',speed):
            raise ValueError(f'第{index+1}件速度未可靠读取：{speed!r}')
        equipment=replace(item.equipment,enhancement=enhancement,stats={'speed':int(speed)},
                          game_score=None,observation_scope='purple_speed')
        records.append({'index':index,'equipment':asdict(equipment),'selected':selected,'locked':lock['locked']})
    return {'records':records,'slots':slots,'issues':[],'ocr_details':details,'scope':'purple_speed'}
