"""原生批量强化驱动；调用方共享账本，确认只发送一次。"""
from dataclasses import asdict, dataclass, replace

from .batch_resources import inspect_resources, verify_material_preview
from .batch_vision import inspect_batch,verify_selection_page
from .workflow import BatchItem, verify_batch


class BatchObservationError(ValueError):
    """只可重读画面，不代表可以重复发送输入。"""


@dataclass(frozen=True)
class BatchPreview:
    target: int
    cost: dict
    resources: dict
    image: str
    items: list
    before: object
    prepared: object


class BatchEnhancementDriver:
    def __init__(self,navigator,batch_reader=inspect_batch,resource_reader=inspect_resources,guard=None,track_resources=True,
                 purple_speed_only=False,ignore_equipment_level=None):
        self.navigator,self.batch_reader,self.resource_reader = navigator,batch_reader,resource_reader
        self.committed = set()
        self.guard, self.pending_ids = guard, {}
        self.last_image = None
        self.verified_items = None
        self.partial_observation = None
        self.verified_level_anchors = dict(getattr(navigator,'batch_verified_level_anchors',{}))
        if navigator is not None:
            navigator.batch_verified_level_anchors = {}  # 一次交接；不得沿用到另一批。
        self.resource_untracked = not track_resources
        self.purple_speed_only = purple_speed_only
        self.speed_rows = dict(getattr(navigator,'batch_speed_rows',{}))
        if navigator is not None:
            navigator.batch_speed_rows={}
        self.ignore_equipment_level=(getattr(navigator,'batch_ignore_equipment_level',False)
                                     if ignore_equipment_level is None else ignore_equipment_level)
        if self.resource_untracked:
            from .batch_resources import inspect_untracked_resources
            self.resource_reader = inspect_untracked_resources

    def normalize_items(self,items):
        if not self.purple_speed_only:
            return items
        result=[]
        for index,item in enumerate(items):
            if item.equipment.rarity!='purple' or 'speed' not in item.equipment.stats or item.equipment.slot=='boots':
                result.append(item)
                continue
            if index not in self.speed_rows:
                if item.equipment.observation_scope!='full' or 'speed' not in item.equipment.stats:
                    raise ValueError('速度专读必须先由完整入口登记速度行')
                self.speed_rows[index]=list(item.equipment.stats).index('speed')
            result.append(replace(item,equipment=replace(item.equipment,stats={'speed':item.equipment.stats['speed']},
                                                        game_score=None,observation_scope='purple_speed',
                                                        main_stat=None,main_stat_usable=True)))
        return result

    def observe(self,expected,*,screen=None):
        import time
        if screen is None:
            screen = (self.navigator.read_batch() if self.resource_untracked and self.batch_reader is inspect_batch
                      and hasattr(self.navigator,'read_batch') else self.navigator.read())
        started=time.perf_counter()
        if screen.page == 'enhancement_refund':
            from .workflow_navigation import NavigationPageChanged
            try:
                screen = self.navigator.transition('dismiss_enhancement_refund')
            except NavigationPageChanged as exc:
                if exc.screen.page!='batch_enhancement':
                    raise
                # 提示自动消失，transition尚未发送输入；直接核验新帧的完整结果。
                screen=exc.screen
        if screen.page != 'batch_enhancement':
            self.partial_observation=None
            if screen.page == 'unknown':
                raise BatchObservationError('批量画面尚未稳定')
            raise ValueError('当前不是批量强化页面，未发送输入')
        if not expected or len({item.token for item in expected}) != len(expected):
            raise ValueError('批量登记缺失或标识重复')
        try:
            slots={i:item.equipment.slot for i,item in enumerate(expected)}
            if (self.purple_speed_only and all(item.equipment.observation_scope=='purple_speed' for item in expected)
                    and all(index in self.speed_rows for index in range(len(expected)))):
                from .purple_speed_vision import inspect_purple_speed_batch
                report=inspect_purple_speed_batch(screen,expected,self.speed_rows,self.verified_level_anchors,
                                                  ignore_levels=self.ignore_equipment_level)
            elif self.batch_reader is inspect_batch:
                report=self.batch_reader(screen.source,slots,verified_level_anchors=self.verified_level_anchors,
                                         ignore_levels=self.ignore_equipment_level,
                                         require_score=(not self.resource_untracked or any(
                                             i.equipment.game_score is not None for i in expected)),
                                         known_items=expected,
                                         reference_path=self.last_image if self.resource_untracked else None,
                                         ignore_purple_main=self.resource_untracked,
                                         purple_speed_only=self.purple_speed_only,speed_rows=self.speed_rows,
                                         retry_report=self.partial_observation)
            else:
                report = (self.batch_reader(screen.source,slots,
                        verified_level_anchors=self.verified_level_anchors)
                      if self.verified_level_anchors else self.batch_reader(screen.source,slots))
        except ValueError as exc:
            raise BatchObservationError(str(exc)) from exc
        if report.get('issues') or [r['index'] for r in report['records']] != list(range(len(expected))):
            self.partial_observation=report if self.batch_reader is inspect_batch else None
            if getattr(self.navigator,'journal',None):
                self.navigator.journal.emit('batch_observation_rejected',image=screen.source,
                    issues=report.get('issues',[]),indices=[r['index'] for r in report['records']],
                    expected_count=len(expected))
            raise BatchObservationError('批量装备识别不完整，不能驱动强化')
        self.partial_observation=None
        states = [slot['state'] for slot in report.get('slots',[])]
        if states != ['occupied']*len(expected)+['empty']*(16-len(expected)):
            raise BatchObservationError('批量占用槽位或尾批空槽不明确')
        items = []
        for old,record in zip(expected,report['records']):
            observed = record['equipment']
            if old.locked is not None and record.get('locked') is None:
                raise BatchObservationError('批量锁按钮尚未可靠读取，只读重试')
            if (old.equipment.rarity!='purple' and old.equipment.main_stat is not None
                    and (record.get('main') or {}).get('stat')!=old.equipment.main_stat):
                raise ValueError('批量装备主属性发生变化')
            if any(observed[key] != getattr(old.equipment,key) for key in ('rarity','level','slot')):
                raise ValueError('批量装备品质、等级或部位发生变化')
            if observed.get('enhancement_bonus',False)!=old.equipment.enhancement_bonus:
                raise ValueError('批量装备强化加成分类发生变化')
            if not observed['recognition_ok']:
                raise ValueError('批量装备未可靠识别')
            if observed.get('observation_scope','full')!=old.equipment.observation_scope:
                raise BatchObservationError('批量装备读取范围发生变化，需要保持本批登记的属性范围')
            item = replace(old.equipment, enhancement=observed['enhancement'], stats=observed['stats'],
                           game_score=observed['game_score'])
            if not old.selected and item != old.equipment:
                # 点击光圈也会把完整数字误读成另一个有效值（如34→54）。
                # 未选中卡片必须不变；只读重试，不缓存这张受遮挡的候选。
                raise BatchObservationError('未选中装备读数发生变化，等待无遮挡画面复核')
            items.append(BatchItem(old.token,item,record['selected'],record.get('locked')))
        try:
            resources = self.resource_reader(screen)
        except ValueError as exc:
            raise BatchObservationError(str(exc)) from exc
        # 恢复记录可能只有速度值而没有速度行；当前画面完整核对成功后才补登记。
        if self.purple_speed_only:
            for index,speed_row in report.get('speed_rows',{}).items():
                if items[index].equipment.observation_scope=='purple_speed':
                    self.speed_rows[index]=speed_row
        self.remember_observation(screen,items)
        if getattr(self.navigator,'journal',None):
            self.navigator.journal.emit('batch_ocr_timing',image=screen.source,
                                       seconds=round(time.perf_counter()-started,4),
                                       scope='mixed' if len({i.equipment.observation_scope for i in items})>1 else items[0].equipment.observation_scope,
                                       purple_speed_cards=sum(i.equipment.observation_scope=='purple_speed' for i in items),
                                       reused_cards=sum(r.get('content_source')=='unchanged_pixels' for r in report['records']))
        return screen,items,resources

    def remember_observation(self,screen,items):
        from copy import deepcopy
        self.last_image=screen.source
        self.verified_items=deepcopy(items)

    def observe_unchanged(self,expected):
        """当前批次只读核验；光效/局部拒识最多重读三次，不重发任何输入。"""
        for attempt in range(3):
            try:
                return self._observe_unchanged(expected)
            except BatchObservationError as exc:
                if attempt==2:
                    raise
                if getattr(self.navigator,'journal',None):
                    self.navigator.journal.emit('batch_unchanged_read_retry',attempt=attempt+1,
                                                message=str(exc),input_repeated=False)
                self.navigator.control.wait(.2)

    def _observe_unchanged(self,expected):
        """同批内容未变时核对新截图，证据不符则完整OCR。"""
        if (not self.resource_untracked or self.batch_reader is not inspect_batch
                or not hasattr(self.navigator,'read_batch') or not self.last_image or not self.verified_items):
            return self.observe(expected)
        def visual(items):
            data=[asdict(item) for item in items]
            for item in data:
                item['equipment'].pop('last_speed_increased',None)
                item['equipment'].pop('early_speed_increased',None)
                item['equipment'].pop('red_speed_misses',None)
            return data
        if visual(expected)!=visual(self.verified_items):
            return self.observe(expected)
        from .batch_vision import verify_stable_batch_pixels
        screen=self.navigator.read_batch()
        try:
            if screen.page!='batch_enhancement':raise ValueError('批量页变化')
            verify_stable_batch_pixels(self.last_image,screen.source,expected)
            resources=self.resource_reader(screen)
        except ValueError:
            return self.observe(expected,screen=screen)
        reference=self.last_image
        self.remember_observation(screen,expected)
        if self.navigator.journal:
            self.navigator.journal.emit('batch_unchanged_pixels_verified',image=screen.source,
                                       reference=reference,number_ocr_repeated=False)
        return screen,expected,resources

    @staticmethod
    def unchanged(before,after):
        if [asdict(item) for item in before] != [asdict(item) for item in after]:
            raise ValueError('登记或确认期间装备、属性、锁状态或勾选集合变化')

    @staticmethod
    def same_resources(a,b):
        if (a.available,a.remaining,a.reserved,a.gold_cost,a.target) != (b.available,b.remaining,b.reserved,b.gold_cost,b.target):
            raise ValueError('确认前资源或目标预览发生变化')

    def observe_selection_result(self,expected):
        for attempt in range(3):
            try:
                return self.observe(expected)
            except BatchObservationError:
                if attempt==2:
                    raise
                self.navigator.control.wait(.2)

    def select_active(self,items,active):
        if not active <= {item.token for item in items}:
            raise ValueError('选择目标不在本批次')
        if all(item.selected==(item.token in active) for item in items):
            return items
        screen,current,resources=self.observe_unchanged(items)
        self.unchanged(items,current)
        if resources.has_preview:
            raise ValueError('尚有登记材料，不能调整批量装备选择')
        reference=screen.source
        for index in range(len(current)):
            target = current[index].token in active
            if current[index].selected is target:
                continue
            row,col = divmod(index,4)
            x,y = round((80+col*316.667)*1280/1661),round((240+row*167.333)*720/933)
            if self.navigator.journal:
                self.navigator.journal.emit('batch_toggle_intent',token=current[index].token,selected=target,image=screen.source)
            self.navigator.adb.tap(x,y)
            expected = [replace(item,selected=target) if i==index else item for i,item in enumerate(current)]
            # 选择本身不消耗资源。逐次核验页面与全部勾选边框，整组完成后再
            # 完整复核属性、身份、锁和资源，减少每次取消的重复数字OCR。
            screen=self.observe_selection_flags(expected,screen)
            current = expected
        if self.resource_untracked and self.batch_reader is inspect_batch:
            from .batch_vision import verify_stable_batch_pixels
            try:
                verify_stable_batch_pixels(reference,screen.source,current)
                after_resources=self.resource_reader(screen)
                self.same_resources(resources,after_resources)
            except ValueError:
                _,after,after_resources=self.observe_selection_result(current)
            else:
                after=current
                self.last_image=screen.source
                if self.navigator.journal:
                    self.navigator.journal.emit('batch_selection_content_verified',image=screen.source,
                                                 reference=reference,number_ocr_repeated=False)
        else:
            _,after,after_resources=self.observe_selection_result(current)
        self.unchanged(current,after)
        self.same_resources(resources,after_resources)
        # fallback观察可能拍了更新的截图，不能用更早的选择动画帧覆盖它。
        if after is current:
            self.remember_observation(screen,after)
        return after

    def observe_selection_flags(self,expected,reference):
        import uuid
        for attempt in range(3):
            self.navigator.control.wait(.2)
            self.navigator.control.checkpoint()
            path=self.navigator.directory/('selection-'+uuid.uuid4().hex[:12]+'.png')
            self.navigator.adb.screenshot(str(path))
            flags=verify_selection_page(reference.source,path,len(expected))
            if flags==[item.selected for item in expected]:
                self.navigator.last_image=str(path.resolve())
                if self.navigator.journal:
                    self.navigator.journal.emit('batch_selection_graph_verified',image=str(path.resolve()),flags=flags)
                return replace(reference,source=str(path.resolve()),words=())
        raise BatchObservationError('批量选择边框尚未确认，不重发点击')

    def prepare_enhancement(self,items,target):
        if target not in (3,6,9,12,15):
            raise ValueError('非法批量强化目标')
        screen,current,before = self.observe_unchanged(items)
        self.unchanged(items,current)
        selected = [item for item in items if item.selected]
        if not selected or any(item.equipment.enhancement >= target for item in selected):
            raise ValueError('强化目标必须高于每件已选装备的实际等级')
        if before.has_preview:
            if self.resource_untracked and before.target == target:
                # 已核对同批属性和勾选；沿用迟到的同目标预览，不再点击阶段按钮。
                if getattr(self.navigator,'journal',None):
                    self.navigator.journal.emit('batch_existing_preview_verified',target=target,image=screen.source)
                return BatchPreview(target,None,None,screen.source,items,before,before)
            raise ValueError('已有其他目标或需核账的登记材料，未重新选择强化目标')
        for attempt in range(3 if self.resource_untracked else 1):
            word = screen.find(f'+{target}阶段',(0,630,1000,710))
            if self.navigator.journal:
                self.navigator.journal.emit('batch_stage_preview_intent',target=target,image=screen.source,
                                            attempt=attempt+1,
                                            x=round(word['center'][0]),y=round(word['center'][1]))
            self.navigator.adb.tap(*(round(v) for v in word['center']))
            self.navigator.control.wait(.3)
            screen,prepared_items,prepared = self.observe_unchanged(items)
            self.unchanged(items,prepared_items)
            if not self.resource_untracked or prepared.target==target:
                break
            if prepared.has_preview:
                raise ValueError('出现其他阶段预览，不覆盖已有登记')
            # 仅在新截图明确无材料登记、装备未变化时重试非消耗性的阶段按钮。
            # 识别失败在observe_unchanged中只读重试，强化确认始终不重发。
        if self.resource_untracked:
            if prepared.target != target:
                raise ValueError('目标阶段未选中，可能材料耗尽，停止强化')
            cost, available = None, None
        else:
            cost = verify_material_preview(before,prepared,target,items)
            available = dict(before.available)
        return BatchPreview(target,cost,available,screen.source,items,before,prepared)

    def commit_enhancement(self,preview):
        if preview.image in self.committed:
            raise ValueError('该批量强化确认已经发送，禁止重试')
        if self.guard is not None:
            self.guard.check_clear()
        screen,current,resources = self.observe_unchanged(preview.items)
        self.unchanged(preview.items,current)
        self.same_resources(preview.prepared,resources)
        word = screen.find('强化',(1150,630,1270,710))
        if self.guard is not None:
            self.pending_ids[preview.image] = self.guard.begin('batch_enhance',
                {'resources':preview.resources,'items':[asdict(item) for item in preview.items],
                 'inventory_context':getattr(self.navigator,'batch_inventory_context',None)},
                {'target':preview.target,'cost':preview.cost,'image':screen.source},
                self.navigator.directory)
        if self.navigator.journal:
            self.navigator.journal.emit('batch_enhance_commit_intent',target=preview.target,cost=preview.cost,image=screen.source)
        self.committed.add(preview.image)  # 输入失败也不能自动重复发送。
        self.navigator.adb.tap(*(round(v) for v in word['center']))

    def settle_enhancement(self,preview):
        """装备结果已复核，且调用方完成当前统计模式结算后调用。"""
        if self.guard is not None:
            self.guard.settle(self.pending_ids[preview.image])
            del self.pending_ids[preview.image]

    def lock_items(self,items,targets):
        from PIL import Image
        from .lock_vision import batch_offset,inspect_batch_lock,verify_batch_lock_pixels
        from .workflow import verify_lock_update
        if not targets <= {item.token for item in items}:
            raise ValueError('上锁目标不在本批次')
        current=items
        for index,item in enumerate(current):
            if item.token not in targets:
                continue
            screen,fresh,resources=self.observe_unchanged(current)
            self.unchanged(current,fresh)
            if item.locked is True:
                continue
            if item.locked is not False:
                raise ValueError('锁状态未知，不点击切换按钮')
            if resources.has_preview:
                raise ValueError('仍有材料登记，不能上锁')
            dx,dy=batch_offset(index)
            if self.navigator.journal:
                self.navigator.journal.emit('batch_lock_intent',token=item.token,image=screen.source)
            self.navigator.control.checkpoint()
            self.navigator.adb.tap(round((300+dx)*1280/1661),round((192+dy)*720/933))
            # 每件目标只输入一次，后续仅重读；未知时不重试切换按钮。
            for _ in range(8):
                self.navigator.control.wait(.5)
                after_screen=(self.navigator.read_batch() if self.resource_untracked and hasattr(self.navigator,'read_batch')
                              else self.navigator.read())
                if after_screen.page=='unknown':
                    continue
                if after_screen.page!='batch_enhancement':
                    raise ValueError('上锁后离开批量页，停止复核')
                with Image.open(screen.source) as before,Image.open(after_screen.source) as after:
                    state=inspect_batch_lock(after,'batch_enhancement',index,True)
                    if state['locked'] is not True:
                        continue
                    try:
                        verify_batch_lock_pixels(before,after,len(current),index,
                                                 attributes_only=self.ignore_equipment_level)
                    except ValueError:
                        # 已保护装备提示可能覆盖底行；只等待/重拍，不重复切锁。
                        continue
                # 只有像素证明本次锁动作未改变装备内容后，才建立遮挡等级的本地证据。
                self.verified_level_anchors[index]=after_screen.source
                _,observed,after_resources=self.observe(current)
                verify_lock_update(current,observed,{item.token})
                self.same_resources(resources,after_resources)
                current=observed
                if self.navigator.journal:
                    self.navigator.journal.emit('batch_lock_verified',token=item.token,image=after_screen.source)
                break
            else:
                raise TimeoutError('上锁结果未确认，不重复点击')
        return current

    def dispose_batch(self,items,rejected,protected,action):
        from .batch_sale import BatchSaleDriver
        return BatchSaleDriver(self).sell(items,rejected,protected,action)

    def finish_enhancement(self,preview):
        if preview.image not in self.committed:
            raise ValueError('尚未发送批量强化确认')
        for attempt in range(8):
            self.navigator.control.wait(.2 if attempt==0 else min(.8,.2+attempt*.1))
            try:
                if (self.resource_untracked and self.batch_reader is inspect_batch
                        and hasattr(self.navigator,'read_batch')):
                    screen=self.navigator.read_batch()
                    if screen.page=='batch_enhancement':
                        try:
                            pending=self.resource_reader(screen).has_preview
                        except ValueError as exc:
                            raise BatchObservationError(str(exc)) from exc
                        if pending:
                            if getattr(self.navigator,'journal',None):
                                self.navigator.journal.emit('batch_result_animation_wait',attempt=attempt+1,
                                    image=screen.source,attribute_ocr_skipped=True)
                            continue
                    # 动画预览清除后复用本帧，不额外截图或降低属性/稳定性核验。
                    screen,items,resources = self.observe(preview.items,screen=screen)
                else:
                    screen,items,resources = self.observe(preview.items)
            except BatchObservationError as exc:
                if getattr(self.navigator,'journal',None):
                    self.navigator.journal.emit('batch_result_read_retry',attempt=attempt+1,message=str(exc))
                continue
            if resources.has_preview:
                continue  # 动画或预览尚未清除，只读取，不重发确认。
            if any(old.selected and new.equipment.enhancement<preview.target
                   for old,new in zip(preview.items,items)):
                # 资源区先清空、卡片动画后完成时，仅等待结果，不重复确认。
                verify_batch(preview.items,items,0)
                if any(new.equipment.enhancement<old.equipment.enhancement
                       for old,new in zip(preview.items,items)):
                    raise ValueError('强化动画期间等级回退，停止读取')
                continue
            verify_batch(preview.items,items,preview.target)
            try:
                stable_screen,stable,stable_resources=self.stable_result(screen,items,resources,preview)
            except BatchObservationError as exc:
                if getattr(self.navigator,'journal',None):
                    self.navigator.journal.emit('batch_result_read_retry',attempt=attempt+1,
                                                message=str(exc),stage='stability')
                continue
            self.unchanged(items,stable)
            self.same_resources(resources,stable_resources)
            self.remember_observation(stable_screen,stable)
            # 交给WorkflowTask共享Ledger结算，包括发生不符时记录真实差额。
            return {'items':stable,'resources':None if self.resource_untracked else dict(stable_resources.available),'image':stable_screen.source}
        raise TimeoutError('批量强化结果未确认，禁止重试确认')

    def stable_result(self,screen,items,resources,preview):
        """第二帧拒识同样属于只读重试；真实身份或资源冲突仍向上报告。"""
        if (self.resource_untracked and self.batch_reader is inspect_batch
                and hasattr(self.navigator,'read_navigation')):
            from .batch_vision import verify_stable_batch_pixels
            stable_screen=(self.navigator.read_batch() if hasattr(self.navigator,'read_batch') else
                           self.navigator.read_navigation({'batch_enhancement'}))
            try:
                if stable_screen.page!='batch_enhancement':
                    raise ValueError('稳定性复核不是批量强化页')
                verify_stable_batch_pixels(screen.source,stable_screen.source,items)
                stable_resources=self.resource_reader(stable_screen)
                self.same_resources(resources,stable_resources)
            except ValueError:
                # 外层结果循环统一重试；复用本帧，不叠加三次读取。
                return self.observe(preview.items,screen=stable_screen)
            self.last_image=stable_screen.source
            if self.navigator.journal:
                self.navigator.journal.emit('batch_result_pixels_verified',image=stable_screen.source,
                                             reference=screen.source,number_ocr_repeated=False)
            return stable_screen,items,stable_resources
        return self.observe(preview.items)
