"""滚动前后用完整重叠行追踪覆盖；图标相似不等于唯一装备ID。"""
from dataclasses import dataclass
import math


def rows(report):
    grouped = {}
    for card in report['cards']:
        grouped.setdefault(card['row'], []).append(card)
    result = [sorted(grouped[key], key=lambda card: card['column']) for key in sorted(grouped)]
    tail = report.get('tail_layout',{})
    if not result:
        raise ValueError('滚动覆盖缺少装备行，不能当作空背包')
    for index,row in enumerate(result):
        count = 7
        if index == len(result)-1 and row[0]['row'] == tail.get('row'):
            count = tail.get('tail_count')
            if type(count) is not int or not 1 <= count <= 7:
                raise ValueError('尾行数量未确认')
        if [card['column'] for card in row] != list(range(count)):
            raise ValueError('滚动覆盖追踪需要完整行或图形已验证的尾行')
    if any(len(row) != 7 for row in result[:-1]):
        raise ValueError('滚动覆盖追踪需要完整七列行；不把残缺行当作已扫描')
    return result


def same_row(a, b, ignore_levels=False):
    if len(a) != len(b):
        return False
    for old, new in zip(a, b):
        fields=('rarity','enhancement','selected') if ignore_levels else ('level','rarity','enhancement','selected')
        if any(old[key] is None or new[key] is None for key in fields):
            return False
        if any(old[key] != new[key] for key in ('column',*fields)):
            return False
        if old.get('tracking_source') or new.get('tracking_source'):
            from .inventory_tracking import inspect_tracking
            if not inspect_tracking(old,new)['matched']:
                return False
            continue
        x, y = old['identity_vector'], new['identity_vector']
        if (not x or len(x) != len(y) or not all(math.isfinite(v) for v in (*x,*y))
                or sum(i*j for i,j in zip(x,y)) < .995):
            return False
    return True


def scroll_distance(report):
    """按当前三行位置校准手势；只决定视口位置，不证明滚动或覆盖。"""
    from statistics import median
    grouped=rows(report)
    if len(grouped)!=3 or any(len(row)!=7 for row in grouped):
        raise ValueError('滚动前需要三行完整定位，以保留两行重叠')
    centers=[]
    for row in grouped:
        points=[card.get('center') for card in row]
        if any(not p or len(p)!=2 or any(type(v) is not int for v in p) for p in points):
            raise ValueError('滚动行坐标未确认')
        if (any(not (0<=x<1280 and 130<=y-50 and y+48<=604) for x,y in points)
                or any(not 90<=b[0]-a[0]<=110 for a,b in zip(points,points[1:]))
                or max(p[1] for p in points)-min(p[1] for p in points)>1):
            raise ValueError('滚动行几何超出完整卡片标定范围')
        centers.append(median(p[1] for p in points))
    pitches=[b-a for a,b in zip(centers,centers[1:])]
    if any(not 120<=p<=145 for p in pitches) or max(pitches)-min(pitches)>3:
        raise ValueError('滚动行距未确认')
    # 实测135px手势约移动124px，144px约移动133px。校正首行中心至250px，
    # 给上下裁切留下余量；误差由下一次真实观测修正，不能凭此填写位移。
    return max(60,min(160,round(median(pitches)+11+centers[0]-250)))


def _coherent_vertical_overlap(old,new,offset,ignore_levels=False):
    """仅滚动恢复：至少两整行全部匹配，每行七格的垂直修正须一致。"""
    from .inventory_tracking import inspect_tracking
    overlap=min(len(old)-offset,len(new))
    if overlap<2:
        return False
    for a,b in zip(old[offset:offset+overlap],new[:overlap]):
        corrections=[]
        if len(a)!=7 or len(b)!=7:
            return False
        for x,y in zip(a,b):
            fields=('column','rarity','enhancement','selected') if ignore_levels else ('column','level','rarity','enhancement','selected')
            if any(x[k] is None or x[k]!=y[k] for k in fields):
                return False
            boxes=(x.get('tracking_box'),y.get('tracking_box'))
            if any(not box or len(box)!=4 or (box[2]-box[0],box[3]-box[1])!=(73,98) for box in boxes):
                return False
            vectors=(x.get('identity_vector'),y.get('identity_vector'))
            if (not all(vectors) or len(vectors[0])!=len(vectors[1])
                    or not all(math.isfinite(v) for vector in vectors for v in vector)):
                return False
            proof=inspect_tracking(x,y,search_margin=6)
            delta=proof.get('offset')
            if (not proof['matched'] or not delta or abs(delta[0])>.25 or abs(delta[1])>6):
                return False
            corrections.append(delta[1])
        if max(corrections)-min(corrections)>.5:
            return False
    return True


def missing_overlap_offset(before,after):
    """仅授权原地重读，不证明位移；完整字段恢复后仍须advance验证。"""
    if (before.get('inventory_context')!=after.get('inventory_context')
            or before['selected_count']!=after['selected_count']):
        return None
    old,new=rows(before),rows(after)
    fields=('rarity','enhancement','selected') if before.get('level_scope')==after.get('level_scope')=='ignored' else ('level','rarity','enhancement','selected')
    from .inventory_tracking import inspect_tracking
    candidates=[]
    for offset in range(len(old)):
        overlap=min(len(old)-offset,len(new))
        if overlap<2:
            continue
        valid,missing=True,False
        for a,b in zip(old[offset:offset+overlap],new[:overlap]):
            for x,y in zip(a,b):
                if len(a)!=len(b) or x['column']!=y['column']:
                    valid=False
                    break
                lost=False
                for key in fields:
                    if x[key] is None or (y[key] is not None and x[key]!=y[key]):
                        valid=False
                        break
                    lost=lost or y[key] is None
                if lost and (y['known'] is not False or y['eligible'] is not False):
                    valid=False
                missing=missing or lost
                vectors=(x.get('identity_vector'),y.get('identity_vector'))
                if (not all(vectors) or len(vectors[0])!=len(vectors[1])
                        or not all(math.isfinite(v) for vector in vectors for v in vector)
                        or not x.get('tracking_source') or not y.get('tracking_source')
                        or not inspect_tracking(x,y)['matched']):
                    valid=False
                if not valid:
                    break
            if not valid:
                break
        if valid:
            candidates.append((offset,missing))
    if len(candidates)==1 and candidates[0][0]>0 and candidates[0][1]:
        return candidates[0][0]
    return None


def unstable_overlap_offset(before,after,*,max_per_row=1):
    """只授权原地重拍：每行至多一卡片、共至多两张略不稳，其余通过原门槛。"""
    if type(max_per_row) is not int or max_per_row not in (1,2):
        raise ValueError('只允许一或两张近门槛卡片授权重拍/视口调整，不能证明覆盖')
    if (before.get('inventory_context')!=after.get('inventory_context')
            or before['selected_count']!=after['selected_count']):
        return None
    old,new=rows(before),rows(after)
    fields=('column','rarity','enhancement','selected') if before.get('level_scope')==after.get('level_scope')=='ignored' else ('column','level','rarity','enhancement','selected')
    from .inventory_tracking import inspect_tracking
    candidates=[]
    for offset in range(len(old)):
        overlap=min(len(old)-offset,len(new))
        if overlap<2:
            continue
        failed=0
        valid=True
        for a,b in zip(old[offset:offset+overlap],new[:overlap]):
            row_failed=0
            if len(a)!=7 or len(b)!=7:
                valid=False
                break
            for x,y in zip(a,b):
                vectors=(x.get('identity_vector'),y.get('identity_vector'))
                if (any(x[k] is None or x[k]!=y[k] for k in fields)
                        or not x.get('tracking_source') or not y.get('tracking_source')
                        or not all(vectors) or len(vectors[0])!=len(vectors[1])
                        or not all(math.isfinite(v) for vector in vectors for v in vector)):
                    valid=False
                    break
                proof=inspect_tracking(x,y)
                if not proof['matched']:
                    score,error=proof.get('score'),proof.get('mae')
                    if (score is None or error is None or not math.isfinite(score)
                            or not math.isfinite(error) or not .99<=score<=1 or not 0<=error<=5):
                        valid=False
                        break
                    failed+=1
                    row_failed+=1
                    if failed>2 or row_failed>max_per_row:
                        valid=False
                        break
            if not valid:
                break
        if valid:
            candidates.append((offset,failed))
    if len(candidates)==1 and candidates[0][0]>0 and 1<=candidates[0][1]<=2:
        return candidates[0][0]
    return None


def coherent_overlap_retry_offset(before,after):
    """两行一致位移、大多数严格匹配仅授权重读/微调，绝不证明覆盖。"""
    if (before.get('inventory_context')!=after.get('inventory_context')
            or before['selected_count']!=after['selected_count']):return None
    from .inventory_tracking import inspect_tracking
    old,new=rows(before),rows(after)
    fields=('column','rarity','enhancement','selected')
    if before.get('level_scope')!=after.get('level_scope'):return None
    if before.get('level_scope')!='ignored':fields+=('level',)
    candidates=[]
    for offset in range(1,len(old)):
        overlap=min(len(old)-offset,len(new))
        if overlap<2:continue
        failed=0;outliers=0;valid=True
        for a,b in zip(old[offset:offset+overlap],new[:overlap]):
            corrections=[];row_failed=0
            if len(a)!=7 or len(b)!=7:valid=False;break
            for x,y in zip(a,b):
                vectors=(x.get('identity_vector'),y.get('identity_vector'))
                if (not x.get('known') or not y.get('known')
                        or any(x.get(k) is None or x[k]!=y.get(k) for k in fields)
                        or not all(vectors) or len(vectors[0])!=len(vectors[1])
                        or not all(math.isfinite(v) for vector in vectors for v in vector)):
                    valid=False;break
                proof=inspect_tracking(x,y)
                delta=proof.get('offset');score=proof.get('score');error=proof.get('mae')
                if (not delta or len(delta)!=2 or score is None or error is None
                        or not all(math.isfinite(v) for v in (*delta,score,error))
                        or abs(delta[0])>.25 or abs(delta[1])>3):valid=False;break
                corrections.append(delta[1])
                if not proof['matched']:
                    failed+=1;row_failed+=1
                    outliers+=score<.99
                    if row_failed>3 or outliers>1 or not .98<=score<=1 or not 0<=error<=3:
                        valid=False;break
            if not valid or max(corrections)-min(corrections)>.5:
                valid=False;break
        if valid and failed>=1:candidates.append(offset)
    return candidates[0] if len(candidates)==1 else None


@dataclass
class InventoryTraversal:
    """base只是本次可见起点的相对行号，不声称起点就是整个背包顶部。"""
    base: int = 0
    covered_rows: int = 0
    moves: int = 0
    end_verified: bool = False
    partial_tail: bool = False
    top_verified: bool = False

    def start(self, report, top_anchor=None):
        self.base=self.moves=0
        self.end_verified=self.partial_tail=self.top_verified=False
        if top_anchor is not None:
            from .inventory_top_vision import verify_top_anchor
            self.top_verified=verify_top_anchor(top_anchor,report)
        self.covered_rows = len(rows(report))
        self.observe_end(report)

    def observe_end(self, report):
        grouped = rows(report)
        self.covered_rows=max(self.covered_rows,self.base+len(grouped))
        tail = report.get('tail_layout',{})
        # 看见滚动条底端但未读到尾行，不构成覆盖到末尾的证据。
        reached = (tail.get('end_verified') is True and tail.get('row') == grouped[-1][0]['row']
                   and tail.get('tail_count') == len(grouped[-1]))
        if reached:
            self.end_verified = True
            self.partial_tail = len(grouped[-1]) < 7
        return reached

    def advance(self, before, after):
        if before.get('level_scope')!=after.get('level_scope'):
            raise ValueError('滚动期间等级识别口径变化，不能拼接覆盖范围')
        ignore_levels=before.get('level_scope')=='ignored'
        if before.get('inventory_context') != after.get('inventory_context'):
            raise ValueError('滚动期间背包数量或排序文字变化，不能拼接覆盖范围')
        if before['selected_count'] != after['selected_count']:
            raise ValueError('滚动期间选择计数变化，不能拼接覆盖范围')
        old, new = rows(before), rows(after)
        # 至少两行正向重叠，避免单行相同装备造成跳页误拼接。
        offsets = [offset for offset in range(len(old))
                   if (overlap := min(len(old)-offset,len(new))) >= 2
                   and all(same_row(old[offset+i],new[i],ignore_levels) for i in range(overlap))]
        if not offsets:
            offsets=[offset for offset in range(len(old)) if _coherent_vertical_overlap(old,new,offset,ignore_levels)]
        if len(offsets) != 1:
            raise ValueError('滚动重叠行不唯一或不足，未猜测翻页距离')
        offset = offsets[0]
        if offset == 0:
            raise ValueError('未确认滚动位移；静止画面不能证明背包末尾')
        self.base += offset
        self.covered_rows = max(self.covered_rows, self.base+len(new))
        self.moves += 1
        self.observe_end(after)
        return offset

    def advance_with_features(self,before,after):
        """仅微调耗尽后的辅助路径；十三张严格匹配，一张由分散特征独立核验。"""
        from .inventory_tracking import inspect_tracking
        from .selection_features import aligned_card_features
        offset=coherent_overlap_retry_offset(before,after)
        if offset is None:raise ValueError('辅助特征未取得唯一完整重叠候选')
        old,new=rows(before),rows(after)
        overlap=min(len(old)-offset,len(new));fallbacks=0
        if any(not c.get('known') for row in new for c in row):
            raise ValueError('辅助特征不能补齐未知字段')
        for a,b in zip(old[offset:offset+overlap],new[:overlap]):
            for x,y in zip(a,b):
                proof=inspect_tracking(x,y)
                if proof['matched']:continue
                fallbacks+=1
                delta=proof.get('offset')
                if (fallbacks>1 or not delta or max(abs(v) for v in delta)>.25
                        or not aligned_card_features(x,y)['matched']):
                    raise ValueError('辅助特征不能核验唯一失配卡片')
        if fallbacks!=1:raise ValueError('辅助特征路径必须且仅补充一张卡片')
        self.base+=offset
        self.covered_rows=max(self.covered_rows,self.base+len(new))
        self.moves+=1
        self.observe_end(after)
        return offset

    def evidence(self):
        return {'relative_row':self.base,'covered_full_rows':self.covered_rows-int(self.partial_tail),
                'covered_rows':self.covered_rows,'last_row_partial':self.partial_tail,
                'verified_moves':self.moves,'top_verified':self.top_verified,'end_verified':self.end_verified}
