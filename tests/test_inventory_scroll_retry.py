from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_scan import InventoryTraversal,missing_overlap_offset
from e7_assistant.tasks import TaskControl,Cancelled
from tests.test_inventory_scan import report


def frames():
    before,complete=report([0,1,2]),report([1,2,3])
    for frame in (before,complete):
        frame['inventory_context']=('1049/1200','获得')
        for card in frame['cards']:
            x,y=card['center']
            card.update(tracking_source='fake.png',tracking_box=(x-35,y-50,x+35,y+48))
    missing=deepcopy(complete)
    missing['cards'][9].update(rarity=None,known=False,eligible=False)
    return before,missing,complete


class ScrollRetryTests(unittest.TestCase):
    def test_actual_additional_missing_field_during_reread_keeps_coverage_zero(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before,first,second=[inspect_inventory(inspect_screen(assets/name)) for name in
                            ('58-reread-loss-reference.png','59-reread-loss-first.png','60-reread-loss-second.png')]
        self.assertEqual(first['cards'][10]['enhancement'],0)
        for frame in (first,second):
            frame['cards'][10].update(enhancement=None,known=False,eligible=False)
        self.assertEqual(first['cards'][9]['rarity'],'purple')
        self.assertIsNone(second['cards'][9]['rarity'])
        self.assertTrue(BatchSelectionDriver._can_retry_missing(first,second))
        driver=self.driver([first,second])
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):driver.observe_scrolled(before,traversal)
        self.assertEqual((self.reads,traversal.moves,traversal.covered_rows),(4,0,3))

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_additional_missing_field_then_complete_frame_advances_only_once(self,proof):
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        before,missing,complete=frames()
        more=deepcopy(missing)
        more['cards'][10].update(rarity=None,known=False,eligible=False)
        driver=self.driver([missing,more,complete])
        traversal=InventoryTraversal();traversal.start(before)
        result,offset=driver.observe_scrolled(before,traversal)
        self.assertEqual((self.reads,offset,traversal.moves),(3,1,1))
        self.assertEqual(result,complete)
        self.assertIsNone(more['cards'][10]['rarity'])

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_incomplete_anchor_rereads_without_committing_coverage(self,proof):
        from e7_assistant.inventory_vision import InventoryObservationIncomplete
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        before,_,complete=frames();driver=self.driver([])
        traversal=InventoryTraversal();traversal.start(before)
        with patch.object(driver,'observe',side_effect=[InventoryObservationIncomplete('anchors'),complete]) as read:
            result,offset=driver.observe_scrolled(before,traversal)
        self.assertEqual((read.call_count,offset,traversal.moves),(2,1,1))
        self.assertEqual(result,complete)

    def test_incomplete_anchor_stops_after_four_reads(self):
        from e7_assistant.inventory_vision import InventoryObservationIncomplete
        before,_,_=frames();driver=self.driver([])
        traversal=InventoryTraversal();traversal.start(before)
        with patch.object(driver,'observe',side_effect=InventoryObservationIncomplete('anchors')) as read:
            with self.assertRaises(InventoryObservationIncomplete):driver.observe_scrolled(before,traversal)
        self.assertEqual((read.call_count,traversal.moves,traversal.covered_rows),(4,0,3))

    def test_other_observation_errors_do_not_retry(self):
        before,_,_=frames();driver=self.driver([])
        traversal=InventoryTraversal();traversal.start(before)
        with patch.object(driver,'observe',side_effect=ValueError('wrong page')) as read:
            with self.assertRaises(ValueError):driver.observe_scrolled(before,traversal)
        self.assertEqual((read.call_count,traversal.moves),(1,0))

    def test_actual_two_validated_same_view_references_keep_original_tracking_gate(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        old,fresh,after=[inspect_inventory(inspect_screen(assets/name)) for name in
                        ('32-scroll-reference.png','33-scroll-fresh.png','34-scroll-after.png')]
        traversal=InventoryTraversal();traversal.start(old)
        with self.assertRaises(ValueError): traversal.advance(fresh,after)
        driver=self.driver([after])
        result,offset=driver.observe_scrolled(fresh,traversal,old)
        self.assertEqual((offset,traversal.moves,self.reads),(1,1,1))
        self.assertEqual(result,after)
        self.assertTrue(any(kind=='inventory_scroll_reference_verified' for kind,_ in self.events))

    def test_changed_alternate_reference_is_rejected_before_reading(self):
        before,missing,complete=frames(); alternate=deepcopy(before)
        alternate['selected_count']=1
        driver=self.driver([missing,complete])
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError): driver.observe_scrolled(before,traversal,alternate)
        self.assertEqual((self.reads,traversal.moves),(0,0))

    def test_actual_scroll_quality_recovers_but_missing_evidence_still_only_retries(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before=inspect_inventory(inspect_screen(assets/'28-scroll-missing-before.png'))
        after=inspect_inventory(inspect_screen(assets/'29-scroll-missing-after.png'))
        self.assertEqual(after['cards'][9]['rarity'],'purple')
        self.assertEqual(after['cards'][9]['rarity_evidence']['source'],'outer_purple_glow')
        accepted=InventoryTraversal(); accepted.start(before)
        self.assertEqual(accepted.advance(before,after),1)
        # 保留未知字段不能累计覆盖的原断言；照片现已可由独立光晕证据恢复。
        after=deepcopy(after)
        after['cards'][9].update(rarity=None,known=False,eligible=False)
        self.assertEqual(missing_overlap_offset(before,after),1)
        traversal=InventoryTraversal(); traversal.start(before)
        driver=self.driver([after])
        with self.assertRaises(ValueError): driver.observe_scrolled(before,traversal)
        self.assertEqual((self.reads,traversal.moves),(4,0))
        self.assertIsNone(after['cards'][9]['rarity'])

    def driver(self,observations):
        self.reads,self.events=0,[]
        control=TaskControl()
        control.wait=lambda seconds:control.checkpoint()
        def read():
            result=deepcopy(observations[min(self.reads,len(observations)-1)])
            self.reads+=1
            return result
        nav=SimpleNamespace(read=read,control=control,journal=SimpleNamespace(
            emit=lambda kind,**data:self.events.append((kind,data))))
        return BatchSelectionDriver(nav,reader=lambda screen:screen)

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_recovered_fields_advance_once_and_missing_snapshot_remains_missing(self,proof):
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        before,missing,complete=frames()
        traversal=InventoryTraversal(); traversal.start(before)
        driver=self.driver([missing,complete])
        result,offset=driver.observe_scrolled(before,traversal)
        self.assertEqual((offset,traversal.moves,traversal.covered_rows),(1,1,4))
        self.assertEqual(result,complete)
        self.assertIsNone(missing['cards'][9]['rarity'])
        self.assertEqual(self.reads,2)

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_missing_fields_remain_unaccepted_after_four_reads(self,proof):
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        before,missing,_=frames(); traversal=InventoryTraversal(); traversal.start(before)
        driver=self.driver([missing])
        with self.assertRaises(ValueError): driver.observe_scrolled(before,traversal)
        self.assertEqual((self.reads,traversal.moves),(4,0))
        self.assertEqual(len(self.events),3)

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_conflict_context_unknown_old_no_image_and_stationary_do_not_retry(self,proof):
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        for case in ('conflict','context','unknown_old','no_image','nan','stationary'):
            before,missing,complete=frames()
            if case=='conflict': missing['cards'][0]['level']=90
            if case=='context': missing['inventory_context']=('1050/1200','获得')
            if case=='unknown_old': before['cards'][16]['rarity']=None
            if case=='no_image': missing['cards'][9]['tracking_source']=None
            if case=='nan': missing['cards'][9]['identity_vector']=[float('nan')]*8
            if case=='stationary':
                missing=deepcopy(before); missing['cards'][9].update(rarity=None,known=False,eligible=False)
            traversal=InventoryTraversal(); traversal.start(before)
            driver=self.driver([missing,complete])
            with self.subTest(case=case),self.assertRaises(ValueError):
                driver.observe_scrolled(before,traversal)
            self.assertEqual((self.reads,traversal.moves),(1,0))

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_positive_changes_in_new_row_during_retry_stop(self,proof):
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        before,missing,complete=frames()
        complete['cards'][-1]['level']=90
        driver=self.driver([missing,complete])
        traversal=InventoryTraversal(); traversal.start(before)
        with self.assertRaises(ValueError): driver.observe_scrolled(before,traversal)
        self.assertEqual(traversal.moves,0)

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_new_row_missing_fields_must_recover_before_coverage_is_committed(self,proof):
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        before,_,complete=frames(); missing=deepcopy(complete)
        missing['cards'][-1].update(rarity=None,known=False,eligible=False)
        traversal=InventoryTraversal();traversal.start(before)
        driver=self.driver([missing,complete])
        result,offset=driver.observe_scrolled(before,traversal)
        self.assertEqual((offset,self.reads,traversal.moves),(1,2,1))
        self.assertTrue(result['cards'][-1]['known'])

    @patch('e7_assistant.inventory_tracking.inspect_tracking')
    def test_stop_during_retry_does_not_read_or_advance_again(self,proof):
        proof.side_effect=lambda a,b:{'matched':a['identity_vector']==b['identity_vector']}
        before,missing,complete=frames(); driver=self.driver([missing,complete])
        driver.navigator.control.wait=lambda seconds:driver.navigator.control.stop()
        traversal=InventoryTraversal(); traversal.start(before)
        with self.assertRaises(Cancelled): driver.observe_scrolled(before,traversal)
        self.assertEqual((self.reads,traversal.moves),(1,0))


if __name__=='__main__': unittest.main()
