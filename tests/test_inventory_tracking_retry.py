from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_scan import InventoryTraversal,unstable_overlap_offset
from tests import test_inventory_scroll_retry as fixtures


def proof(a,b):
    if a['identity_vector']!=b['identity_vector']:
        return {'matched':False,'score':.6,'mae':12}
    unstable=(a['tracking_source']!=b['tracking_source'] and b['tracking_source']=='unstable.png'
              and b['column']==1 and b['row']==0)
    return {'matched':not unstable,'score':.9948 if unstable else .9999,'mae':1.1 if unstable else .1}


def frames():
    before,_,complete=fixtures.frames()
    unstable=deepcopy(complete)
    for card in unstable['cards']:card['tracking_source']='unstable.png'
    return before,unstable,complete


class TrackingRetryTests(unittest.TestCase):
    def test_actual_one_unstable_card_per_row_only_authorizes_readonly_retry(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before,after=[inspect_inventory(inspect_screen(assets/name)) for name in
                      ('56-two-rows-unstable-before.png','57-two-rows-unstable-after.png')]
        self.assertEqual(unstable_overlap_offset(before,after),1)
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):traversal.advance(before,after)
        harness=fixtures.ScrollRetryTests();driver=harness.driver([after])
        with self.assertRaises(ValueError):driver.observe_scrolled(before,traversal)
        self.assertEqual((harness.reads,traversal.moves,traversal.covered_rows),(4,0,3))

    def test_two_rows_recover_only_when_every_card_passes_original_gate(self):
        def dual(a,b):
            result=proof(a,b)
            if (a['identity_vector']==b['identity_vector'] and b['tracking_source']=='unstable.png'
                    and b['row']==1 and b['column']==1):
                return {'matched':False,'score':.9943,'mae':1.2}
            return result
        with patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=dual):
            before,unstable,complete=frames()
            self.assertEqual(unstable_overlap_offset(before,unstable),1)
            traversal=InventoryTraversal();traversal.start(before)
            with self.assertRaises(ValueError):traversal.advance(before,unstable)
            harness=fixtures.ScrollRetryTests();driver=harness.driver([unstable,complete])
            result,offset=driver.observe_scrolled(before,traversal)
            self.assertEqual((offset,harness.reads,traversal.moves),(1,2,1))
            self.assertEqual(result,complete)

    def test_two_row_retry_preserves_conflict_and_image_quality_checks(self):
        for case in ('level','quality','selection','low','high_mae','three'):
            before,unstable,_=frames()
            if case=='level':unstable['cards'][8]['level']=90
            if case=='quality':unstable['cards'][8]['rarity']='red'
            if case=='selection':unstable['cards'][8]['selected']=True
            def dual(a,b):
                result=proof(a,b)
                if a['identity_vector']==b['identity_vector'] and b['tracking_source']=='unstable.png':
                    if b['row']==1 and b['column']==1:
                        return {'matched':False,'score':.98 if case=='low' else .9943,
                                'mae':6 if case=='high_mae' else 1.2}
                    if case=='three' and b['row']==1 and b['column']==2:
                        return {'matched':False,'score':.9943,'mae':1.2}
                return result
            with self.subTest(case=case),patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=dual):
                self.assertIsNone(unstable_overlap_offset(before,unstable))

    def test_actual_near_threshold_card_authorizes_reread_but_never_coverage(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before,after=[inspect_inventory(inspect_screen(assets/name)) for name in
                      ('42-scroll-low-match-before.png','43-scroll-low-match-after.png')]
        self.assertEqual(unstable_overlap_offset(before,after),1)
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):traversal.advance(before,after)
        harness=fixtures.ScrollRetryTests();driver=harness.driver([after])
        with self.assertRaises(ValueError):driver.observe_scrolled(before,traversal)
        self.assertEqual((harness.reads,traversal.moves,traversal.covered_rows),(4,0,3))

    @patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=proof)
    def test_recovered_frame_commits_once_under_original_tracking_gate(self,_):
        before,unstable,complete=frames()
        self.assertEqual(unstable_overlap_offset(before,unstable),1)
        harness=fixtures.ScrollRetryTests();driver=harness.driver([unstable,complete])
        traversal=InventoryTraversal();traversal.start(before)
        result,offset=driver.observe_scrolled(before,traversal)
        self.assertEqual((offset,harness.reads,traversal.moves),(1,2,1))
        self.assertEqual(result,complete)

    @patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=proof)
    def test_conflicts_missing_evidence_and_stationary_frames_do_not_authorize_retry(self,_):
        for case in ('level','quality','selection','context','missing','nan','stationary','complete'):
            before,unstable,complete=frames()
            if case=='level':unstable['cards'][1]['level']=90
            if case=='quality':unstable['cards'][1]['rarity']='red'
            if case=='selection':unstable['cards'][1]['selected']=True
            if case=='context':unstable['inventory_context']=('1050/1200','获得')
            if case=='missing':unstable['cards'][1]['tracking_source']=None
            if case=='nan':unstable['cards'][1]['identity_vector']=[float('nan')]*8
            if case=='stationary':unstable=deepcopy(before)
            if case=='complete':unstable=complete
            with self.subTest(case=case):self.assertIsNone(unstable_overlap_offset(before,unstable))

    def test_two_unstable_cards_low_match_and_partial_rows_reject(self):
        before,unstable,_=frames()
        for case in ('two','low','partial'):
            def match(a,b):
                result=proof(a,b)
                if a['identity_vector']==b['identity_vector']:
                    if case=='two' and b['row']==0 and b['column']==2:
                        return {'matched':False,'score':.994,'mae':1}
                    if case=='low' and not result['matched']:return {'matched':False,'score':.98,'mae':1}
                return result
            after=deepcopy(unstable)
            if case=='partial':
                after['cards']=after['cards'][:13]
                after['tail_layout']={'row':1,'tail_count':6}
            with self.subTest(case=case),patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=match):
                self.assertIsNone(unstable_overlap_offset(before,after))

    @patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=proof)
    def test_identical_row_candidates_cannot_authorize_a_guessed_offset(self,_):
        before,unstable,_=frames()
        unstable['cards']=unstable['cards'][:14]
        for frame in (before,unstable):
            for card in frame['cards']:card['identity_vector']=[1.,0.]
        self.assertIsNone(unstable_overlap_offset(before,unstable))

    @patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=proof)
    def test_semantic_conflict_during_reread_still_stops(self,_):
        before,unstable,complete=frames();complete['cards'][1]['level']=90
        harness=fixtures.ScrollRetryTests();driver=harness.driver([unstable,complete])
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):driver.observe_scrolled(before,traversal)
        self.assertEqual(traversal.moves,0)
