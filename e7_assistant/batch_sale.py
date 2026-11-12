"""明确淘汰名单的批量出售事务；产物、保留装备和背包减量均核对后结算。"""
from dataclasses import asdict
import re

from .batch_sale_vision import inspect_organized,inspect_sale_confirmation,origin,verify_sale_survivors,sale_confirmation_unchanged
from .disposal_guard import DisposalGuard
from .initial_cleanup import inspect_inventory
from .batch_resources import inspect_resources


class BatchSaleDriver:
    def __init__(self,enhancement,organized_reader=inspect_organized,
                 confirmation_reader=inspect_sale_confirmation,guard=None,survivor_reader=verify_sale_survivors):
        self.enhancement=enhancement
        self.navigator=enhancement.navigator
        self.organized_reader=organized_reader
        self.confirmation_reader=confirmation_reader
        self.survivor_reader=survivor_reader
        self.guard=guard if guard is not None else DisposalGuard(
            self.navigator.directory.parent/'disposal-pending',self.navigator.adb.serial)
        self.pending=False

    def emit(self,kind,**data):
        if self.navigator.journal:
            self.navigator.journal.emit(kind,**data)

    def click(self,screen,label,region):
        word=screen.find(label,region,.95)
        self.navigator.control.checkpoint()
        self.navigator.adb.tap(*(round(v) for v in word['center']))
        self.navigator.control.wait(.4)

    def observe_survivors(self,reference,items,rejected):
        for attempt in range(6):
            screen=self.navigator.read()
            try:
                self.survivor_reader(screen,reference,items,rejected)
                return screen
            except ValueError:
                if attempt==5:
                    raise
                # 出售成功提示会遮挡底行；只重拍，不重发出售或导航。
                self.navigator.control.wait(.3)

    def observe(self,reference,count,gold):
        for attempt in range(3):
            screen=self.navigator.read()
            try:
                state=(self.organized_reader(screen,reference,count,track_gold=gold is not None,
                                             locked_indices=getattr(self,'locked_indices',()),
                                             boosted_red_indices=getattr(self,'boosted_red_indices',()))
                       if self.organized_reader is inspect_organized else
                       self.organized_reader(screen,reference,count))
            except ValueError:
                # 选择闪光可能尚未消退；只重读同一登记参考，不重发点击。
                if attempt==2:
                    raise
                self.navigator.control.wait(.2)
                continue
            if gold is not None and state.gold!=gold:
                raise ValueError('整理期间金币变化，未出售')
            return screen,state

    @staticmethod
    def sale_resources(screen,resources):
        # 强化可不读取余额；出售事务单独读取一次基线和回执，
        # 不把未跟踪对象的None字段当作0或已完成核账。
        return inspect_resources(screen) if resources.available is None else resources

    def sell(self,items,rejected,protected,action='sell'):
        tokens={i.token for i in items}
        if (action!='sell' or not rejected or rejected&protected
                or rejected|protected!=tokens or len(tokens)!=len(items)
                or any(i.selected for i in items)
                or any(i.locked is not False for i in items if i.token in rejected)):
            raise ValueError('出售必须是无强化选中、完整保留/淘汰划分且淘汰装备确认未锁')
        context=getattr(self.navigator,'batch_inventory_context',())
        counts=[re.fullmatch(r'(\d+)/(\d+)',x) for x in context]
        counts=[m for m in counts if m]
        if len(counts)!=1:
            raise ValueError('缺少本批入口的已核对背包数量，未处置')
        inventory_count,capacity=map(int,counts[0].groups())
        # 十连打造可令持有量暂时超过容量；超容量正是需要清理的合法状态。
        if capacity<=0 or inventory_count<len(items):
            raise ValueError('登记背包数量无效')
        self.guard.check_clear()
        self.locked_indices={index for index,item in enumerate(items) if item.locked is True}
        self.boosted_red_indices={index for index,item in enumerate(items) if item.equipment.enhancement_bonus}
        observer=getattr(self.enhancement,'observe_unchanged',self.enhancement.observe)
        screen,fresh,resources=observer(items)
        self.enhancement.unchanged(items,fresh)
        if resources.has_preview:
            raise ValueError('已有强化材料登记，不进入整理')
        tracked=resources.available is not None
        if resources.has_preview:
            raise ValueError('出售资源基线仍有强化材料登记，不进入整理')
        reference=screen.source
        gold=resources.available['gold'] if tracked else None
        self.navigator.transition('organize_batch')
        screen,state=self.observe(reference,len(items),gold)
        self.emit('batch_sale_auto_select_intent',image=screen.source)
        self.click(screen,'自动选择',(10,60,160,130))
        screen,state=self.observe(reference,len(items),gold)
        for index,item in enumerate(items):
            target=item.token in rejected
            if state.selected[index] is target:
                continue
            screen,fresh=self.observe(reference,len(items),gold)
            if fresh.selected!=state.selected:
                raise ValueError('整理补选前选择集合变化')
            dx,dy=origin(index)
            self.emit('batch_sale_toggle_intent',token=item.token,selected=target,image=screen.source)
            self.navigator.control.checkpoint()
            self.navigator.adb.tap(62+dx,185+dy)
            self.navigator.control.wait(.4)
            screen,after=self.observe(reference,len(items),gold)
            expected=list(state.selected);expected[index]=target
            if after.selected!=tuple(expected):
                raise ValueError('整理补选未恰好改变一件装备，未重试点击')
            state=after
        screen,fresh=self.observe(reference,len(items),gold)
        if {i.token for i,selected in zip(items,fresh.selected) if selected}!=rejected:
            raise ValueError('整理勾选不等于明确淘汰名单，未打开出售')
        self.click(screen,'出售',(210,60,370,130))
        confirmation=None
        warning_confirmed=False
        for _ in range(6):
            screen=self.navigator.read()
            if screen.page=='sale_level_warning':
                if warning_confirmed or not any(i.equipment.enhancement==15 for i in items if i.token in rejected):
                    raise ValueError('整理提示重复或淘汰名单没有+15装备，未继续')
                self.emit('batch_sale_level_warning_intent',rejected=sorted(rejected),image=screen.source)
                self.click(screen,'确认',(540,490,735,570))
                warning_confirmed=True
                continue
            if screen.page=='sale_confirmation':
                confirmation=self.confirmation_reader(screen)
                break
            if screen.page not in {'batch_organize','unknown'}:
                raise ValueError('出售入口出现意外页面，未确认')
            self.navigator.control.wait(.4)
        if confirmation is None:
            raise TimeoutError('出售弹窗未出现，不重试入口')
        if confirmation.count!=len(rejected):
            raise ValueError('出售弹窗件数不等于明确淘汰名单')
        expected_types={'jewelry_powder' if item.equipment.slot in {'ring','necklace'} else 'powder'
                        for item in items if item.token in rejected}
        actual_types={key for key in ('powder','jewelry_powder') if getattr(confirmation,key)>0}
        if expected_types!=actual_types or (tracked and not expected_types<=resources.available.keys()):
            raise ValueError('出售产物类别与淘汰装备部位不符，未确认')
        previous=confirmation
        for attempt in range(6):
            screen=self.navigator.read()
            stable=self.confirmation_reader(screen)
            if any(getattr(confirmation,key)!=getattr(stable,key)
                   for key in ('count','gold','powder','jewelry_powder')):
                raise ValueError('出售确认前件数或产物变化')
            if sale_confirmation_unchanged(previous,stable):
                break
            self.emit('batch_sale_preview_render_wait',attempt=attempt+1,image=screen.source)
            previous=stable
            self.navigator.control.wait(.3)
        else:
            raise ValueError('出售弹窗连续画面仍不稳定，未确认')
        operation_id=self.guard.begin('sell',
            {'items':[asdict(i) for i in items],'rejected':sorted(rejected),
             'inventory_count':inventory_count,'capacity':capacity,'resources':resources.available},
            asdict(stable),self.navigator.directory)
        self.pending=True
        self.emit('batch_sale_commit_intent',operation_id=operation_id,
                  pending_record=str(self.guard.path),confirmation=asdict(stable))
        self.click(screen,'确认',(650,490,850,570))  # 单次输入；此后异常保留持久化记录。
        for _ in range(8):
            screen=self.navigator.read()
            if screen.page in {'sale_confirmation','unknown'}:
                self.navigator.control.wait(.4)
                continue
            if screen.page not in {'batch_organize','batch_enhancement','inventory','inventory_batch_selection','inventory_batch_selection_empty'}:
                raise ValueError('出售后未确认批量页面，保留未结算记录')
            break
        else:
            raise TimeoutError('出售结果未知，不重复确认')
        return self.settle_result(items,rejected,protected,resources.available,reference,confirmation,
                                  inventory_count,capacity,operation_id,screen.page)

    def settle_result(self,items,rejected,protected,resources_before,reference,confirmation,
                      inventory_count,capacity,operation_id,page,*,historical_survivors=None):
        """只核验已提交出售的结果；支持原生自动返回强化页，不重发出售确认。"""
        pending=self.guard.read()
        if pending is None or pending['operation_id']!=operation_id:
            raise ValueError('出售结算记录身份不符')
        survivors=[i for i in items if i.token not in rejected]
        returned_inventory=page in {'inventory','inventory_batch_selection','inventory_batch_selection_empty'}
        if returned_inventory and survivors and historical_survivors is None:
            raise ValueError('仍有保留装备时意外返回背包，需复核保留装备')
        if page=='batch_organize':
            from .workflow_navigation import NavigationPageChanged
            try:
                self.navigator.transition('cancel_batch_organize')
            except NavigationPageChanged as exc:
                # 整批售空也可能直接返回背包；只更新现场，不发送过期取消。
                if exc.screen.page=='batch_enhancement':
                    page=exc.screen.page
                elif not survivors and exc.screen.page in {'inventory','inventory_batch_selection','inventory_batch_selection_empty'}:
                    page=exc.screen.page
                    returned_inventory=True
                else:
                    raise
        elif page!='batch_enhancement' and not returned_inventory and not (page=='forge' and historical_survivors):
            raise ValueError('出售结果页面不明确，不结算')
        tracked=resources_before is not None
        if survivors:
            if historical_survivors is not None:
                if tracked or len(historical_survivors)!=2:
                    raise ValueError('历史保留凭据只支持未跟踪余额且完整的双帧核验')
                after_screen,stable_screen=historical_survivors
                for observed in historical_survivors:
                    self.survivor_reader(observed,reference,items,rejected)
            else:
                after_screen=self.observe_survivors(reference,items,rejected)
                stable_screen=self.observe_survivors(reference,items,rejected)
            after=self.enhancement.resource_reader(after_screen)
            stable_resources=self.enhancement.resource_reader(stable_screen)
            self.enhancement.same_resources(after,stable_resources)
            self.emit('batch_sale_survivors_verified',operation_id=operation_id,
                      images=[after_screen.source,stable_screen.source],historical=historical_survivors is not None)
        elif not returned_inventory:
            screen=self.navigator.read()
            if screen.page!='batch_enhancement':
                raise ValueError('出售后空批页面未确认')
            report=self.enhancement.batch_reader(screen.source,{})
            if report['issues'] or report['records'] or any(s['state']!='empty' for s in report['slots']):
                raise ValueError('出售后仍有装备或未知槽位')
            after=self.enhancement.resource_reader(screen)
        else:
            screen=self.navigator.read()
            if tracked:
                raise ValueError('返回背包后无法核对完整材料余额，保留待核验记录')
            from .batch_resources import UntrackedBatchResources
            after=UntrackedBatchResources(None,screen.source)
        expected=None
        if tracked:
            expected=dict(resources_before)
            expected['gold']+=confirmation.gold
            if confirmation.powder:
                expected['powder']+=confirmation.powder
            if confirmation.jewelry_powder:
                expected['jewelry_powder']+=confirmation.jewelry_powder
            if after.available!=expected or after.gold_cost or any(after.reserved.values()):
                raise ValueError('出售金币/返还粉末或其他材料与预览不符，未结算')
        elif after.has_preview:
            raise ValueError('出售后出现强化预览，未结算')
        inventory=(inspect_inventory(self.navigator.navigate('inventory')) if tracked else
                   inspect_inventory(self.navigator.navigate('inventory'),track_gold=False))
        if ((inventory.count,inventory.capacity)!=(inventory_count-len(rejected),capacity)
                or (tracked and inventory.gold!=expected['gold'])):
            raise ValueError('出售后背包减量、容量或金币与登记不符，未结算')
        if returned_inventory:
            stable=inspect_inventory(self.navigator.read(),track_gold=tracked)
            if (stable.count,stable.capacity,stable.selected,stable.gold)!=(inventory.count,inventory.capacity,inventory.selected,inventory.gold):
                raise ValueError('出售后返回背包的数量尚未稳定')
        self.emit('batch_sale_settled',operation_id=operation_id,disposed=sorted(rejected),
                  resources_after=after.available,inventory_after=asdict(inventory))
        self.guard.settle(operation_id)
        self.pending=False
        self.enhancement.last_image=inventory.image
        return {'disposed':sorted(rejected),'protected':sorted(protected),'image':inventory.image}
