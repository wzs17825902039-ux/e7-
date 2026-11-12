from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import math
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_detail import read_detail
from e7_assistant.inventory_scan import InventoryTraversal
from e7_assistant.inventory_level_recovery import InventoryLevelRecovery
from e7_assistant.inventory_detail import detail_fingerprint
from e7_assistant.batch_vision import verify_detail_entry_level
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import TaskControl
from test_inventory_detail import screen
from scripts.probe_inventory_traversal import DetailProbeAdb


class RecoveryTests(unittest.TestCase):
    def driver(self, stages=(3,)):
        self.state = {'source':'list.png','page':'inventory_batch_selection',
                      'selected_count':0,'inventory_context':('最大强化','100/1200'),
                      'cards':[{'row':0,'column':i,'center':(190+99*i,211),
                                'rarity':'red','level':None,'enhancement':stage,'selected':False,
                                'known':False,'eligible':False,'identity_vector':[1.,0.]}
                               for i,stage in enumerate(stages)]}
        self.clicks=[]
        self.details=[]
        self.events=[]
        def tap(x,y):
            self.clicks.append((x,y))
            target=next(c for c in self.state['cards'] if c['center']==(x,y))
            target['selected']=not target['selected']
            self.state['selected_count']+=1 if target['selected'] else -1
        control=TaskControl(.2)
        control.wait=lambda seconds:control.checkpoint()
        nav=SimpleNamespace(read=lambda:deepcopy(self.state),control=control,
                            adb=SimpleNamespace(tap=tap),
                            journal=SimpleNamespace(emit=lambda kind,**data:self.events.append((kind,data))))
        def detail(observed,card):
            self.details.append(card['column'])
            return {'equipment':Equipment('test','red',85,card['enhancement'],'helmet',
                                           {'speed':4,'atk_pct':8,'crit':5,'cdmg':7},True,True,35),
                    'source':'detail.png','fingerprint':f"detail-{card['column']}",
                    'main':('生命值','540')}
        driver=BatchSelectionDriver(nav,reader=lambda value:value,detail_reader=detail,
                                    recover_detail_levels=True,policy=Policy(ignore_equipment_level=False))
        driver.level_recovery.detail_reader=detail
        return driver

    def test_missing_grade_is_independently_read_and_temporary_selection_restored(self):
        for stage in (0,3,14):
            with self.subTest(stage=stage):
                driver=self.driver((stage,))
                report=driver._begin(16)
                self.assertEqual(self.clicks,[(190,211)]*2)
                self.assertEqual(self.state['selected_count'],0)
                self.assertIsNone(self.state['cards'][0]['level'])
                self.assertEqual(report['cards'][0]['level'],85)
                self.assertTrue(report['cards'][0]['eligible'])
                self.assertEqual(report['cards'][0]['detail_level_evidence']['method'],'native_detail')

    def test_unchanged_frame_and_verified_selection_reuse_evidence_without_extra_clicks(self):
        driver=self.driver()
        report=driver._begin(16)
        fresh=driver.observe_unchanged(report)
        driver.navigator.adb.tap(190,211)
        after=driver._observe_click(fresh,(0,0))
        self.assertTrue(after['cards'][0]['selected'])
        self.assertEqual(self.clicks,[(190,211)]*3)
        self.assertEqual(self.details,[0])

    def test_unfinished_recovered_equipment_can_be_registered(self):
        driver=self.driver((3,14,15))
        result=driver.collect_visible(limit=2)
        self.assertEqual([r['equipment']['enhancement'] for r in result['registered']],[3,14])
        self.assertEqual(self.details,[0,1,0,1])  # 独立恢复与正式登记。
        self.assertEqual(len(self.clicks),6)

    def test_fifteen_and_other_unknown_fields_do_not_trigger_probe(self):
        for update in ({'enhancement':15},{'rarity':None},{'enhancement':None},{'selected':None}):
            driver=self.driver()
            self.state['cards'][0].update(update)
            if update.get('selected','missing') is None:
                with self.assertRaises(ValueError):
                    driver._begin(16)
            else:
                result=driver._begin(16)
                self.assertIsNone(result['cards'][0]['level'])
            self.assertEqual(self.clicks,[])

    def test_preexisting_selection_is_never_touched(self):
        driver=self.driver()
        self.state['cards'][0]['selected']=True
        self.state['selected_count']=1
        with self.assertRaises(ValueError):
            driver._begin(16)
        self.assertEqual(self.clicks,[])

    def test_detail_failure_restores_verified_temporary_selection(self):
        driver=self.driver()
        def fail(*args):
            raise ValueError('详情等级未确认')
        driver.level_recovery.detail_reader=fail
        with self.assertRaisesRegex(ValueError,'详情等级'):
            driver._begin(16)
        self.assertEqual(self.state['selected_count'],0)
        self.assertEqual(len(self.clicks),2)
        self.assertIsNone(driver.level_recovery.previous_verified)

    def test_wrong_detail_grade_quality_or_stage_is_rejected_and_restored(self):
        for field,value in (('level',88),('rarity','purple'),('enhancement',14),('recognition_ok',False)):
            driver=self.driver()
            original=driver.level_recovery.detail_reader
            def wrong(observed,card):
                detail=original(observed,card)
                detail['equipment']=replace(detail['equipment'],**{field:value})
                return detail
            driver.level_recovery.detail_reader=wrong
            with self.subTest(field=field),self.assertRaises(ValueError):
                driver._begin(16)
            self.assertEqual(self.state['selected_count'],0)

    def test_no_effect_probe_is_not_repeated(self):
        driver=self.driver()
        driver.navigator.adb.tap=lambda x,y:self.clicks.append((x,y))
        with self.assertRaises(ValueError):
            driver._begin(16)
        self.assertEqual(len(self.clicks),1)

    def test_untracked_selected_unknown_does_not_reorder_selection(self):
        driver=self.driver()
        driver._owns_selection=True
        self.state['selected_count']=1
        self.state['cards'][0]['selected']=True
        with self.assertRaisesRegex(ValueError,'不取消重选'):
            driver.observe()
        self.assertEqual(self.clicks,[])

    def test_two_complete_overlap_rows_transfer_detail_evidence(self):
        driver=self.driver()
        cards=[]
        for row in range(3):
            for column in range(7):
                card=deepcopy(self.state['cards'][0])
                angle=(row*7+column)*.2
                card.update(row=row,column=column,center=(190+column*99,211+row*133),
                            identity_vector=[math.cos(angle),math.sin(angle)],
                            level=85,known=True,eligible=True)
                cards.append(card)
        cards[7]['level']=None
        cards[7]['known']=cards[7]['eligible']=False
        self.state['cards']=cards
        before=driver._begin(16)
        old_clicks=len(self.clicks)
        tail=deepcopy(cards[:7])
        for card in tail:
            card.update(row=2,center=(card['center'][0],477),enhancement=14)
        self.state['cards']=deepcopy(self.state['cards'][7:])+tail
        for i,card in enumerate(self.state['cards']):
            card['row']=i//7
            card['center']=(190+card['column']*99,211+card['row']*133)
        after=driver.observe()
        self.assertEqual(after['cards'][0]['level'],85)
        self.assertEqual(len(self.clicks),old_clicks)
        traversal=InventoryTraversal()
        traversal.start(before)
        self.assertEqual(traversal.advance(before,after),1)

    def test_other_card_changes_invalidate_propagation(self):
        driver=self.driver()
        driver._begin(16)
        self.state['cards'][0]['enhancement']=6
        after=driver.observe()
        self.assertEqual(len(self.clicks),4)
        self.assertEqual(after['cards'][0]['enhancement'],6)
        self.assertEqual(self.details,[0,0])

    def test_detail_probe_cannot_add_seventeenth_card(self):
        driver=self.driver()
        driver._owns_selection=True
        self.state['selected_count']=16
        report=driver.observe()
        self.assertEqual(self.clicks,[])
        self.assertIsNone(report['cards'][0]['level'])

    def test_probe_grade_can_become_visible_but_complete_conflict_still_rejected(self):
        driver=self.driver()
        before=deepcopy(self.state)
        after=deepcopy(before)
        after['selected_count']=1
        after['cards'][0].update(selected=True,level=85,known=True,eligible=True)
        InventoryLevelRecovery.verify_probe_click(driver,before,after,(0,0),True)
        self.assertIsNone(before['cards'][0]['level'])
        before['cards'][0]['level']=88
        with self.assertRaises(ValueError):
            InventoryLevelRecovery.verify_probe_click(driver,before,after,(0,0),True)

    def test_selected_badge_loss_uses_independent_detail_and_tracks_original_order(self):
        driver=self.driver()
        original_read=driver.navigator.read
        def dimmed():
            report=original_read()
            if report['cards'][0]['selected']:
                report['cards'][0]['enhancement']=None
            return report
        driver.navigator.read=dimmed
        initial=driver._begin(16)
        driver.navigator.adb.tap(190,211)
        selected=driver._observe_click(initial,(0,0))
        self.assertEqual(selected['cards'][0]['enhancement'],3)
        self.assertEqual(len(self.clicks),3)
        self.assertEqual(self.details,[0])
        self.assertTrue(driver.observe_unchanged(selected)['cards'][0]['selected'])

    def test_complete_stage_conflict_never_uses_missing_badge_exception(self):
        driver=self.driver()
        before=deepcopy(self.state)
        after=deepcopy(before)
        after['selected_count']=1
        after['cards'][0].update(selected=True,enhancement=6)
        with self.assertRaises(ValueError):
            InventoryLevelRecovery.verify_probe_click(driver,before,after,(0,0),True)


class EntryDetailEvidenceTests(unittest.TestCase):
    def fixture(self):
        from dataclasses import asdict
        item=Equipment('test','red',85,3,'helmet',
                       {'speed':4,'atk_pct':8,'crit':5,'cdmg':7},True,True,35)
        main=('生命值','540')
        entry={'equipment':asdict(item),'main':main,'source':'detail.png',
               'fingerprint':detail_fingerprint(item,main)}
        return entry,item,{'stat':'hp_flat','value':540}

    def test_complete_matching_detail_can_support_hidden_entry_grade(self):
        entry,item,main=self.fixture()
        verify_detail_entry_level(entry,item,main,True)

    def test_only_grade_or_partial_detail_never_suffices(self):
        entry,item,main=self.fixture()
        for key in ('fingerprint','source','equipment','main'):
            broken=deepcopy(entry)
            del broken[key]
            with self.subTest(key=key),self.assertRaises(ValueError):
                verify_detail_entry_level(broken,item,main,True)

    def test_full_attributes_main_selection_and_fingerprint_must_match(self):
        entry,item,main=self.fixture()
        for changes in ({'stats':{'speed':8}}, {'enhancement':6}, {'game_score':36},
                        {'slot':'armor'}, {'rarity':'purple'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                verify_detail_entry_level(entry,replace(item,**changes),main,True)
        for bad_main,selected in ((None,True),({'stat':'hp_pct','value':540},True),(main,False)):
            with self.assertRaises(ValueError):
                verify_detail_entry_level(entry,item,bad_main,selected)
        entry['equipment']['level']=88
        with self.assertRaises(ValueError):
            verify_detail_entry_level(entry,item,main,True)


class DetailProbeGuardTests(unittest.TestCase):
    def test_only_registered_card_point_can_be_clicked_once(self):
        adb=DetailProbeAdb(serial='test')
        for kind in ('inventory_detail_probe_intent','inventory_detail_probe_restore_intent'):
            adb.event({'kind':kind,'x':200,'y':250})
            with patch.object(adb,'_run') as run:
                adb.tap(200,250)
                with self.assertRaises(ValueError):
                    adb.tap(200,250)
                run.assert_called_once()

    def test_resource_lock_and_mismatching_points_are_forbidden(self):
        for kind,point in (('batch_enhance_commit_intent',(1200,670)),
                            ('inventory_detail_probe_intent',(1190,183)),
                            ('inventory_detail_probe_intent',(201,250)),
                            ('batch_selection_intent',(200,250))):
            adb=DetailProbeAdb(serial='test')
            adb.event({'kind':kind,'x':200,'y':250})
            with self.subTest(kind=kind,point=point),patch.object(adb,'_run') as run:
                with self.assertRaises(ValueError):
                    adb.tap(*point)
                run.assert_not_called()


class NativeUnknownGradeTests(unittest.TestCase):
    def test_unknown_grade_requires_explicit_independent_detail_path(self):
        candidate={'rarity':'red','level':None,'enhancement':3}
        values={'level':'85','score':'35','main':'540','enhancement':'+3',
                'stat0':'4','stat1':'28','stat2':'4%','stat3':'5%'}
        observed=replace(screen(),words=screen().words+(
            {'text':'+3','center':(950,178),'confidence':1.},))
        with self.assertRaises(ValueError):
            read_detail(observed,candidate,lambda *args:values)
        detail=read_detail(observed,candidate,lambda *args:values,allow_unknown_level=True)
        self.assertEqual(detail['equipment'].level,85)
        for level in ('5','88','90',''):
            with self.subTest(level=level),self.assertRaises(ValueError):
                read_detail(observed,candidate,lambda *args:{**values,'level':level},allow_unknown_level=True)


if __name__=='__main__':
    unittest.main()
