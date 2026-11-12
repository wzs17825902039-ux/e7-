import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_scan import InventoryTraversal,unstable_overlap_offset
from e7_assistant.tasks import TaskControl

ROOT=Path(__file__).resolve().parents[1]


class ScrollAdjustmentTests(unittest.TestCase):
    def frames(self):
        return json.loads((ROOT/'runs/scroll-83f9-offline-reports.json').read_text(encoding='utf8'))

    def driver(self,before,after,failures=2):
        self.swipes=[];self.reads=0
        control=TaskControl();control.wait=lambda seconds:control.checkpoint()
        driver=BatchSelectionDriver.__new__(BatchSelectionDriver)
        driver.navigator=SimpleNamespace(control=control,journal=None,
            adb=SimpleNamespace(swipe=lambda *args:self.swipes.append(args)))
        def observe(reference,traversal,alternate=None):
            self.assertIs(reference,before)
            self.assertEqual(traversal.moves,0)
            self.reads+=1
            driver.last_scroll_observation=after
            if self.reads<=failures:
                raise ValueError('原配准未通过')
            traversal.moves+=1
            return after,1
        driver.observe_scrolled=observe
        return driver

    def test_two_same_row_near_matches_never_commit_coverage(self):
        before,after=self.frames()
        self.assertIsNone(unstable_overlap_offset(before,after))
        self.assertEqual(unstable_overlap_offset(before,after,max_per_row=2),1)
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):traversal.advance(before,after)
        self.assertEqual(traversal.moves,0)

    def test_small_adjustments_are_bounded_and_require_strict_read_success(self):
        before,after=self.frames();driver=self.driver(before,after)
        traversal=InventoryTraversal();traversal.start(before)
        result=driver.observe_scrolled_with_adjustment(before,traversal)
        self.assertEqual(result,(after,1))
        self.assertEqual(self.reads,3)
        self.assertEqual(self.swipes,[(500,450,500,426,300)]*2)
        self.assertEqual(traversal.moves,1)

    def test_failed_adjustments_preserve_zero_coverage(self):
        before,after=self.frames();driver=self.driver(before,after,failures=3)
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):driver.observe_scrolled_with_adjustment(before,traversal)
        self.assertEqual(len(self.swipes),2)
        self.assertEqual(traversal.moves,0)

    def test_conflicts_unknown_cards_and_insufficient_margin_never_adjust(self):
        for case in ('context','selection','unknown','margin'):
            before,after=self.frames()
            if case=='context':after['inventory_context']=[]
            if case=='selection':after['selected_count']+=1
            if case=='unknown':after['cards'][0]['known']=False
            if case=='margin':after['cards'][0]['center'][1]=200
            driver=self.driver(before,after)
            traversal=InventoryTraversal();traversal.start(before)
            with self.subTest(case=case),self.assertRaises(ValueError):
                driver.observe_scrolled_with_adjustment(before,traversal)
            self.assertEqual(self.swipes,[])
