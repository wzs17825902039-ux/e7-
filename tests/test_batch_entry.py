from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest

from e7_assistant.batch_entry import verify_entry, BatchEntryDriver
from e7_assistant.rules import Equipment
from e7_assistant.tasks import TaskControl


def fixtures(count=2):
    registered, records = [], []
    for index in range(count):
        item = asdict(Equipment(f'selection:{index}', 'purple', 85, 0, 'helmet',
                                {'speed':3,'crit':5,'atk_pct':7}, True, True, 25))
        registered.append({'equipment':item, 'main':('生命值','540')})
        records.append({'index':index,'equipment':deepcopy(item),'selected':True,'locked':None,
                        'main':{'stat':'hp_flat','value':540}})
    return ({'selected_count':count,'registered':registered,'scan_complete':True},
            {'page':'batch_enhancement','records':records,'issues':[],
             'slots':[{'index':i,'state':'occupied' if i<count else 'empty'} for i in range(16)]})


class BatchEntryTests(unittest.TestCase):
    def test_custom_set_registration_is_shared_by_manual_and_full_workflow_entry(self):
        from e7_assistant.rules import Policy
        for enabled in (False,True):
            with self.subTest(enabled=enabled):
                selection,report=fixtures(1)
                for record in (selection['registered'][0],report['records'][0]):
                    record['equipment'].update(rarity='red',stats={'atk_pct':8,'crit':3,'effectiveness':8,'resistance':8})
                report['source']='batch.png'
                selector=SimpleNamespace(navigator=SimpleNamespace(journal=Mock()),policy=Policy(
                    custom_targets_enabled=enabled,custom_targets=[{'name':'输出','sets':['speed'],'stats':['atk_pct','crit']}]))
                driver=BatchEntryDriver(selector,batch_reader=Mock(return_value=report))
                with patch('e7_assistant.set_vision.inspect_batch_sets',return_value={0:{'set':'speed'}}) as read:
                    result,items=driver.read_entry(selection,SimpleNamespace(page='batch_enhancement',source='batch.png'))
                self.assertEqual(items[0].equipment.gear_set,'speed' if enabled else None)
                self.assertEqual(read.call_count,int(enabled))

    def test_entry_ocr_retry_recovers_without_repeating_entry_click(self):
        driver,selection=self.make_driver(iter(['batch_enhancement']*3))
        good=driver.batch_reader('batch.png',{})
        bad=deepcopy(good);bad['issues']=['卡片1：数字拒识']
        driver.batch_reader=Mock(side_effect=[bad,good])
        _,items=driver.enter(selection)
        self.assertEqual(len(items),16)
        self.assertEqual(driver.batch_reader.call_count,2)
        self.assertEqual(len(self.clicks),1)

    def test_entry_ocr_retry_is_bounded_and_never_confirms(self):
        driver,selection=self.make_driver(iter(['batch_enhancement']*4))
        bad=driver.batch_reader('batch.png',{});bad['issues']=['卡片1：拒识']
        driver.batch_reader=Mock(return_value=bad)
        with self.assertRaisesRegex(ValueError,'3次'):
            driver.enter(selection)
        self.assertEqual(driver.batch_reader.call_count,3)
        self.assertEqual(len(self.clicks),1)

    def test_entry_identity_mismatch_is_not_a_retryable_ocr_failure(self):
        driver,selection=self.make_driver(iter(['batch_enhancement']*3))
        wrong=driver.batch_reader('batch.png',{})
        wrong['records'][0]['equipment']['stats']['speed']=10
        driver.batch_reader=Mock(return_value=wrong)
        with self.assertRaisesRegex(ValueError,'背包登记不符'):
            driver.enter(selection)
        self.assertEqual(driver.batch_reader.call_count,1)

    def test_entry_retry_stops_on_unexpected_page(self):
        driver,selection=self.make_driver(iter(['batch_enhancement','sale_confirmation']))
        bad=driver.batch_reader('batch.png',{});bad['issues']=['卡片1：拒识']
        driver.batch_reader=Mock(return_value=bad)
        with self.assertRaisesRegex(ValueError,'页面已改变'):
            driver.enter(selection)
        self.assertEqual(driver.batch_reader.call_count,1)
        self.assertEqual(len(self.clicks),1)

    def test_entry_retry_recovers_reader_error_and_unknown_frame(self):
        driver,selection=self.make_driver(iter(['batch_enhancement','unknown','batch_enhancement']))
        good=driver.batch_reader('batch.png',{})
        driver.batch_reader=Mock(side_effect=[ValueError('动画尚未稳定'),good])
        _,items=driver.enter(selection)
        self.assertEqual(len(items),16)
        self.assertEqual(driver.batch_reader.call_count,2)
        self.assertEqual(len(self.clicks),1)

    def test_mixed_unfinished_stages_keep_their_actual_levels(self):
        selection, report = fixtures(4)
        for index,stage in enumerate((0,3,9,14)):
            selection['registered'][index]['equipment']['enhancement']=stage
            report['records'][index]['equipment']['enhancement']=stage
        self.assertEqual([item.equipment.enhancement for item in verify_entry(selection,report)],
                         [0,3,9,14])
        selection['registered'][3]['equipment']['enhancement']=15
        report['records'][3]['equipment']['enhancement']=15
        with self.assertRaises(ValueError):
            verify_entry(selection,report)

    def test_complete_and_tail_batches_preserve_registered_identity(self):
        for count in (1,2,16):
            selection, report = fixtures(count)
            for record in report['records']:
                record['equipment']['equipment_id'] = 'different-pixel-hash'
            items = verify_entry(selection,report)
            self.assertEqual([i.equipment.equipment_id for i in items],[f'selection:{i}' for i in range(count)])
            self.assertTrue(all(i.locked is None for i in items))

    def test_unknown_empty_slot_is_not_ignored(self):
        selection,report = fixtures()
        report['slots'][-1]['state'] = 'unknown'
        with self.assertRaises(ValueError):
            verify_entry(selection,report)

    def test_extra_occupied_slot_is_rejected(self):
        selection,report = fixtures()
        report['slots'][2]['state'] = 'occupied'
        with self.assertRaises(ValueError):
            verify_entry(selection,report)

    def test_any_attribute_change_or_wrong_part_is_rejected(self):
        for key,value in [('slot','ring'),('stats',{'speed':4}),('enhancement',3),('game_score',99)]:
            selection,report = fixtures()
            report['records'][0]['equipment'][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                verify_entry(selection,report)

    def test_unconfirmed_or_wrong_main_stat_is_rejected(self):
        for main in (None,{'stat':'hp_pct','value':540},{'stat':'hp_flat','value':541}):
            selection,report = fixtures()
            report['records'][0]['main'] = main
            with self.assertRaises(ValueError):
                verify_entry(selection,report)

    def test_wrong_order_or_missing_registration_is_rejected(self):
        selection,report = fixtures()
        report['records'].reverse()
        with self.assertRaises(ValueError):
            verify_entry(selection,report)
        selection['registered'].pop()
        with self.assertRaises(ValueError):
            verify_entry(selection,report)

    def test_incomplete_tail_does_not_click_entry(self):
        selection,_ = fixtures(1)
        selection['scan_complete'] = False
        selector = SimpleNamespace(navigator=SimpleNamespace())
        with self.assertRaisesRegex(ValueError,'扫描末尾'):
            BatchEntryDriver(selector).enter(selection)

    def test_bottom_only_is_not_complete_inventory_scan(self):
        selection,_ = fixtures(5)
        selection['scan_complete'] = False
        selection['scan_evidence'] = {'end_verified':True,'top_verified':False}
        selector = SimpleNamespace(navigator=SimpleNamespace())
        with self.assertRaisesRegex(ValueError,'从顶部'):
            BatchEntryDriver(selector).enter(selection)

    def test_deselected_or_unreadable_card_is_rejected(self):
        selection,report = fixtures()
        report['records'][0]['selected'] = False
        with self.assertRaises(ValueError):
            verify_entry(selection,report)
        report['records'][0]['selected'] = True
        report['issues'] = ['卡片1：拒识']
        with self.assertRaises(ValueError):
            verify_entry(selection,report)

    def make_driver(self, pages):
        selection, report = fixtures(16)
        fresh = {'selected_count':16,'scan_complete':True}
        self.clicks = []
        control = TaskControl()
        control.wait = lambda seconds: control.checkpoint()
        navigator = SimpleNamespace(control=control, journal=None,
                                    adb=SimpleNamespace(tap=lambda *point:self.clicks.append(point)),
                                    read=lambda: SimpleNamespace(page=next(pages),source='batch.png'))
        screen = SimpleNamespace(find=lambda *args: {'center':(1114,674)})
        selector = SimpleNamespace(navigator=navigator, observe=lambda:fresh, screen=screen,
                                   _verify_unchanged=lambda a,b:self.assertEqual(a,b))
        return BatchEntryDriver(selector, batch_reader=lambda path,slots:report), selection

    def test_actual_entry_path_clicks_once_and_verifies_result(self):
        driver,selection = self.make_driver(iter(['unknown','batch_enhancement']))
        report,items = driver.enter(selection)
        self.assertEqual(len(items),16)
        self.assertEqual(self.clicks,[(1114,674)])

    def test_verified_entry_hands_locked_grade_anchors_to_exactly_one_batch_driver(self):
        from e7_assistant.batch_enhancement import BatchEnhancementDriver
        driver,selection=self.make_driver(iter(['batch_enhancement']))
        original_reader=driver.batch_reader
        def locked_reader(path,slots):
            report=original_reader(path,slots)
            report['records'][0]['locked']=True
            return report
        driver.batch_reader=locked_reader
        report,items=driver.enter(selection)
        self.assertTrue(items[0].locked)
        self.assertEqual(report['verified_level_anchors'],{0:'batch.png'})
        enhancement=BatchEnhancementDriver(driver.navigator)
        self.assertEqual(enhancement.verified_level_anchors,{0:'batch.png'})
        second=BatchEnhancementDriver(driver.navigator)
        self.assertEqual(second.verified_level_anchors,{})

    def test_scan_metadata_does_not_replace_fresh_visual_snapshot(self):
        driver,selection = self.make_driver(iter(['batch_enhancement']))
        selection.update(visual_snapshot={'selected_count':16,'scan_complete':True},
                         scanned_pages=2,scan_evidence={'end_verified':False})
        report,items = driver.enter(selection)
        self.assertEqual(len(items),16)
        self.assertEqual(len(self.clicks),1)

    def test_entry_timeout_and_popup_never_repeat_click(self):
        for pages in (['unknown']*8,['sale_confirmation']):
            driver,selection = self.make_driver(iter(pages))
            with self.assertRaises((ValueError,TimeoutError)):
                driver.enter(selection)
            self.assertEqual(len(self.clicks),1)
