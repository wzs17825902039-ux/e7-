"""选装到原生批量页：核对数量、顺序及全部初始属性，入口不消耗材料。"""
from dataclasses import asdict

from .batch_vision import inspect_batch
from .rules import Equipment
from .workflow import BatchItem
from .vision import ATTRIBUTE_NAMES


def verify_entry(selection, report,policy=None):
    expected = selection.get('registered', [])
    count = selection['selected_count']
    if not 1 <= count <= 16 or len(expected) != count:
        raise ValueError('初始装备登记不完整，不能进入批量强化')
    if report.get('page') != 'batch_enhancement' or report.get('issues'):
        raise ValueError('批量页面存在识别失败，不进入强化')
    slots = report.get('slots', [])
    if len(slots) != 16 or [s['index'] for s in slots] != list(range(16)):
        raise ValueError('批量槽位证据不完整')
    if [s['state'] for s in slots] != ['occupied'] * count + ['empty'] * (16-count):
        raise ValueError('批量占用数量、排列或尾批空槽未确认')
    records = report['records']
    if [r['index'] for r in records] != list(range(count)):
        raise ValueError('批量装备顺序或数量不符')
    items = []
    for index, (old, new) in enumerate(zip(expected, records)):
        a, b = old['equipment'], new['equipment']
        if a.get('enhancement_bonus',False)!=b.get('enhancement_bonus',False):
            raise ValueError('批量强化加成红装类型与入口标题不符')
        if old.get('selection_only') is True:
            for field in ('rarity','level','enhancement','slot'):
                if a[field]!=b[field]:
                    raise ValueError(f'批量第{index+1}件装备{field}与背包选装不符')
            if (type(a['enhancement']) is not int or not 0<=a['enhancement']<15
                    or not b.get('recognition_ok') or new['selected'] is not True
                    or new.get('locked') not in (True,False)
                    or b['rarity']!='purple' and new.get('main') is None):
                raise ValueError('批量初始属性、选中、锁或主属性未确认')
            equipment=Equipment(**b)
            from .rules import Policy,RIGHT_MAIN_STATS,FLATS
            active_policy=policy or Policy()
            if equipment.rarity=='purple':
                equipment.main_stat=None
                equipment.main_stat_usable=True
            elif equipment.slot in RIGHT_MAIN_STATS:
                main_key=new['main']['stat']
                equipment.main_stat=main_key
                if main_key not in RIGHT_MAIN_STATS[equipment.slot]:
                    raise ValueError('批量主属性与部位不符')
                equipment.main_stat_usable=main_key in active_policy.right_main_stats.get(equipment.slot,[])
                if main_key in FLATS and equipment.stats.get('speed',0)<=0:
                    equipment.main_stat_usable=False
            items.append(BatchItem(str(index),equipment,True,new['locked']))
            continue
        for field in ('rarity','level','enhancement','slot','stats','game_score'):
            if a[field] != b[field]:
                raise ValueError(f'批量第{index+1}件装备{field}与背包登记不符')
        label, value = old['main']
        if label not in ATTRIBUTE_NAMES:
            raise ValueError('背包登记主属性不明确')
        key = ATTRIBUTE_NAMES[label][0 if value.endswith('%') else 1]
        if new.get('main') != {'stat':key, 'value':int(value.rstrip('%'))}:
            raise ValueError('批量主属性与背包登记不符或未确认')
        if (type(a['enhancement']) is not int or not 0 <= a['enhancement'] < 15
                or not b.get('recognition_ok') or new['selected'] is not True):
            raise ValueError('批量初始装备不是已确认且选中的+0～+14装备')
        equipment = Equipment(**a)
        items.append(BatchItem(str(index), equipment, True, new.get('locked')))
    return items


class BatchEntryDriver:
    def __init__(self, selector, batch_reader=inspect_batch):
        self.selector, self.navigator, self.batch_reader = selector, selector.navigator, batch_reader

    def enter(self, selection):
        count = selection['selected_count']
        if not 1 <= count <= 16 or len(selection.get('registered', [])) != count:
            raise ValueError('选装登记未完成，未点击批量入口')
        if count < 16 and selection.get('scan_complete') is not True:
            evidence = selection.get('scan_evidence',{})
            if evidence.get('end_verified') and not evidence.get('top_verified'):
                raise ValueError('已确认列表底部，但未确认从顶部完整扫描，未把当前视口当作完整尾批')
            raise ValueError('不足16件但尚未确认扫描末尾，未把当前可见行当尾批')
        fresh = self.selector.observe()
        # 登记是独立于视觉快照的记录，不参与当前页面相等比较。
        visual = selection.get('visual_snapshot')
        if visual is None:
            visual = {key: value for key,value in selection.items()
                      if key not in ('source','selection_status','registered')}
        checker=getattr(self.selector,'verify_selection_unchanged',self.selector._verify_unchanged)
        checker(visual, {key:value for key,value in fresh.items() if key != 'source'})
        word = self.selector.screen.find(f'批量强化({count})', (1000,630,1250,710))
        if self.navigator.journal:
            self.navigator.journal.emit('batch_entry_intent', count=count, image=fresh['source'])
        self.navigator.adb.tap(*(round(v) for v in word['center']))
        screen = None
        for _ in range(8):
            self.navigator.control.wait(.4)
            screen = self.navigator.read()
            if screen.page == 'batch_enhancement':
                break
            if screen.page not in ('inventory_batch_selection','unknown'):
                raise ValueError('进入批量页时出现意外页面，未确认或重试')
        else:
            raise TimeoutError('进入批量页超时，未重复点击入口')
        return self.read_entry(selection,screen)

    def read_entry(self,selection,screen):
        """入口只读重试；绝不重发入口、强化或资源确认。身份冲突不重试。"""
        slots = {index:entry['equipment']['slot'] for index,entry in enumerate(selection['registered'])}
        report=None
        for attempt in range(3):
            if attempt:
                self.navigator.control.wait(.35*attempt)
                screen=(self.navigator.read_batch() if hasattr(self.navigator,'read_batch')
                        else self.navigator.read())
            if screen.page not in ('batch_enhancement','unknown'):
                raise ValueError('入口重读时页面已改变，不发送输入')
            error=None
            if screen.page=='unknown':
                error='批量页面尚未稳定'
            else:
                try:
                    report=self._read_report(selection,screen,slots,report)
                    if not report.get('issues'):
                        break
                    error='；'.join(report['issues'])
                except ValueError as exc:
                    error=str(exc)
                    report=None
            if self.navigator.journal:
                self.navigator.journal.emit('batch_entry_read_retry',attempt=attempt+1,
                    max_attempts=3,will_retry=attempt<2,message=error,image=screen.source,
                    input_repeated=False)
        else:
            raise ValueError(f'批量入口识别3次仍未通过：{error}')
        items = verify_entry(selection, report,policy=getattr(self.selector,'policy',None))
        policy=getattr(self.selector,'policy',None)
        if policy and policy.custom_targets_enabled and any(rule['sets'] for rule in policy.custom_targets):
            from dataclasses import replace
            from .set_vision import inspect_batch_sets
            evidence=inspect_batch_sets(report['source'],[index for index,item in enumerate(items) if item.equipment.rarity=='red'])
            items=[replace(item,equipment=replace(item.equipment,gear_set=evidence[index]['set']))
                   if index in evidence else item for index,item in enumerate(items)]
            report['set_evidence']=evidence
            if self.navigator.journal:
                self.navigator.journal.emit('custom_target_sets_read',evidence=evidence,image=report['source'])
        # 只有完整入口核对成功后，才将本批锁遮挡图块交接给后续逐阶段读取。
        ignore_level=getattr(self.selector,'ignore_equipment_level',False)
        anchors={} if ignore_level else {r['index']:screen.source for r in report['records'] if r.get('locked') is True}
        self.navigator.batch_verified_level_anchors=anchors
        self.navigator.batch_speed_rows=report.get('speed_rows',{})
        self.navigator.batch_ignore_equipment_level=ignore_level
        report['verified_level_anchors']=anchors
        report['ignore_equipment_level']=self.navigator.batch_ignore_equipment_level
        self.navigator.batch_inventory_context=selection.get('inventory_context',())
        if self.navigator.journal:
            self.navigator.journal.emit('batch_entry_verified', image=screen.source,
                                        equipment=[asdict(item) for item in items])
        return report, items

    def _read_report(self,selection,screen,slots,previous=None):
        if self.batch_reader is inspect_batch:
            report = self.batch_reader(screen.source, slots,
                                       entry_details={i:entry for i,entry in enumerate(selection['registered'])
                                                      if not entry.get('selection_only')},
                                       ignore_levels=getattr(self.selector,'ignore_equipment_level',False),
                                       require_score=any(not e.get('selection_only') for e in selection['registered']),
                                       ignore_purple_main=all(e.get('selection_only') for e in selection['registered']),
                                       purple_speed_only=all(e.get('selection_only') for e in selection['registered']),
                                       boosted_red_indices={i for i,entry in enumerate(selection['registered'])
                                                            if entry['equipment'].get('enhancement_bonus') is True},
                                       registered_rarities={i:entry['equipment']['rarity']
                                                            for i,entry in enumerate(selection['registered'])},
                                       initial_indices={i for i,entry in enumerate(selection['registered'])
                                                        if entry['equipment']['enhancement']==0},
                                       retry_report=previous)
        else:
            report = self.batch_reader(screen.source, slots)
        if self.navigator.journal:
            self.navigator.journal.emit('batch_entry_observed', image=screen.source,
                                        slots=report.get('slots'), records=report.get('records'),
                                        issues=report.get('issues'))
        return report
