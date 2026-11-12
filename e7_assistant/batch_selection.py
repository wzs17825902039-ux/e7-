"""实际背包选装输入：一次点击后核对勾选与计数，不启动强化。"""
from .inventory_vision import inspect_inventory, InventoryObservationIncomplete
from .inventory_detail import read_detail,read_selection_header,UnsupportedEquipment
from dataclasses import asdict
from .inventory_scan import InventoryTraversal
from .rules import Policy
import time
from .selection_state import verify_selection_state,IncompleteSelectionState


class SelectionImageUnstable(ValueError):
    """状态字段已符合预期，但图像可能仍有选中闪光；只允许重读。"""


class BatchSelectionDriver:
    def __init__(self, navigator, reader=inspect_inventory, detail_reader=read_detail,
                 excluded_fingerprints=(), policy=None, protection=None,top_reader=None,navigation_reader=None,
                 recover_detail_levels=None,defer_details=None,excluded_positions=None):
        self.navigator, self.reader = navigator, reader
        effective_policy=policy or Policy()
        self.ignore_equipment_level=effective_policy.ignore_equipment_level
        self.excluded_positions=dict(excluded_positions or {})
        self.defer_details=(reader is inspect_inventory and detail_reader is read_detail and self.ignore_equipment_level
                            if defer_details is None else defer_details)
        if type(self.defer_details) is not bool:
            raise ValueError('批量页属性识别开关必须为布尔值')
        self.native_selection_state=self.defer_details and reader is inspect_inventory
        if reader is inspect_inventory and self.ignore_equipment_level:
            self.reader=lambda screen:inspect_inventory(screen,ignore_levels=True)
        self.detail_reader = (lambda screen,card:read_detail(screen,card,policy=effective_policy)
                              if detail_reader is read_detail else detail_reader(screen,card))
        self.top_reader = top_reader
        self.navigation_reader = navigation_reader or self._navigation_snapshot
        # 完整属性等价保护集合，不能把fingerprint当作游戏唯一ID。
        self.excluded_fingerprints = frozenset(excluded_fingerprints)
        self.policy, self.protection = policy, protection
        from .inventory_level_recovery import InventoryLevelRecovery
        enabled = reader is inspect_inventory if recover_detail_levels is None else recover_detail_levels
        if type(enabled) is not bool:
            raise ValueError('详情等级恢复开关必须为布尔值')
        self.level_recovery = InventoryLevelRecovery(self) if enabled and not self.ignore_equipment_level else None
        self._owns_selection = False
        if protection is not None and (policy is None or protection.policy_data != asdict(policy)):
            raise ValueError('装备暂存记录与当前规则配置不一致')

    def _read_screen(self):
        return (self.navigator.read_selection() if self.defer_details and hasattr(self.navigator,'read_selection')
                else self.navigator.read())

    def observe(self, recover_levels=True):
        self.screen = self._read_screen()
        report = self.reader(self.screen)
        report=self._recover_levels(report) if recover_levels else report
        self._observed_at=time.monotonic()
        return report

    def selection_reference(self,current):
        """仅连续选装复用刚核验的截图；每次点击后仍完整核对新截图。"""
        age=time.monotonic()-getattr(self,'_observed_at',float('-inf'))
        if (self.defer_details and 0<=age<=1
                and getattr(getattr(self,'screen',None),'source',None)==current['source']):
            if self.navigator.journal:
                self.navigator.journal.emit('batch_selection_observation_reused',
                                            image=current['source'],age_seconds=round(age,4))
            return current
        return self.observe_unchanged(current,allow_expansion=True)

    def _recover_levels(self, report):
        if self.level_recovery is not None and self._owns_selection:
            return self.level_recovery.resolve(report)
        return report

    @staticmethod
    def _navigation_snapshot(screen):
        from .inventory_mode_vision import inspect_zero_selection
        from .inventory_vision import inventory_context
        if screen.page!='inventory_batch_selection_empty':
            raise ValueError('回顶中途未确认零选择页面，不发送下一次手势')
        mode=inspect_zero_selection(screen.source,screen.words)
        return {'source':screen.source,'selected_count':mode['selected_count'],
                'inventory_context':inventory_context(screen),'cards':[], 'navigation_only':True}

    @staticmethod
    def _can_retry_missing(before,after):
        """只为暂时缺失证据安排重读；此结果绝不能用于选装或填补字段。"""
        try:
            BatchSelectionDriver._verify_unchanged(
                {k:v for k,v in before.items() if k not in {'source','cards'}},
                {k:v for k,v in after.items() if k not in {'source','cards'}})
        except ValueError:
            return False
        old_cards,new_cards=before['cards'],after['cards']
        if len(old_cards)!=len(new_cards):
            return False
        registered_jitter=BatchSelectionDriver._stationary_row_jitter(before,after)
        missing=False
        import math
        from .inventory_tracking import inspect_tracking
        for index,(old,new) in enumerate(zip(old_cards,new_cards)):
            if any(old[k]!=new[k] for k in ('row','column')):
                return False
            if (not old.get('tracking_box') or not new.get('tracking_box')
                    or any(not p or len(p)!=2 or any(type(v) is not int for v in p)
                           for p in (old.get('center'),new.get('center')))
                    or (index not in registered_jitter and (
                        any(abs(x-y)>1 for x,y in zip(old['center'],new['center']))
                        or any(abs(x-y)>1 for x,y in zip(old['tracking_box'],new['tracking_box']))))):
                return False
            a,b=old.get('identity_vector'),new.get('identity_vector')
            if not a or not b or len(a)!=len(b) or not all(math.isfinite(v) for v in (*a,*b)):
                return False
            lost=False
            for key in ('level','rarity','enhancement','selected'):
                if old[key]==new[key]:
                    continue
                if old[key] is None or new[key] is not None:
                    return False  # 已接受值变化或未知变为另一值，不用复读掩盖。
                lost=True
            if lost:
                if new['known'] is not False or new['eligible'] is not False:
                    return False
                missing=True
            elif (old['known'],old['eligible'])!=(new['known'],new['eligible']):
                return False
            if not inspect_tracking(old,new)['matched']:
                return False
        return missing

    @staticmethod
    def _can_expand_view(before,after):
        """只接受同一画面从两整行恢复为三整行；新增字段仅来自新截图。"""
        from .inventory_scan import rows
        from .inventory_tracking import inspect_tracking
        try:
            old_rows,new_rows=rows(before),rows(after)
            if len(old_rows)!=2 or len(new_rows)!=3 or any(len(row)!=7 for row in (*old_rows,*new_rows)):
                return False
            if before.get('tail_layout',{}).get('end_verified') or after.get('tail_layout',{}).get('end_verified'):
                return False
            if [[c['row'] for c in row] for row in new_rows]!=[[i]*7 for i in range(3)]:
                return False
            BatchSelectionDriver._verify_unchanged(
                {k:v for k,v in before.items() if k!='source'},
                {**{k:v for k,v in after.items() if k!='source'},'cards':after['cards'][:14]})
            # 旧的两行必须保有完整图像证明；不能仅凭数字/套装相同认作同视口。
            if any(not inspect_tracking(a,b)['matched'] for a,b in zip(before['cards'],after['cards'][:14])):
                return False
            for card in new_rows[-1]:
                if not card['known'] or card['selected'] is not False:
                    return False
                box=card.get('tracking_box')
                if (not box or len(box)!=4 or any(type(v) is not int for v in box)
                        or not(0<=box[0]<box[2]<=995 and 130<=box[1]<box[3]<=604)
                        or card.get('tracking_source')!=after['source']):
                    return False
                original={'tracking_source':before['source'],'tracking_box':box}
                if not inspect_tracking(original,card)['matched']:
                    return False
            return True
        except (ValueError,KeyError,TypeError):
            return False

    def verify_selection_unchanged(self,before,after):
        if getattr(self,'native_selection_state',False):
            verify_selection_state(before,after)
        else:
            self._verify_unchanged(before,after)

    def observe_unchanged(self,before,allow_expansion=False):
        """动作前最多四次只读核对；只有完整恢复原接受字段后才交回调用方。"""
        for attempt in range(4):
            self.navigator.control.checkpoint()
            fresh=self.observe()
            try:
                self.verify_selection_unchanged({k:v for k,v in before.items() if k!='source'},
                                                {k:v for k,v in fresh.items() if k!='source'})
                return fresh
            except ValueError as exc:
                if allow_expansion and self._can_expand_view(before,fresh):
                    if self.navigator.journal:
                        self.navigator.journal.emit('inventory_view_expanded',
                            before=before['source'],image=fresh['source'],added_cards=7)
                    return fresh
                if attempt==3 or not (isinstance(exc,IncompleteSelectionState) or self._can_retry_missing(before,fresh)):
                    raise
                if self.navigator.journal:
                    self.navigator.journal.emit('inventory_observation_retry',attempt=attempt+1,
                        reason='accepted_field_temporarily_missing',image=fresh['source'])
                self.navigator.control.wait(.4)

    def observe_scrolled(self,before,traversal,alternate=None):
        """一次手势后最多四次只读；不以缺失字段或图像匹配代替完整行验证。"""
        from .inventory_scan import missing_overlap_offset,unstable_overlap_offset,coherent_overlap_retry_offset
        from .inventory_scan import rows
        from copy import copy
        references=[before]
        if alternate is not None:
            self.verify_selection_unchanged({k:v for k,v in alternate.items() if k!='source'},
                                             {k:v for k,v in before.items() if k!='source'})
            references.append(alternate)
        previous=None
        for attempt in range(4):
            self.navigator.control.checkpoint()
            try:
                after=self.observe()
                self.last_scroll_observation=after
            except InventoryObservationIncomplete:
                if attempt==3:
                    raise
                if self.navigator.journal:
                    self.navigator.journal.emit('inventory_scroll_incomplete_retry',attempt=attempt+1)
                self.navigator.control.wait(.4)
                continue
            if previous is not None:
                try:
                    self.verify_selection_unchanged({k:v for k,v in previous.items() if k!='source'},
                                                    {k:v for k,v in after.items() if k!='source'})
                except ValueError:
                    # 原地重读可能继续漏字段或恢复字段；两方向均不覆盖已接受值。
                    if not (self._can_retry_missing(previous,after)
                            or self._can_retry_missing(after,previous)):
                        raise
            retry_new_row=False
            try:
                # 试验性核对不累计覆盖；新露出的行也须读完整，才提交本次位移。
                verified=None
                alignment_error=None
                for reference in references:
                    try:
                        offset=copy(traversal).advance(reference,after)
                    except ValueError as exc:
                        alignment_error=exc
                        continue
                    verified=reference
                    break
                if verified is None:
                    raise alignment_error
                overlap=min(len(rows(verified))-offset,len(rows(after)))
                retry_new_row=any(not card['known'] for row in rows(after)[overlap:] for card in row)
                if retry_new_row:
                    raise ValueError('滚动后新行存在未确认字段，未提交覆盖')
                traversal.advance(verified,after)
                if verified is not before and self.navigator.journal:
                    self.navigator.journal.emit('inventory_scroll_reference_verified',
                        reference=verified['source'],fresh_before=before['source'],image=after['source'])
                return after,offset
            except ValueError:
                if attempt==3 or not (retry_new_row or any(
                        missing_overlap_offset(reference,after) is not None
                        or unstable_overlap_offset(reference,after) is not None
                        or coherent_overlap_retry_offset(reference,after) is not None for reference in references)):
                    raise
                if self.navigator.journal:
                    self.navigator.journal.emit('inventory_scroll_observation_retry',
                        attempt=attempt+1,image=after['source'])
                previous=after
                self.navigator.control.wait(.4)

    def observe_scrolled_with_adjustment(self,before,traversal,alternate=None):
        """仅对完整、近门槛的重叠图像微调视口；位移仍由原两整行核验确定。"""
        from .inventory_scan import rows,unstable_overlap_offset,coherent_overlap_retry_offset
        self.last_scroll_observation=None
        original_moves=traversal.moves
        for attempt in range(3):
            try:
                return self.observe_scrolled(before,traversal,alternate)
            except ValueError:
                after=self.last_scroll_observation
                if traversal.moves==original_moves and after:
                    # 仅允许独立特征补充一张；满足时无需额外移动视口。
                    try:
                        offset=traversal.advance_with_features(before,after)
                    except ValueError:
                        pass
                    else:
                        if self.navigator.journal:
                            self.navigator.journal.emit('inventory_scroll_features_verified',
                                image=after['source'],offset=offset)
                        return after,offset
                if (attempt==2 or traversal.moves!=original_moves or not after
                        or any(not c.get('known') for c in after.get('cards',()))
                        or (unstable_overlap_offset(before,after,max_per_row=2) is None
                            and coherent_overlap_retry_offset(before,after) is None)
                        or rows(after)[0][0]['center'][1]<210):
                    raise
                self.navigator.control.checkpoint()
                if self.navigator.journal:
                    self.navigator.journal.emit('inventory_scroll_adjust_intent',
                        attempt=attempt+1,max_adjustments=2,image=after['source'],
                        distance=24,coverage_committed=False)
                self.navigator.adb.swipe(500,450,500,426,300)
                self.navigator.control.wait(.3)

    @staticmethod
    def _stationary_row_jitter(before,after):
        """七列整行一致偏移2～4像素时，必须证明像素实际留在原坐标。"""
        import math
        old,new=before.get('cards',()),after.get('cards',())
        if len(old)!=len(new):
            return set()
        from .inventory_tracking import inspect_tracking
        verified=set()
        groups={}
        for index,(a,b) in enumerate(zip(old,new)):
            groups.setdefault(a.get('row'),[]).append((index,a,b))
        for group in groups.values():
            if len(group)!=7 or [a.get('column') for _,a,b in group]!=list(range(7)):
                continue
            shifts=[]
            for index,a,b in group:
                center,other=a.get('center'),b.get('center')
                box,target=a.get('tracking_box'),b.get('tracking_box')
                if (not center or not other or len(center)!=2 or len(other)!=2
                        or not box or not target or len(box)!=4 or len(target)!=4
                        or any(type(v) is not int for p in (center,other,box,target) for v in p)):
                    break
                dy=other[1]-center[1]
                if (dy not in (-4,-3,-2,2,3,4) or center[0]!=other[0]
                        or tuple(y-x for x,y in zip(box,target))!=(0,dy,0,dy)):
                    break
                proof=inspect_tracking(a,b,search_margin=6) if abs(dy)==4 else inspect_tracking(a,b)
                offset=proof.get('offset')
                if (not proof['matched'] or not offset or len(offset)!=2
                        or not all(math.isfinite(v) for v in offset)
                        or abs(offset[0])>.25 or abs(offset[1]+dy)>.25):
                    break
                shifts.append(dy)
            if len(shifts)==7 and len(set(shifts))==1:
                verified.update(index for index,a,b in group)
        return verified

    @staticmethod
    def _verify_unchanged(before, after):
        # OCR候选与置信度是审计证据；已接受的字段、卡片像素和勾选必须保持一致。
        import math
        registered_jitter=BatchSelectionDriver._stationary_row_jitter(before,after)
        for index,(old,new) in enumerate(zip(before.get('cards',()),after.get('cards',()))):
            if 'identity_vector' in old or 'identity_vector' in new:
                a,b=old.get('identity_vector'),new.get('identity_vector')
                valid=(a and b and len(a)==len(b)
                        and all(math.isfinite(v) for v in (*a,*b)))
                if not valid:
                    raise SelectionImageUnstable('选装前装备图像身份未确认，未点击')
                if index in registered_jitter:
                    continue
                shifted=(old.get('center')!=new.get('center')
                         or old.get('tracking_box')!=new.get('tracking_box'))
                if shifted or sum(x*y for x,y in zip(a,b))<.995:
                    # OCR行锚点可能差一像素；必须由完整卡片图像独立配准证明。
                    points=[old.get('center'),new.get('center')]
                    boxes=[old.get('tracking_box'),new.get('tracking_box')]
                    bounded=(all(p and len(p)==2 for p in points)
                             and all(p and len(p)==4 for p in boxes)
                             and all(type(v) is int for p in (*points,*boxes) for v in p)
                             and all(abs(x-y)<=1 for x,y in zip(*points))
                             and all(abs(x-y)<=1 for x,y in zip(*boxes)))
                    from .inventory_tracking import inspect_tracking
                    from .selection_features import stationary_features
                    proof=inspect_tracking(old,new) if bounded else {'matched':False}
                    feature_proof=(bounded and not proof['matched']
                                   and stationary_features(old,new)['matched']
                                   and BatchSelectionDriver._stationary_inner_proof(old,new,proof))
                    if not bounded or not (proof['matched'] or feature_proof):
                        raise SelectionImageUnstable('选装前装备图像身份未确认，未点击')
                    registered_jitter.add(index)
        diagnostics={'level_evidence','badge_evidence','context_evidence','mode_evidence','count_evidence'}
        def visual(report):
            result={k:v for k,v in report.items() if k not in diagnostics}
            if 'cards' in result:
                result['cards']=[{k:v for k,v in card.items()
                                  if k not in (({'center','tracking_box','identity_box'} if index in registered_jitter else set())
                                               | ({'tracking_source','identity_vector','signature',
                                                'orange_ratio','orange_component_ratio','green_ratio','rarity_evidence',
                                                'detail_level_evidence'}
                                               if 'identity_vector' in card else {'tracking_source'}))}
                                 for index,card in enumerate(result['cards'])]
            if 'tail_layout' in result:
                tail=result['tail_layout']
                result['tail_layout']={k:v for k,v in tail.items()
                                       if k not in {'bottom_cap_mae','bottom_cap_match','notice','cells'}}
                if 'cells' in tail:
                    result['tail_layout']['cells']=[{'column':c['column'],'state':c['state']}
                                                     for c in tail['cells']]
            return result
        if visual(before)!=visual(after):
            raise ValueError('选装前页面或识别结果变化，未点击')

    @staticmethod
    def _stationary_target(before,after,target):
        """六张未点击整卡证明行未移动，再在原坐标核对目标未被勾选遮挡的图块。"""
        import math
        from .inventory_tracking import inspect_tracking
        pairs=[(a,b) for a,b in zip(before['cards'],after['cards']) if a['row']==target[0]]
        if len(pairs)!=7 or [a['column'] for a,b in pairs]!=list(range(7)):
            return False
        shifts=[]
        for a,b in pairs:
            center,other=a.get('center'),b.get('center')
            box,new_box=a.get('tracking_box'),b.get('tracking_box')
            if (not center or not other or not box or not new_box
                    or len(center)!=2 or len(other)!=2 or len(box)!=4 or len(new_box)!=4
                    or any(type(v) is not int for p in (center,other,box,new_box) for v in p)):
                return False
            dy=other[1]-center[1]
            # 归一化身份裁框可偏移一像素，原生中心取整后却保持不变。
            # 此时仍须六张未点击卡片证明零位移，并在原坐标验证目标内容。
            if dy not in (-1,0,1) or center[0]!=other[0] or tuple(y-x for x,y in zip(box,new_box))!=(0,dy,0,dy):
                return False
            shifts.append(dy)
            if (a['row'],a['column'])!=target:
                proof=inspect_tracking(a,b)
                offset=proof.get('offset')
                if (not (proof['matched'] or BatchSelectionDriver._stationary_inner_proof(a,b,proof)) or not offset or len(offset)!=2
                        or not all(math.isfinite(v) for v in offset)
                        or abs(offset[0])>.25 or abs(offset[1]+dy)>.25):
                    return False
        if len(set(shifts))!=1:
            return False
        a,b=next((a,b) for a,b in pairs if (a['row'],a['column'])==target)
        box=a.get('identity_box')
        if (not box or len(box)!=4 or any(type(v) is not int for v in box)
                or (box[2]-box[0],box[3]-box[1])!=(60,39)
                or not (0<=box[0]<box[2]<=1661 and 0<=box[1]<box[3]<=933)):
            return False
        from PIL import Image
        import numpy as np
        vectors=[]
        for card in (a,b):
            if not card.get('tracking_source'):
                return False
            with Image.open(card['tracking_source']) as image:
                if image.size!=(1280,720):
                    return False
                pixels=np.asarray(image.convert('RGB').resize((1661,933)).crop(box)
                                  .convert('L').resize((24,16))).astype(float).ravel()
            if float(pixels.std())<8:
                return False
            pixels-=pixels.mean()
            vectors.append(pixels/np.linalg.norm(pixels))
        # 勾选使目标整体变暗；与原identity_vector相同，去均值后核对结构。
        return bool(float(np.dot(*vectors))>=.995 or
                    BatchSelectionDriver._target_icon_content_unchanged(a,{**b,'identity_box':box}))

    @staticmethod
    def _stationary_inner_proof(before,after,proof):
        """流动边框不能证明移动；配准零位移后再核对原坐标两块内部图案。"""
        import math
        boxes=(before.get('identity_box'),after.get('identity_box'))
        offset=proof.get('offset')
        if (not all(box and len(box)==4 for box in boxes)
                or any(type(v) is not int for box in boxes for v in box)
                or any(abs(a-b)>2 for a,b in zip(*boxes))
                or not offset or len(offset)!=2 or not all(math.isfinite(v) for v in offset)):
            return False
        dx=after['center'][0]-before['center'][0]
        dy=after['center'][1]-before['center'][1]
        if abs(offset[0]+dx)>.25 or abs(offset[1]+dy)>.25:return False
        return BatchSelectionDriver._target_icon_content_unchanged(before,{**after,'identity_box':boxes[0]})

    @staticmethod
    def _target_icon_content_unchanged(before,after):
        """目标选中时边框发光；只比对两处不含边框、等级角标的图案。"""
        from PIL import Image
        import numpy as np
        import cv2
        box=before.get('identity_box')
        if (not box or box!=after.get('identity_box') or len(box)!=4
                or box[2]-box[0]!=60 or box[3]-box[1]!=39):return False
        sources=[card.get('tracking_source') for card in (before,after)]
        if not all(sources):return False
        images=[]
        for source in sources:
            with Image.open(source) as image:
                if image.size!=(1280,720):return False
                images.append(image.convert('RGB').resize((1661,933)))
        for offset in ((12,4,60,34),(12,18,60,39)):
            region=(box[0]+offset[0],box[1]+offset[1],box[0]+offset[2],box[1]+offset[3])
            vectors=[];patches=[]
            for image in images:
                patch=np.asarray(image.crop(region).convert('L')).astype(float)
                patches.append(patch)
                values=patch.ravel().copy()
                if values.std()<8:return False
                values-=values.mean();vectors.append(values/np.linalg.norm(values))
            if float(np.dot(*vectors))<.995:
                # 勾选暗层与流动光效可改变低频亮度；两个高通尺度均须保留原门槛。
                for sigma in (1,2):
                    edges=[p-cv2.GaussianBlur(p,(0,0),sigma) for p in patches]
                    if any(p.std()<2 for p in edges):return False
                    if float(np.corrcoef(edges[0].ravel(),edges[1].ravel())[0,1])<.995:return False
        return True

    @staticmethod
    def _verify_click(before, after, target, selected=True):
        if len(before['cards']) != len(after['cards']):
            raise ValueError('选装后可见卡片数量变化')
        if after['selected_count'] != before['selected_count'] + (1 if selected else -1):
            raise ValueError('选装后计数未恰好变化1，禁止重复点击')
        for old, new in zip(before['cards'], after['cards']):
            for key in ('row', 'column', 'level', 'rarity', 'enhancement'):
                if old[key] != new[key]:
                    if key in ('level','rarity','enhancement') and old[key] is not None and new[key] is None:
                        raise SelectionImageUnstable('选装后身份字段暂时缺失，只可重读')
                    raise ValueError('选装后卡片位置或身份字段变化')
            expected = selected if (old['row'], old['column']) == target else old['selected']
            if new['selected'] is not expected:
                raise ValueError('选装后勾选集合与目标不符')
        # 先检查整页结构和勾选集合，避免重读掩盖其他卡片的真实异常。
        import math
        stationary_rows=BatchSelectionDriver._stationary_row_jitter(before,after)
        for index,(old, new) in enumerate(zip(before['cards'], after['cards'])):
            a, b = old['identity_vector'], new['identity_vector']
            if not a or len(a)!=len(b) or not all(math.isfinite(v) for v in (*a,*b)):
                raise SelectionImageUnstable('选装后装备图像身份未确认')
            shifted=(old['center']!=new['center'] or old.get('tracking_box')!=new.get('tracking_box')
                     or old.get('identity_box')!=new.get('identity_box'))
            if shifted:
                # 非目标整行沿用已有的零实际位移证明，不能将原生2px取整误作移动。
                if index in stationary_rows and (old['row'],old['column'])!=target:
                    continue
                # 目标勾选图形改变，须由整行和原坐标身份图块独立取证。
                # 非目标卡片须保持完整像素内容，才容许一像素OCR定位变化。
                points=(old['center'],new['center'])
                boxes=(old.get('tracking_box'),new.get('tracking_box'))
                bounded=(all(p and len(p)==2 for p in points)
                         and all(p and len(p)==4 for p in boxes)
                         and all(type(v) is int for p in (*points,*boxes) for v in p)
                         and all(abs(x-y)<=1 for x,y in zip(*points))
                         and all(abs(x-y)<=1 for x,y in zip(*boxes)))
                if old.get('identity_box')!=new.get('identity_box'):
                    identity_boxes=(old.get('identity_box'),new.get('identity_box'))
                    bounded=bounded and all(p and len(p)==4 for p in identity_boxes)
                    bounded=bounded and all(type(v) is int for p in identity_boxes for v in p)
                    # 1280→1661缩放后，原生1px取整差可成为归一化2px。
                    bounded=bounded and all(abs(x-y)<=2 for x,y in zip(*identity_boxes))
                if not bounded:
                    raise ValueError('选装后卡片位置或身份字段变化')
                if (old['row'],old['column'])==target:
                    if not BatchSelectionDriver._stationary_target(before,after,target):
                        raise SelectionImageUnstable('选装后目标原坐标图像身份未确认')
                    continue
                from .inventory_tracking import inspect_tracking
                proof=inspect_tracking(old,new)
                if not (proof['matched'] or BatchSelectionDriver._stationary_inner_proof(old,new,proof)):
                    raise SelectionImageUnstable('选装后装备图像身份未确认')
            elif sum(x*y for x,y in zip(a,b))<.995:
                if (old['row'],old['column'])==target and BatchSelectionDriver._target_icon_content_unchanged(old,new):
                    continue
                if (old['row'],old['column'])!=target:
                    from .inventory_tracking import inspect_tracking
                    from .selection_features import stationary_features
                    proof=inspect_tracking(old,new)
                    if ((proof['matched'] or stationary_features(old,new)['matched'])
                            and BatchSelectionDriver._stationary_inner_proof(old,new,proof)):
                        continue
                raise SelectionImageUnstable('选装后装备图像身份未确认')

    def _observe_click(self,before,target,selected=True,recover_levels=True):
        for attempt in range(4):
            after=None
            try:
                after = self.observe(recover_levels=recover_levels)
                if getattr(self,'native_selection_state',False):
                    verify_selection_state(before,after,target,selected)
                else:
                    self._verify_click(before,after,target,selected)
                return after
            except (SelectionImageUnstable,InventoryObservationIncomplete,IncompleteSelectionState):
                if attempt == 3:
                    raise
            except ValueError:
                if attempt==3 or after is None or not self._can_retry_click_missing(before,after,target,selected):
                    raise
            if self.navigator.journal:
                self.navigator.journal.emit('batch_selection_image_retry',
                                            attempt=attempt+1,image=self.screen.source)
            self.navigator.control.wait(.4)

    @staticmethod
    def _can_retry_click_missing(before,after,target,selected):
        """一次点击后只允许缺失证据的原地重读，不重发点击或填补字段。"""
        from copy import deepcopy
        if after.get('page') not in {'inventory_batch_selection','inventory_batch_selection_empty'}:
            return False
        expected=deepcopy(before)
        expected['page']=after['page']
        expected['selected_count']+=1 if selected else -1
        for card in expected['cards']:
            if (card['row'],card['column'])==target:
                card['selected']=selected
        return BatchSelectionDriver._can_retry_missing(expected,after)

    def _begin(self, limit,navigation_only=False):
        if type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError('选装上限必须为1～16')
        self._owns_selection = False
        if self.level_recovery is not None:
            self.level_recovery.reset()
        current = (self.navigation_reader(self._read_screen()) if navigation_only else self.observe())
        if current['selected_count'] or any(c['selected'] is not False for c in current['cards']):
            raise ValueError('开始选装前必须确认没有已选装备；不清空用户选择')
        self._owns_selection = True
        return current if navigation_only else self._recover_levels(current)

    def _collect_page(self, current, registered, limit, skipped, base=0):
        while current['selected_count'] < limit:
            self.navigator.control.checkpoint()
            candidate = None
            for card in current['cards']:
                position=(base+card['row'],card['column'])
                if position in self.excluded_positions:
                    from .inventory_scan import same_row
                    if not same_row([self.excluded_positions[position]],[card],self.ignore_equipment_level):
                        raise ValueError('暂存位置图像或强化阶段变化，停止并重新核对，不跳过未知装备')
                    skipped.add(position)
                if (base+card['row'],card['column']) in skipped:
                    continue
                if card['selected']:
                    continue
                if card['enhancement'] == 15:
                    continue
                if not self.ignore_equipment_level and card['known'] and card['level'] in {88,90}:
                    # 正向确认的非投入等级只参与覆盖追踪，不选中强化。
                    skipped.add((base+card['row'],card['column']))
                    continue
                if not card['eligible']:
                    raise ValueError('顺序扫描遇到未确认的装备，已停止；未把未知当作可强化装备')
                candidate = card
                break
            if candidate is None:
                fresh=self.selection_reference(current)
                expanded=len(fresh['cards'])>len(current['cards'])
                current=fresh
                if expanded:
                    continue  # 新恢复的第三行也要处理，不能直接滚过它。
                break
            fresh = self.selection_reference(current)
            target = (candidate['row'], candidate['column'])
            candidate=next(c for c in fresh['cards'] if (c['row'],c['column'])==target)
            if self.navigator.journal:
                self.navigator.journal.emit('batch_selection_intent', row=target[0], column=target[1],
                                            image=fresh['source'], count=fresh['selected_count'])
            self.navigator.adb.tap(*candidate['center'])
            self.navigator.control.wait(.3)
            after = self._observe_click(fresh,target)
            try:
                detail = ({'equipment':read_selection_header(self.screen,candidate),'selection_only':True,
                           'source':self.screen.source} if self.defer_details else self.detail_reader(self.screen, candidate))
            except UnsupportedEquipment as exc:
                # 只撤销刚刚确认的选择；普通OCR失败不走此分支，仍停止。
                fresh=self.selection_reference(after)
                if self.navigator.journal:
                    self.navigator.journal.emit('batch_unsupported_deselect_intent',
                        row=target[0],column=target[1],reason=str(exc),image=fresh['source'])
                self.navigator.adb.tap(*candidate['center'])
                self.navigator.control.wait(.3)
                current=self._observe_click(fresh,target,False)
                skipped.add((base+candidate['row'],candidate['column']))
                if self.navigator.journal:
                    self.navigator.journal.emit('batch_unsupported_preserved',
                        row=target[0],column=target[1],image=current['source'])
                continue
            if self.defer_details:
                detail['position']=(base+candidate['row'],candidate['column'])
                detail['list_card']=candidate
                registered.append(detail)
                current=after
                if self.navigator.journal:
                    self.navigator.journal.emit('batch_selection_only_registered',index=len(registered)-1,
                                                **detail)
                continue
            protected = detail['fingerprint'] in self.excluded_fingerprints
            from .custom_targets import needs_set_check
            pending_set_check=self.policy is not None and needs_set_check(detail['equipment'],self.policy)
            if self.protection is not None and not pending_set_check:
                protected = self.protection.should_skip(detail) or protected
            decision = None
            if not protected and self.policy is not None and not pending_set_check:
                from .rules import evaluate
                decision = evaluate(detail['equipment'],self.policy)
                protected = decision.action in {'stop','review','store'} and not decision.discard_allowed
            if protected:
                # 点击只是读取详情；已保护的同属性装备立即取消，不再次投入强化。
                fresh = self.observe_unchanged(after)
                if self.navigator.journal:
                    self.navigator.journal.emit('batch_protected_equivalence_deselect_intent',
                                                fingerprint=detail['fingerprint'],image=fresh['source'])
                self.navigator.adb.tap(*candidate['center'])
                self.navigator.control.wait(.3)
                current = self._observe_click(fresh,target,False)
                if decision is not None and self.protection is not None:
                    self.protection.remember(detail)
                    if self.navigator.journal:
                        self.navigator.journal.emit('batch_unfinished_equipment_protected',
                            fingerprint=detail['fingerprint'],decision=asdict(decision),source=detail['source'])
                skipped.add((base+candidate['row'],candidate['column']))
                continue
            equipment = asdict(detail['equipment'])
            equipment['equipment_id'] = f"selection:{len(registered)}:{detail['fingerprint']}"
            registered.append({'equipment': equipment, 'fingerprint': detail['fingerprint'],
                               'main': detail['main'], 'source': detail['source']})
            if self.navigator.journal:
                self.navigator.journal.emit('batch_equipment_registered', index=len(registered)-1,
                                            **registered[-1])
            current = after
            if self.navigator.journal:
                self.navigator.journal.emit('batch_selection_verified', count=current['selected_count'],
                                            image=current['source'])
        return current

    @staticmethod
    def _result(current, registered, limit, **extra):
        return {**current, 'selection_status': 'capacity' if current['selected_count'] == limit else 'visible_exhausted',
                'registered': registered,
                'scan_complete': False, **extra}

    def collect_visible(self, limit=16):
        """只处理当前完整可见行；不足上限不冒充已完成整个背包扫描。"""
        current = self._begin(limit)
        registered = []
        current = self._collect_page(current,registered,limit,set())
        return self._result(current,registered,limit)

    def settle_top_snapshot(self,current):
        """回顶动画尚在收敛时更新只读候选，连续两帧严格静止才登记扫描基准。"""
        for attempt in range(4):
            self.navigator.control.checkpoint()
            self.navigator.control.wait(.3)
            fresh=self.reader(self._read_screen())
            try:
                verify_selection_state(current,fresh)
                return fresh
            except IncompleteSelectionState:
                if attempt==3:raise
                # 没有输入或已选集合；这里只重选尚未交给扫描器的完整候选帧。
                # 字段/排序/数量的真实冲突仍由上面的核验直接抛出。
                current=fresh
        raise AssertionError('unreachable')

    def rewind_to_top(self,current,max_moves):
        from .inventory_top_vision import inspect_top,verify_top_anchor,context_pixels_equal
        expected_context=current.get('inventory_context')
        import re
        if (not expected_context or not any(re.fullmatch(r'\d+/\d+',text) for text in expected_context)
                or not any(re.fullmatch(r'[\u4e00-\u9fff]{1,8}',text) for text in expected_context)):
            raise ValueError('背包数量与排序上下文未确认，不能回到顶部')
        for move in range(max_moves):
            self.navigator.control.checkpoint()
            if self.navigator.journal:
                self.navigator.journal.emit('inventory_rewind_intent',move=move+1,image=current['source'])
            self.navigator.adb.swipe(500,300,500,600,600)
            # 端点会很快淡出，先截图取证，再等待回弹结束。
            head_screen=self._read_screen()
            head=(self.top_reader or inspect_top)(head_screen)
            self.navigator.control.wait(.3)
            stable_screen=self._read_screen()
            if head.get('head_visible') is True:
                # 只有到顶后的完整观测可以交给后续扫描；中途不累计装备覆盖。
                stable=self.reader(stable_screen)
            else:
                stable=self.navigation_reader(stable_screen)
            head_context_matches=head.get('inventory_context')==expected_context
            if (not head_context_matches and stable.get('inventory_context')==expected_context
                    and set(head.get('inventory_context',())).issubset(expected_context)):
                head_context_matches=context_pixels_equal(current['source'],head['source'],stable['source'])
                if head_context_matches and self.navigator.journal:
                    self.navigator.journal.emit('inventory_context_pixel_verified',
                        before=current['source'],head=head['source'],stable=stable['source'])
            if (stable['selected_count']!=0 or any(c['selected'] is not False for c in stable['cards'])
                    or stable.get('inventory_context')!=expected_context
                    or not head_context_matches):
                raise ValueError('回到顶部期间选择、排序或背包数量变化，已停止')
            if head.get('head_visible') is True:
                if self.native_selection_state:
                    stable=self.settle_top_snapshot(stable)
                stable = self._recover_levels(stable)
                anchor={'method':'visible_head_then_settled','head_visible':True,
                        'head_source':head['source'],'stable_source':stable['source'],
                        'inventory_context':expected_context}
                verify_top_anchor(anchor,stable)
                if self.navigator.journal:
                    self.navigator.journal.emit('inventory_top_verified',**anchor)
                return stable,anchor
            current=stable
        raise ValueError('回到顶部达到次数上限，未获得滚动条顶部证据；未把静止当作到顶')

    def collect_pages(self, limit=16, max_pages=10,start_at_top=False):
        """跨页填满批次；没有端点证据时不把不足上限当作尾批。"""
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError('扫描页数上限必须为正整数')
        if type(start_at_top) is not bool:
            raise ValueError('从顶部扫描标志必须为布尔值')
        current = self._begin(limit,navigation_only=start_at_top)
        top_anchor=None
        if start_at_top:
            current,top_anchor=self.rewind_to_top(current,max_pages)
        registered, skipped = [], set()
        traversal = InventoryTraversal()
        traversal.start(current,top_anchor)
        pages = 0
        for pages in range(1,max_pages+1):
            current = self._collect_page(current,registered,limit,skipped,traversal.base)
            traversal.observe_end(current)
            if current['selected_count'] == limit or pages == max_pages or traversal.end_verified:
                break
            fresh = self.selection_reference(current)
            alternate=current
            if len(fresh['cards'])>len(current['cards']):
                current=self._collect_page(fresh,registered,limit,skipped,traversal.base)
                traversal.observe_end(current)
                if current['selected_count']==limit or traversal.end_verified:
                    break
                fresh=current
                alternate=None
            from .inventory_scan import scroll_distance
            distance=scroll_distance(fresh)
            if self.navigator.journal:
                self.navigator.journal.emit('inventory_scroll_intent',image=fresh['source'],
                                            selected=fresh['selected_count'],distance=distance,
                                            **traversal.evidence())
            self.navigator.control.checkpoint()
            # 小幅滚动，保留至少两行重叠；只在装备列表内部发送手势。
            self.navigator.adb.swipe(500,510,500,510-distance,600)
            self.navigator.control.wait(.5)
            after,offset = self.observe_scrolled_with_adjustment(fresh,traversal,alternate)
            if self.navigator.journal:
                self.navigator.journal.emit('inventory_scroll_verified',image=after['source'],
                                            offset=offset,**traversal.evidence())
            current = after
        complete=(current['selected_count']<limit and traversal.top_verified and traversal.end_verified)
        status = 'capacity' if current['selected_count'] == limit else (
            'exhausted' if complete else 'bottom_reached_unanchored' if traversal.end_verified else 'visible_exhausted')
        if self.navigator.journal:
            self.navigator.journal.emit('batch_scan_finished',selected=current['selected_count'],
                                        scanned_pages=pages,selection_status=status,scan_complete=complete,
                                        scan_evidence=traversal.evidence(),image=current['source'])
        return self._result(current,registered,limit,scanned_pages=pages,selection_status=status,
                            scan_complete=complete,top_anchor=top_anchor,
                            protected_equivalence_skipped=len(skipped),scan_evidence=traversal.evidence(),
                            visual_snapshot={k:v for k,v in current.items() if k != 'source'})
