from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from tests import test_inventory_view_expansion as fixtures


def frames(dy=3):
    before,_=fixtures.snapshots()
    after=deepcopy(before)
    for card in after['cards'][7:]:
        x,y=card['center'];card['center']=(x,y+dy)
        x1,y1,x2,y2=card['tracking_box'];card['tracking_box']=(x1,y1+dy,x2,y2+dy)
    return before,after


class StationaryRowTests(unittest.TestCase):
    def test_actual_four_pixel_localization_shift_requires_seven_stationary_cards(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before,after=[inspect_inventory(inspect_screen(assets/name)) for name in
                      ('73-four-pixel-row-before.png','74-four-pixel-row-after.png')]
        self.assertEqual(BatchSelectionDriver._stationary_row_jitter(before,after),set(range(14,21)))
        BatchSelectionDriver._verify_unchanged({k:v for k,v in before.items() if k!='source'},
                                               {k:v for k,v in after.items() if k!='source'})

    def test_actual_row_jitter_with_missing_badge_only_authorizes_bounded_read_retry(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        from tests.test_inventory_observation_retry import ObservationRetryTests
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before,missing=[inspect_inventory(inspect_screen(assets/name)) for name in
                        ('52-jitter-missing-before.png','53-jitter-missing-after.png')]
        self.assertEqual(BatchSelectionDriver._stationary_row_jitter(before,missing),set(range(14,21)))
        # 下半部头盔尖角不再误作强化徽标；该实图现已可靠读为+0。
        self.assertEqual(missing['cards'][19]['enhancement'],0)
        # 仍保留缺字段时只读重试的故障注入，不能用识别改善删除此覆盖。
        missing['cards'][19].update(enhancement=None,known=False,eligible=False)
        self.assertTrue(BatchSelectionDriver._can_retry_missing(before,missing))
        harness=ObservationRetryTests()
        with self.assertRaises(ValueError):harness.driver([missing]).observe_unchanged(before)
        self.assertEqual((harness.reads,harness.inputs),(4,[]))
        result=harness.driver([missing,before]).observe_unchanged(before)
        self.assertEqual((harness.reads,harness.inputs),(2,[]))
        self.assertEqual(result,before)
        self.assertIsNone(missing['cards'][19]['enhancement'])

    def test_missing_fields_with_row_shift_require_absolute_stationarity_and_no_conflicts(self):
        for dy in (-3,-2,2,3):
            before,missing=frames(dy)
            missing['cards'][8].update(enhancement=None,known=False,eligible=False)
            with self.subTest(dy=dy),patch('e7_assistant.inventory_tracking.inspect_tracking',
                    return_value={'matched':True,'offset':(0,-dy)}):
                self.assertTrue(BatchSelectionDriver._can_retry_missing(before,missing))
                conflict=deepcopy(missing);conflict['cards'][9]['level']=90
                self.assertFalse(BatchSelectionDriver._can_retry_missing(before,conflict))
            with patch('e7_assistant.inventory_tracking.inspect_tracking',
                    return_value={'matched':True,'offset':(0,0)}):
                self.assertFalse(BatchSelectionDriver._can_retry_missing(before,missing))

    def test_actual_three_pixel_row_localization_error_requires_all_original_pixel_proofs(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before,after=[inspect_inventory(inspect_screen(assets/name)) for name in
                      ('44-row-jitter-before.png','45-row-jitter-after.png')]
        self.assertEqual(BatchSelectionDriver._stationary_row_jitter(before,after),set(range(14,21)))
        BatchSelectionDriver._verify_unchanged({k:v for k,v in before.items() if k!='source'},
                                               {k:v for k,v in after.items() if k!='source'})

    def test_uniform_row_error_uses_absolute_stationarity_not_just_similar_cards(self):
        for dy in (-3,-2,2,3):
            before,after=frames(dy)
            with self.subTest(dy=dy),patch('e7_assistant.inventory_tracking.inspect_tracking',
                    return_value={'matched':True,'offset':(0,-dy)}):
                BatchSelectionDriver._verify_unchanged(before,after)
            with patch('e7_assistant.inventory_tracking.inspect_tracking',
                    return_value={'matched':True,'offset':(0,0)}):
                with self.assertRaises(ValueError):BatchSelectionDriver._verify_unchanged(before,after)

    def test_partial_mixed_large_and_missing_pixel_proof_remain_rejected(self):
        for case in ('single','mixed','large','partial','no_proof'):
            before,after=frames()
            if case=='single':after['cards'][8:]=deepcopy(before['cards'][8:])
            if case=='mixed':after['cards'][8]['center']=(after['cards'][8]['center'][0],999)
            if case=='large':before,after=frames(4)
            if case=='partial':before['cards'].pop();after['cards'].pop()
            result={'matched':case!='no_proof','offset':(0,-3)}
            with self.subTest(case=case),patch('e7_assistant.inventory_tracking.inspect_tracking',return_value=result):
                with self.assertRaises(ValueError):BatchSelectionDriver._verify_unchanged(before,after)

    def test_positive_field_conflict_is_not_hidden_by_row_registration(self):
        for case in ('level','selected','nan'):
            before,after=frames()
            if case=='level':after['cards'][8]['level']=90
            if case=='selected':after['cards'][8]['selected']=True
            if case=='nan':after['cards'][8]['identity_vector']=[float('nan')]*8
            with self.subTest(case=case),patch('e7_assistant.inventory_tracking.inspect_tracking',
                    return_value={'matched':True,'offset':(0,-3)}):
                with self.assertRaises(ValueError):BatchSelectionDriver._verify_unchanged(before,after)
