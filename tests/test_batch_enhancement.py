from dataclasses import replace
from types import SimpleNamespace
import unittest

from e7_assistant.batch_enhancement import BatchEnhancementDriver,BatchObservationError
from e7_assistant.tasks import Ledger,Limits,TaskControl
from test_batch_resources import resources,items


class BatchEnhancementTests(unittest.TestCase):
    def test_second_frame_ocr_failure_retries_result_without_resending_confirmation(self):
        from unittest.mock import Mock
        before,_,_=resources()
        initial=items()
        enhanced=[replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3))]
        driver=self.driver([(self.screen('clear1'),enhanced,before),
                            (self.screen('clear2'),enhanced,before)])
        driver.stable_result=Mock(side_effect=[BatchObservationError('第二帧遮挡'),
            (self.screen('stable'),enhanced,before)])
        preview=SimpleNamespace(image='submitted',items=initial,target=3)
        driver.committed.add(preview.image)
        self.assertEqual(driver.finish_enhancement(preview)['items'],enhanced)
        self.assertEqual(driver.stable_result.call_count,2)
        self.assertEqual(self.clicks,[])

    def test_unselected_stat_overlay_is_retryable_and_not_cached(self):
        from copy import deepcopy
        from test_batch_entry import fixtures
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        _,report=fixtures(1)
        report=deepcopy(report)
        record=report['records'][0]
        record['selected']=False
        expected=[BatchItem('0',Equipment(**deepcopy(record['equipment'])),False,record['locked'])]
        key=next(iter(record['equipment']['stats']))
        record['equipment']['stats'][key]+=20
        nav=SimpleNamespace(journal=None,read=lambda:SimpleNamespace(page='batch_enhancement',source='overlay.png'))
        driver=BatchEnhancementDriver(nav,batch_reader=lambda path,slots:report,
                                      resource_reader=lambda screen:resources()[0])
        with self.assertRaisesRegex(BatchObservationError,'未选中装备'):
            driver.observe(expected)
        self.assertIsNone(driver.last_image)
        self.assertIsNone(driver.verified_items)

    def test_result_overlay_retries_without_repeating_input(self):
        before,_,_=resources()
        initial=items()
        enhanced=[replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3))]
        driver=self.driver([BatchObservationError('未选中装备读数发生变化'),
                            (self.screen('clear'),enhanced,before),
                            (self.screen('stable'),enhanced,before)])
        preview=SimpleNamespace(image='submitted',items=initial,target=3)
        driver.committed.add(preview.image)
        self.assertEqual(driver.finish_enhancement(preview)['items'],enhanced)
        self.assertEqual(self.clicks,[])


    def test_refund_that_disappears_to_an_unrelated_page_is_not_swallowed(self):
        from unittest.mock import Mock
        from e7_assistant.workflow_navigation import NavigationPageChanged
        changed=SimpleNamespace(page='inventory',source='unexpected.png')
        nav=SimpleNamespace(journal=None,read=lambda:SimpleNamespace(page='enhancement_refund'),
            transition=Mock(side_effect=NavigationPageChanged('dismiss_enhancement_refund',changed)))
        read=Mock()
        driver=BatchEnhancementDriver(nav,batch_reader=read)
        with self.assertRaises(NavigationPageChanged):driver.observe(items())
        read.assert_not_called()

    def test_refund_that_disappears_before_dismiss_is_read_without_another_input(self):
        from unittest.mock import Mock
        from test_batch_entry import fixtures
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        from e7_assistant.workflow_navigation import NavigationPageChanged
        _,report=fixtures(1)
        record=report['records'][0]
        expected=[BatchItem('0',Equipment(**record['equipment']),record['selected'],record['locked'])]
        ready=SimpleNamespace(page='batch_enhancement',source='already-dismissed.png')
        nav=SimpleNamespace(journal=None,read=lambda:SimpleNamespace(page='enhancement_refund'),
            transition=Mock(side_effect=NavigationPageChanged('dismiss_enhancement_refund',ready)))
        before,_,_=resources()
        driver=BatchEnhancementDriver(nav,batch_reader=lambda path,slots:report,
                                      resource_reader=lambda screen:before)
        actual,observed,_=driver.observe(expected)
        self.assertIs(actual,ready)
        self.assertEqual(observed,expected)
        nav.transition.assert_called_once_with('dismiss_enhancement_refund')

    def test_live_animation_preview_skips_attribute_ocr_before_result_read(self):
        from pathlib import Path
        from unittest.mock import Mock
        from e7_assistant.batch_resources import inspect_untracked_resources
        from e7_assistant.batch_vision import inspect_batch
        root=Path(__file__).resolve().parents[1]/'runs/workflow-9b5b58155e7a'
        animation=SimpleNamespace(page='batch_enhancement',source=str(root/'workflow-0288.png'))
        result=SimpleNamespace(page='batch_enhancement',source=str(root/'workflow-0289.png'))
        self.assertTrue(inspect_untracked_resources(animation).has_preview)
        self.assertFalse(inspect_untracked_resources(result).has_preview)
        initial=items()
        enhanced=[replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3))]
        nav=SimpleNamespace(journal=None,control=TaskControl(),read_batch=Mock(side_effect=[animation,result]))
        driver=BatchEnhancementDriver(nav,batch_reader=inspect_batch,track_resources=False)
        driver.observe=Mock(return_value=(result,enhanced,inspect_untracked_resources(result)))
        driver.stable_result=Mock(return_value=driver.observe.return_value)
        preview=SimpleNamespace(image='submitted',items=initial,target=3)
        driver.committed.add(preview.image)
        self.assertEqual(driver.finish_enhancement(preview)['items'],enhanced)
        self.assertEqual(nav.read_batch.call_count,2)
        driver.observe.assert_called_once_with(initial,screen=result)

    def test_second_frame_ocr_uses_one_attempt_per_outer_result_cycle(self):
        from unittest.mock import Mock
        driver=self.driver([])
        driver.observe=Mock(side_effect=BatchObservationError('第二帧拒识'))
        driver.observe_selection_result=Mock(side_effect=AssertionError('不得嵌套重试'))
        with self.assertRaises(BatchObservationError):
            driver.stable_result(self.screen('first'),items(),resources()[0],SimpleNamespace(items=items()))
        driver.observe.assert_called_once_with(items())
        driver.observe_selection_result.assert_not_called()

    def test_persistent_second_frame_refusal_is_bounded_by_outer_eight_cycles(self):
        from unittest.mock import Mock
        initial=items()
        enhanced=[replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3))]
        first=(self.screen('first'),enhanced,resources()[0])
        driver=self.driver([])
        driver.observe=Mock(side_effect=[value for _ in range(8)
                                        for value in (first,BatchObservationError('第二帧拒识'))])
        preview=SimpleNamespace(image='submitted',items=initial,target=3)
        driver.committed.add(preview.image)
        with self.assertRaises(TimeoutError):driver.finish_enhancement(preview)
        self.assertEqual(driver.observe.call_count,16)
        self.assertEqual(self.clicks,[])

    def test_failed_pixel_comparison_reuses_captured_second_frame_for_ocr(self):
        from unittest.mock import Mock,patch
        from e7_assistant.batch_vision import inspect_batch
        first=self.screen('first');second=self.screen('second');second.page='batch_enhancement'
        nav=SimpleNamespace(read_batch=Mock(return_value=second),read_navigation=Mock())
        driver=BatchEnhancementDriver(nav,batch_reader=inspect_batch,track_resources=False)
        expected=items();observed=(second,expected,resources()[0])
        driver.observe=Mock(return_value=observed)
        with patch('e7_assistant.batch_vision.verify_stable_batch_pixels',side_effect=ValueError('光效变化')):
            self.assertEqual(driver.stable_result(first,expected,resources()[0],SimpleNamespace(items=expected)),observed)
        nav.read_batch.assert_called_once_with()
        driver.observe.assert_called_once_with(expected,screen=second)

    def test_animation_wait_is_bounded_and_never_repeats_confirmation(self):
        from pathlib import Path
        from unittest.mock import Mock
        from e7_assistant.batch_vision import inspect_batch
        source=Path(__file__).resolve().parents[1]/'runs/workflow-9b5b58155e7a/workflow-0288.png'
        screen=SimpleNamespace(page='batch_enhancement',source=str(source))
        nav=SimpleNamespace(journal=None,control=SimpleNamespace(wait=Mock()),
                            read_batch=Mock(return_value=screen),adb=Mock())
        driver=BatchEnhancementDriver(nav,batch_reader=inspect_batch,track_resources=False)
        driver.observe=Mock(side_effect=AssertionError('Animation must not run attribute OCR'))
        preview=SimpleNamespace(image='submitted',items=items(),target=3)
        driver.committed.add(preview.image)
        with self.assertRaisesRegex(TimeoutError,'禁止重试确认'):
            driver.finish_enhancement(preview)
        self.assertEqual(nav.read_batch.call_count,8)
        driver.observe.assert_not_called()
        nav.adb.tap.assert_not_called()

    def test_unknown_lock_is_retryable_observation_not_a_confirmed_lock_change(self):
        from copy import deepcopy
        from test_batch_entry import fixtures
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        _,report=fixtures(1)
        old=report['records'][0]
        expected=[BatchItem('0',Equipment(**old['equipment']),True,False)]
        report=deepcopy(report);report['records'][0]['locked']=None
        nav=SimpleNamespace(journal=None,read=lambda:SimpleNamespace(page='batch_enhancement',source='fresh.png'))
        driver=BatchEnhancementDriver(nav,batch_reader=lambda path,slots:report,
                                      resource_reader=lambda screen:resources()[0])
        with self.assertRaises(BatchObservationError):driver.observe(expected)

    def test_existing_untracked_preview_is_reused_only_for_same_target(self):
        from e7_assistant.batch_resources import UntrackedBatchResources
        initial=items()
        ready=UntrackedBatchResources(3,'ready')
        driver=self.driver([(self.screen('ready'),initial,ready)])
        driver.resource_untracked=True
        preview=driver.prepare_enhancement(initial,3)
        self.assertEqual(preview.target,3)
        self.assertEqual(self.clicks,[])
        driver=self.driver([(self.screen('wrong'),initial,ready)])
        driver.resource_untracked=True
        with self.assertRaises(ValueError):driver.prepare_enhancement(initial,6)
        self.assertEqual(self.clicks,[])

    def test_unregistered_stage_tap_can_retry_but_never_overwrites_other_preview(self):
        from e7_assistant.batch_resources import UntrackedBatchResources
        initial=items();empty=UntrackedBatchResources(None,'empty')
        ready=UntrackedBatchResources(3,'ready')
        driver=self.driver([(self.screen('before'),initial,empty),(self.screen('ignored'),initial,empty),
                            (self.screen('ready'),initial,ready)])
        driver.resource_untracked=True
        self.assertEqual(driver.prepare_enhancement(initial,3).target,3)
        self.assertEqual(self.clicks,[(300,670),(300,670)])
        wrong=UntrackedBatchResources(6,'wrong')
        driver=self.driver([(self.screen('before'),initial,empty),(self.screen('wrong'),initial,wrong)])
        driver.resource_untracked=True
        with self.assertRaises(ValueError):driver.prepare_enhancement(initial,3)
        self.assertEqual(self.clicks,[(300,670)])

    def test_second_result_read_can_retry_without_repeating_confirmation(self):
        before,prepared,after=resources();initial=items()
        enhanced=[replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3))]
        driver=self.driver([(self.screen('before'),initial,before),(self.screen('prepared'),initial,prepared),
                            (self.screen('commit'),initial,prepared),(self.screen('result'),enhanced,after),
                            BatchObservationError('第二帧徽标光效'),(self.screen('reread'),enhanced,after),
                            (self.screen('stable'),enhanced,after)])
        preview=driver.prepare_enhancement(initial,3)
        driver.commit_enhancement(preview)
        self.assertEqual(driver.finish_enhancement(preview)['items'],enhanced)
        self.assertEqual(self.clicks,[(300,670),(1200,670)])

    def test_preview_retries_only_reads_without_repeating_stage_or_commit(self):
        before,prepared,_=resources();initial=items()
        driver=self.driver([(self.screen('before'),initial,before),BatchObservationError('光效'),
                            (self.screen('prepared'),initial,prepared),BatchObservationError('光效'),
                            (self.screen('commit'),initial,prepared)])
        preview=driver.prepare_enhancement(initial,3)
        self.assertEqual(self.clicks,[(300,670)])
        driver.commit_enhancement(preview)
        self.assertEqual(self.clicks,[(300,670),(1200,670)])

    def test_unchanged_observation_retry_is_bounded_and_never_hides_identity_change(self):
        initial=items()
        driver=self.driver([BatchObservationError('拒识')]*3)
        with self.assertRaises(BatchObservationError):driver.observe_unchanged(initial)
        self.assertEqual(self.clicks,[])
        driver=self.driver([ValueError('品质变化')])
        with self.assertRaisesRegex(ValueError,'品质变化'):driver.observe_unchanged(initial)
        self.assertEqual(self.clicks,[])

    def test_result_retry_passes_partial_successes_only_to_readonly_reader(self):
        from copy import deepcopy
        from unittest.mock import Mock,patch
        from test_batch_entry import fixtures
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        _,good=fixtures(1)
        old=good['records'][0]
        expected=[BatchItem('0',Equipment(**old['equipment']),True,None)]
        partial=deepcopy(good);partial['issues']=['卡片1：拒识'];partial['records']=[]
        reader=Mock(side_effect=[partial,good])
        nav=SimpleNamespace(journal=None,read=lambda:SimpleNamespace(page='batch_enhancement',source='fresh.png'))
        before,_,_=resources()
        with patch('e7_assistant.batch_enhancement.inspect_batch',reader):
            driver=BatchEnhancementDriver(nav,batch_reader=reader,resource_reader=lambda screen:before)
            with self.assertRaises(BatchObservationError):driver.observe(expected)
            driver.observe(expected)
        self.assertIs(reader.call_args_list[1].kwargs['retry_report'],partial)
        self.assertIsNone(driver.partial_observation)

    def test_selection_result_retries_only_observation_errors(self):
        before,_,_=resources();initial=items()
        observed=(self.screen('fresh'),initial,before)
        driver=self.driver([BatchObservationError('动画拒识'),observed])
        self.assertEqual(driver.observe_selection_result(initial),observed)
        self.assertEqual(self.clicks,[])
        driver=self.driver([BatchObservationError('拒识')]*3)
        with self.assertRaises(BatchObservationError):driver.observe_selection_result(initial)
        self.assertEqual(self.clicks,[])
        driver=self.driver([ValueError('身份变化')])
        with self.assertRaisesRegex(ValueError,'身份变化'):driver.observe_selection_result(initial)
        self.assertEqual(self.clicks,[])

    def test_mixed_selected_levels_cannot_preview_a_lower_target(self):
        before,_,_=resources()
        initial=items()
        initial.append(replace(initial[0],token='higher',
                               equipment=replace(initial[0].equipment,equipment_id='higher',enhancement=9)))
        driver=self.driver([(self.screen('before'),initial,before)])
        with self.assertRaisesRegex(ValueError,'每件'):
            driver.prepare_enhancement(initial,3)
        self.assertEqual(self.clicks,[])

    def driver(self,observations):
        self.clicks = []
        control = TaskControl()
        control.wait = lambda seconds:control.checkpoint()
        navigator = SimpleNamespace(control=control,journal=None,
                                    adb=SimpleNamespace(tap=lambda *point:self.clicks.append(point)))
        driver = BatchEnhancementDriver(navigator)
        queue = iter(observations)
        def observe(expected):
            result = next(queue)
            if isinstance(result,Exception):
                raise result
            return result
        driver.observe = observe
        driver.observe_selection_flags=lambda expected,reference:self.screen('selection-verified')
        return driver

    def screen(self,name):
        return SimpleNamespace(source=name,find=lambda label,region:{'center':(300,670) if label!='强化' else (1200,670)})

    def test_prepare_commit_once_and_actual_ledger_settlement(self):
        before,prepared,after = resources()
        initial = items()
        enhanced = [replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3,stats={**initial[0].equipment.stats,'speed':7}))]
        driver = self.driver([(self.screen('before'),initial,before),(self.screen('prepared'),initial,prepared),
                              (self.screen('fresh'),initial,prepared),(self.screen('after'),enhanced,after),
                              (self.screen('stable'),enhanced,after)])
        preview = driver.prepare_enhancement(initial,3)
        ledger = Ledger(Limits(gold=5000,powder=10))
        ledger.check(preview.cost,preview.resources)
        driver.commit_enhancement(preview)
        result = driver.finish_enhancement(preview)
        ledger.settle(preview.resources,result['resources'],preview.cost)
        self.assertEqual(ledger.spent['gold'],3200)
        self.assertEqual(ledger.spent['powder'],2)
        self.assertEqual(self.clicks,[(300,670),(1200,670)])
        with self.assertRaises(ValueError):
            driver.commit_enhancement(preview)

    def test_budget_failure_occurs_before_confirm(self):
        before,prepared,_ = resources()
        initial = items()
        driver = self.driver([(self.screen('before'),initial,before),(self.screen('prepared'),initial,prepared)])
        preview = driver.prepare_enhancement(initial,3)
        with self.assertRaises(ValueError):
            Ledger(Limits(gold=100,powder=10)).check(preview.cost,preview.resources)
        self.assertEqual(self.clicks,[(300,670)])

    def test_changed_preparation_prevents_confirmation(self):
        before,prepared,_ = resources()
        initial = items()
        changed = replace(prepared,gold_cost=3201)
        driver = self.driver([(self.screen('before'),initial,before),(self.screen('prepared'),initial,prepared),
                              (self.screen('changed'),initial,changed)])
        preview = driver.prepare_enhancement(initial,3)
        with self.assertRaises(ValueError):
            driver.commit_enhancement(preview)
        self.assertEqual(len(self.clicks),1)

    def test_result_timeout_does_not_repeat_confirmation(self):
        before,prepared,_ = resources()
        initial = items()
        driver = self.driver([(self.screen('before'),initial,before),(self.screen('prepared'),initial,prepared),
                              (self.screen('fresh'),initial,prepared)]+[(self.screen('pending'),initial,prepared)]*8)
        preview = driver.prepare_enhancement(initial,3)
        driver.commit_enhancement(preview)
        with self.assertRaises(TimeoutError):
            driver.finish_enhancement(preview)
        self.assertEqual(len(self.clicks),2)

    def test_deselect_validates_only_target_changed(self):
        before,_,_ = resources()
        initial = items()
        deselected = [replace(initial[0],selected=False)]
        driver = self.driver([(self.screen('before'),initial,before),(self.screen('after'),deselected,before)])
        result = driver.select_active(initial,set())
        self.assertFalse(result[0].selected)
        self.assertEqual(len(self.clicks),1)

    def test_multiple_toggles_use_two_full_reads_and_verify_every_selection(self):
        before,_,_=resources()
        initial=items()
        initial.extend(replace(initial[0],token=str(i),equipment=replace(initial[0].equipment,
                       equipment_id=str(i))) for i in range(1,4))
        expected=[replace(i,selected=False) for i in initial]
        driver=self.driver([(self.screen('before'),initial,before),(self.screen('after'),expected,before)])
        checked=[]
        driver.observe_selection_flags=lambda current,reference:checked.append([i.selected for i in current]) or self.screen('flags')
        self.assertEqual(driver.select_active(initial,set()),expected)
        self.assertEqual(len(self.clicks),4)
        self.assertEqual(checked,[[False,True,True,True],[False,False,True,True],
                                  [False,False,False,True],[False,False,False,False]])

    def test_selection_graph_failure_stops_before_next_tap(self):
        before,_,_=resources();initial=items()
        initial.append(replace(initial[0],token='1'))
        driver=self.driver([(self.screen('before'),initial,before)])
        def fail(expected,reference):raise BatchObservationError('边框未确认')
        driver.observe_selection_flags=fail
        with self.assertRaises(BatchObservationError):driver.select_active(initial,set())
        self.assertEqual(len(self.clicks),1)

    def test_selection_final_attribute_change_rejected(self):
        before,_,_=resources();initial=items()
        changed=[replace(initial[0],selected=False,equipment=replace(initial[0].equipment,stats={'speed':8}))]
        driver=self.driver([(self.screen('before'),initial,before),(self.screen('after'),changed,before)])
        with self.assertRaisesRegex(ValueError,'属性'):driver.select_active(initial,set())

    def test_animation_frame_only_retries_reading(self):
        before,prepared,after = resources()
        initial = items()
        enhanced = [replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3))]
        driver = self.driver([(self.screen('before'),initial,before),(self.screen('prepared'),initial,prepared),
                              (self.screen('fresh'),initial,prepared),BatchObservationError('动画'),
                              (self.screen('after'),enhanced,after),(self.screen('stable'),enhanced,after)])
        preview = driver.prepare_enhancement(initial,3)
        driver.commit_enhancement(preview)
        self.assertEqual(driver.finish_enhancement(preview)['items'][0].equipment.enhancement,3)
        self.assertEqual(len(self.clicks),2)

    def test_observer_preserves_registered_ids_and_rejects_missing_fields(self):
        from test_batch_entry import fixtures
        from e7_assistant.batch_entry import verify_entry
        selection,report = fixtures(2)
        expected = verify_entry(selection,report)
        for record in report['records']:
            record['equipment']['equipment_id'] = 'different-pixel-hash'
        before,_,_ = resources()
        navigator = SimpleNamespace(read=lambda:SimpleNamespace(page='batch_enhancement',source='frame.png'))
        driver = BatchEnhancementDriver(navigator,batch_reader=lambda path,slots:report,
                                        resource_reader=lambda screen:before)
        _,observed,_ = driver.observe(expected)
        self.assertEqual([i.equipment.equipment_id for i in observed],['selection:0','selection:1'])
        report['issues'] = ['卡片字段不完整']
        with self.assertRaises(BatchObservationError):
            driver.observe(expected)

    def test_mismatched_actual_cost_is_recorded_by_shared_ledger(self):
        before,prepared,after = resources()
        after = replace(after,available={**after.available,'gold':6799})
        initial = items()
        enhanced = [replace(initial[0],equipment=replace(initial[0].equipment,enhancement=3))]
        driver = self.driver([(self.screen('before'),initial,before),(self.screen('prepared'),initial,prepared),
                              (self.screen('fresh'),initial,prepared),(self.screen('after'),enhanced,after),
                              (self.screen('stable'),enhanced,after)])
        preview = driver.prepare_enhancement(initial,3)
        driver.commit_enhancement(preview)
        result = driver.finish_enhancement(preview)
        ledger = Ledger(Limits(gold=5000,powder=10))
        with self.assertRaises(ValueError):
            ledger.settle(preview.resources,result['resources'],preview.cost)
        self.assertEqual(ledger.spent['gold'],3201)
        self.assertEqual(ledger.steps,1)
