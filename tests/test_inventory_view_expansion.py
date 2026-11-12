from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_scan import InventoryTraversal
from tests.test_inventory_scan import report
from tests import test_inventory_scan as scan_fixtures
from tests import test_inventory_observation_retry as retry_fixtures


def snapshots():
    before,after=report([0,1]),report([0,1,2])
    for frame in (before,after):
        frame['inventory_context']=('1049/1200','获得')
        for card in frame['cards']:
            x,y=card['center']
            card.update(tracking_source=frame['source'],tracking_box=(x-35,y-50,x+35,y+48))
    return before,after


class ViewExpansionTests(unittest.TestCase):
    def test_actual_recovered_third_row_requires_original_location_image_proof(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        from e7_assistant.inventory_vision import _read_levels
        def missing_trailing(path,boxes):
            # 模拟第三行局部OCR仍未恢复；旧视口不能提前填入新行字段。
            return {} if any(k.startswith('level_trailing_anchor_') for k in boxes) else _read_levels(path,boxes)
        before=inspect_inventory(inspect_screen(assets/'35-view-two-rows.png'),missing_trailing)
        after=inspect_inventory(inspect_screen(assets/'36-view-three-rows.png'))
        self.assertEqual((len(before['cards']),len(after['cards'])),(14,21))
        with self.assertRaises(ValueError):
            BatchSelectionDriver._verify_unchanged({k:v for k,v in before.items() if k!='source'},
                                                   {k:v for k,v in after.items() if k!='source'})
        self.assertTrue(BatchSelectionDriver._can_expand_view(before,after))
        harness=retry_fixtures.ObservationRetryTests()
        driver=harness.driver([after])
        self.assertEqual(driver.observe_unchanged(before,allow_expansion=True),after)
        self.assertEqual(harness.inputs,[])
        traversal=InventoryTraversal();traversal.start(before)
        traversal.observe_end(after)
        self.assertEqual((traversal.covered_rows,traversal.moves),(3,0))
        self.assertFalse(traversal.end_verified)

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_default_strict_check_still_rejects_added_rows(self,proof):
        before,after=snapshots(); harness=retry_fixtures.ObservationRetryTests()
        driver=harness.driver([after])
        with self.assertRaises(ValueError):driver.observe_unchanged(before)
        self.assertEqual(harness.reads,1)

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_conflicts_unknown_new_cards_and_layout_changes_never_expand(self,proof):
        for case in ('count','sort','old_level','old_selected','unknown','selected','outside',
                     'tail','gap','one_row','partial'):
            before,after=snapshots()
            if case=='count':after['selected_count']=1
            if case=='sort':after['inventory_context']=('1049/1200','最大强化')
            if case=='old_level':after['cards'][0]['level']=90
            if case=='old_selected':after['cards'][0]['selected']=True
            if case=='unknown':after['cards'][-1].update(level=None,known=False,eligible=False)
            if case=='selected':after['cards'][-1]['selected']=True
            if case=='outside':after['cards'][-1]['tracking_box']=(730,570,800,668)
            if case=='tail':after['tail_layout']={'end_verified':True,'row':2,'tail_count':7}
            if case=='gap':after['cards'][-1]['row']=3
            if case=='one_row':before['cards']=before['cards'][:7]
            if case=='partial':after['cards'].pop()
            with self.subTest(case=case):self.assertFalse(BatchSelectionDriver._can_expand_view(before,after))

    def test_missing_or_changed_new_row_pixels_cannot_restore_a_row(self):
        before,after=snapshots()
        with patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':False}):
            self.assertFalse(BatchSelectionDriver._can_expand_view(before,after))
        def proof(a,b):return {'matched':b['row']!=2}
        with patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=proof):
            self.assertFalse(BatchSelectionDriver._can_expand_view(before,after))

    def expanding_driver(self,initial_reads):
        self.harness=scan_fixtures.PaginatedSelectionTests()
        driver=self.harness.driver([(2,0)])
        read=driver.navigator.read
        self.reads=0
        def observe():
            frame=read(); self.reads+=1
            if self.reads<=initial_reads:frame['cards']=frame['cards'][:14]
            for card in frame['cards']:
                x,y=card['center']
                card.update(tracking_source=frame['source'],tracking_box=(x-35,y-50,x+35,y+48))
            return frame
        driver.navigator.read=observe
        return driver

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_restored_row_is_selected_before_leaving_visible_page(self,proof):
        driver=self.expanding_driver(1)
        result=driver.collect_visible(limit=1)
        self.assertEqual(result['selected_count'],1)
        self.assertEqual(self.harness.details,['2:0'])
        self.assertEqual(self.harness.swipes,[])

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_late_expansion_before_scroll_is_processed_without_swiping_over_it(self,proof):
        driver=self.expanding_driver(2)
        result=driver.collect_pages(limit=1,max_pages=3)
        self.assertEqual(result['selected_count'],1)
        self.assertEqual(self.harness.details,['2:0'])
        self.assertEqual(self.harness.swipes,[])


if __name__=='__main__':unittest.main()
