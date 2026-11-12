"""背包只选装模式：原生勾选状态与整行静止取证，属性留到批量页。"""
import math

from .inventory_tracking import inspect_tracking
from .selection_features import stationary_features


class IncompleteSelectionState(ValueError):
    """允许有限只读重试，不允许重复输入。"""


def verify_selection_state(before,after,target=None,selected=True):
    pages={'inventory_batch_selection','inventory_batch_selection_empty'}
    if before.get('page') not in pages or after.get('page') not in pages:
        raise ValueError('选装核验页面变化')
    if (not before.get('inventory_context') or before.get('inventory_context')!=after.get('inventory_context')
            or before.get('level_scope')!=after.get('level_scope')):
        raise ValueError('选装核验背包、排序或识别口径变化')
    delta=(1 if selected else -1) if target is not None else 0
    count=before.get('selected_count')
    if type(count) is not int or after.get('selected_count')!=count+delta:
        raise ValueError('选装核验计数变化不符，禁止重复点击')
    old,new=before.get('cards',[]),after.get('cards',[])
    if not old or len(old)!=len(new):raise IncompleteSelectionState('选装卡片数量未稳定')
    def compact(report):
        tail=report.get('tail_layout',{})
        return (tail.get('method')=='calibrated_compact_list' and tail.get('end_verified') is True
                and tail.get('row')==0 and tail.get('tail_count')==len(old)
                and all(card['row']==0 and abs(card['center'][1]-211)<=2 for card in report['cards']))
    groups={};targets=0
    fields=('row','column','rarity','enhancement')
    for a,b in zip(old,new):
        if any(a.get(k) is None or b.get(k) is None for k in fields):
            raise IncompleteSelectionState('选装已确认字段暂时缺失')
        if any(a[k]!=b[k] for k in fields):raise ValueError('选装位置或已确认字段变化')
        if before.get('level_scope')!='ignored' and a.get('level')!=b.get('level'):
            raise ValueError('选装已确认装备等级变化')
        position=(a['row'],a['column']);is_target=position==target
        targets+=is_target
        if is_target and a.get('selected') is not (not selected):
            raise ValueError('选装目标原勾选状态与操作不符')
        expected=selected if is_target else a.get('selected')
        if type(expected) is not bool or b.get('selected') is not expected:
            raise ValueError('选装勾选集合变化不符')
        points=(a.get('center'),b.get('center'));boxes=(a.get('tracking_box'),b.get('tracking_box'))
        if (any(not p or len(p)!=2 for p in points) or any(not p or len(p)!=4 for p in boxes)
                or any(type(v) is not int for p in (*points,*boxes) for v in p)):
            raise IncompleteSelectionState('选装几何取证缺失')
        dx,dy=(v-u for u,v in zip(*points))
        if dx!=0 or abs(dy)>4 or tuple(v-u for u,v in zip(*boxes))!=(0,dy,0,dy):
            raise IncompleteSelectionState('选装行位置未稳定')
        groups.setdefault(a['row'],[]).append((a,b,is_target,dy))
    if target is not None and targets!=1:raise ValueError('选装目标位置未唯一确认')
    full_rows=0
    for group in groups.values():
        if [a['column'] for a,b,t,dy in group]!=list(range(len(group))) or len(group)>7:
            raise ValueError('选装行列排列不完整')
        peers=[pair for pair in group if not pair[2]]
        required=len(peers)//2+1 if peers else 0
        proven=0
        for a,b,_,dy in peers:
            proof=inspect_tracking(a,b,search_margin=6) if abs(dy)==4 else inspect_tracking(a,b)
            offset=proof.get('offset')
            if (not offset or len(offset)!=2 or not all(math.isfinite(v) for v in offset)
                    or abs(offset[0])>.25 or abs(offset[1]+dy)>.25):continue
            if proof['matched'] or stationary_features(a,b)['matched']:
                proven+=1
            if proven>=required:break
        if proven<required:raise IncompleteSelectionState('整行静止取证不足，只能重读')
        full_rows+=len(group)==7
    if not full_rows:
        if not compact(before) or not compact(after):
            raise IncompleteSelectionState('尚无完整七列行或已核验短列表证明视口静止')
        if target is not None:
            from .batch_selection import BatchSelectionDriver
            a,b=next((a,b) for a,b in zip(old,new) if (a['row'],a['column'])==target)
            if (abs(a['center'][1]-b['center'][1])>1 or
                    not BatchSelectionDriver._target_icon_content_unchanged(a,{**b,'identity_box':a.get('identity_box')})):
                raise IncompleteSelectionState('短列表目标原坐标图像未确认，只能重读')
