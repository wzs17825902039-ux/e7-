"""列表等级遮挡时独立读取原生详情；所有临时勾选都恢复，不点击锁或资源按钮。"""
from copy import deepcopy

from .inventory_detail import read_detail
from .inventory_scan import rows, same_row


class InventoryLevelRecovery:
    def __init__(self, selector, detail_reader=None):
        self.selector = selector
        self.detail_reader = detail_reader or (
            lambda screen, card: read_detail(screen, card, allow_unknown_level=True))
        self.reset()

    def reset(self):
        self.previous_raw = self.previous_verified = None

    def _emit(self, kind, **data):
        journal = self.selector.navigator.journal
        if journal:
            journal.emit(kind, **data)

    @staticmethod
    def verify_probe_click(selector,before,after,target,selected):
        """原先未知的目标等级可在勾选后显现；其余已接受字段仍严格不变。"""
        a,b=deepcopy(before),deepcopy(after)
        old=next(c for c in a['cards'] if (c['row'],c['column'])==target)
        new=next(c for c in b['cards'] if (c['row'],c['column'])==target)
        levels=(old['level'],new['level'])
        if None in levels and all(v is None or v in {85,88,90} for v in levels):
            # 仅用于核对这次勾选；不将此归一化结果写入返回观测。
            old['level']=new['level']=next((v for v in levels if v is not None),None)
        stages=(old['enhancement'],new['enhancement'])
        if None in stages and all(v is None or type(v) is int and 0<=v<15 for v in stages):
            # 勾选遮罩可使小徽标拒识；正式恢复仍必须由独立详情确认该阶段。
            old['enhancement']=new['enhancement']=next((v for v in stages if v is not None),None)
        selector._verify_click(a,b,target,selected)

    def _observe_probe_click(self,before,target,selected=True):
        from .batch_selection import SelectionImageUnstable
        from .inventory_vision import InventoryObservationIncomplete
        for attempt in range(4):
            after=None
            try:
                after=self.selector.observe(recover_levels=False)
                self.verify_probe_click(self.selector,before,after,target,selected)
                return after
            except (SelectionImageUnstable,InventoryObservationIncomplete):
                if attempt==3:
                    raise
            except ValueError:
                if (attempt==3 or after is None
                        or not self.selector._can_retry_click_missing(before,after,target,selected)):
                    raise
            self.selector.navigator.control.wait(.4)

    def _mapped_proofs(self, current):
        """只有原地不变、一次已验证勾选、或唯一两行重叠才传播先前详情证据。"""
        old = self.previous_raw
        verified = self.previous_verified
        if old is None or old.get('inventory_context') != current.get('inventory_context'):
            return {}
        pairs = None
        try:
            delta = current['selected_count'] - old['selected_count']
            if delta == 0:
                self.selector._verify_unchanged(
                    {k:v for k,v in old.items() if k!='source'},
                    {k:v for k,v in current.items() if k!='source'})
            elif abs(delta) == 1:
                changed = [(a['row'], a['column']) for a,b in zip(old['cards'],current['cards'])
                           if a['selected'] != b['selected']]
                if len(changed) != 1:
                    raise ValueError('不是一次勾选变化')
                target=next(c for c in verified['cards'] if (c['row'],c['column'])==changed[0])
                if 'detail_level_evidence' in target:
                    self.verify_probe_click(self.selector,old,current,changed[0],delta==1)
                else:
                    self.selector._verify_click(old,current,changed[0],delta==1)
            else:
                raise ValueError('选择计数不连续')
            pairs = list(zip(old['cards'],current['cards']))
        except ValueError:
            if old['selected_count'] != current['selected_count']:
                return {}
            # 临时0仅作为几何对应标记，绝不返回为装备等级。
            def geometry(report):
                projected = deepcopy(report)
                for card in projected['cards']:
                    if card['level'] is None:
                        card['level'] = 0
                return rows(projected)
            try:
                a,b = geometry(old),geometry(current)
            except ValueError:
                return {}
            offsets = [offset for offset in range(len(a))
                       if min(len(a)-offset,len(b)) >= 2
                       and all(same_row(x,y) for x,y in zip(a[offset:],b))]
            if len(offsets) != 1:
                return {}
            original_old, original_new = rows(old),rows(current)
            pairs = [(x,y) for a,b in zip(original_old[offsets[0]:],original_new)
                     for x,y in zip(a,b)]
        previous = {(c['row'],c['column']):c for c in verified['cards']}
        return {(new['row'],new['column']): previous[(old['row'],old['column'])]['detail_level_evidence']
                for old,new in pairs if old['level'] is None and new['level'] is None
                and 'detail_level_evidence' in previous[(old['row'],old['column'])]}

    def resolve(self, report):
        raw = deepcopy(report)
        proofs = self._mapped_proofs(raw)
        try:
            for card in list(raw['cards']):
                target = (card['row'],card['column'])
                if card['level'] is not None or card['enhancement'] == 15 or target in proofs:
                    continue
                if (card['rarity'] not in {'red','purple'}
                        or type(card['enhancement']) is not int or not 0 <= card['enhancement'] < 15
                        or type(card['selected']) is not bool):
                    continue  # 不能用详情恢复掩盖其他未知字段。
                if card['selected']:
                    raise ValueError('已选装备缺少可追踪详情等级证据，不取消重选以免改变顺序')
                if raw['selected_count'] >= 16:
                    continue  # 已满不再临时添加第17件。
                fresh = self.selector.observe(recover_levels=False)
                self.selector._verify_unchanged(
                    {k:v for k,v in raw.items() if k!='source'},
                    {k:v for k,v in fresh.items() if k!='source'})
                nav = self.selector.navigator
                nav.control.checkpoint()
                self._emit('inventory_detail_probe_intent',row=target[0],column=target[1],
                           x=card['center'][0],y=card['center'][1],image=fresh['source'])
                nav.adb.tap(*card['center'])
                nav.control.wait(.3)
                selected = self._observe_probe_click(fresh,target)
                detail = None
                try:
                    detail = self.detail_reader(self.selector.screen,card)
                    item = detail['equipment']
                    if (item.level != 85 or item.rarity != card['rarity']
                            or item.enhancement != card['enhancement'] or not item.recognition_ok):
                        raise ValueError('详情与列表候选不符，不恢复等级')
                finally:
                    # 只取消已经由计数、勾选集合及图像验证的本次临时选择。
                    stable = self.selector.observe(recover_levels=False)
                    self.selector._verify_unchanged(
                        {k:v for k,v in selected.items() if k!='source'},
                        {k:v for k,v in stable.items() if k!='source'})
                    nav.control.checkpoint()
                    self._emit('inventory_detail_probe_restore_intent',row=target[0],column=target[1],
                               x=card['center'][0],y=card['center'][1],image=stable['source'])
                    nav.adb.tap(*card['center'])
                    nav.control.wait(.3)
                    raw = self._observe_probe_click(stable,target,False)
                proofs[target] = {'method':'native_detail', 'level':85,
                                  'enhancement':item.enhancement,
                                  'list_source':fresh['source'],'detail_source':detail['source'],
                                  'restored_source':raw['source'],'fingerprint':detail['fingerprint']}
                self._emit('inventory_detail_level_verified',row=target[0],column=target[1],
                           evidence=proofs[target],image=raw['source'])
            verified = deepcopy(raw)
            for card in verified['cards']:
                proof = proofs.get((card['row'],card['column']))
                if card['level'] is None and proof:
                    card['level'] = proof['level']
                    if card['enhancement'] is None:
                        card['enhancement'] = proof['enhancement']
                    card['detail_level_evidence'] = deepcopy(proof)
                    card['known'] = all(card[k] is not None for k in ('rarity','enhancement','selected'))
                    card['eligible'] = card['known'] and card['enhancement'] < 15
            self.previous_raw,self.previous_verified = deepcopy(raw),deepcopy(verified)
            return verified
        except Exception:
            self.reset()
            raise
