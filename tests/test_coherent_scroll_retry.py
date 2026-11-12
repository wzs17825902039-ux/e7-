import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image,ImageChops

from e7_assistant.inventory_scan import InventoryTraversal,coherent_overlap_retry_offset

ROOT=Path(__file__).resolve().parents[1]


class CoherentScrollRetryTests(unittest.TestCase):
    def frames(self):
        return json.loads((ROOT/'runs/scroll-b6a-offline.json').read_text(encoding='utf8'))

    def test_live_thirteen_strict_matches_only_authorize_retry(self):
        before,after=self.frames()
        self.assertEqual(coherent_overlap_retry_offset(before,after),1)
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):traversal.advance(before,after)
        self.assertEqual(traversal.moves,0)

    def test_conflicts_and_missing_evidence_cannot_authorize_retry(self):
        for case in ('context','selection','rarity','missing','position','nan'):
            before,after=self.frames()
            if case=='context':after['inventory_context']=[]
            if case=='selection':after['selected_count']+=1
            if case=='rarity':after['cards'][0]['rarity']='red'
            if case=='missing':after['cards'][0]['known']=False
            if case=='nan':after['cards'][0]['identity_vector']=[float('nan')]*8
            if case=='position':
                box=after['cards'][0]['tracking_box']
                after['cards'][0]['tracking_box']=[box[0],box[1]+4,box[2],box[3]+4]
            with self.subTest(case=case):
                self.assertIsNone(coherent_overlap_retry_offset(before,after))

    def test_retry_limits_outliers_and_requires_coherent_geometry(self):
        for case in ('three','four','two_low','incoherent'):
            before,after=self.frames()
            def proof(a,b):
                if a['row']!=b['row']+1:return {'matched':False,'score':.5,'mae':10,'offset':(0,0)}
                index=b['row']*7+b['column']
                weak=index<(4 if case=='four' else 3)
                score=(.985 if index==0 or case=='two_low' and index==1 else .994) if weak else .999
                return {'matched':not weak,'score':score,'mae':1,
                        'offset':(0,2 if case=='incoherent' and index==1 else 0)}
            with self.subTest(case=case),patch('e7_assistant.inventory_tracking.inspect_tracking',side_effect=proof):
                self.assertEqual(coherent_overlap_retry_offset(before,after),1 if case=='three' else None)

    def test_actual_adjusted_frame_uses_one_feature_proof_without_lowering_tracking_gate(self):
        from e7_assistant.inventory_vision import inspect_inventory
        from e7_assistant.workflow_screen import inspect_screen
        before,_=self.frames()
        before['inventory_context']=tuple(before['inventory_context'])
        after=inspect_inventory(inspect_screen(ROOT/'runs/scroll-recovery-97f966ec/workflow-0012.png'),ignore_levels=True)
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):traversal.advance(before,after)
        self.assertEqual(traversal.advance_with_features(before,after),1)
        self.assertEqual(traversal.moves,1)
        from e7_assistant.batch_selection import BatchSelectionDriver
        driver=BatchSelectionDriver.__new__(BatchSelectionDriver)
        driver.navigator=SimpleNamespace(journal=None)
        def rejected(reference,traversal,alternate=None):
            driver.last_scroll_observation=after
            raise ValueError('严格配准未通过')
        driver.observe_scrolled=rejected
        recovered=InventoryTraversal();recovered.start(before)
        self.assertEqual(driver.observe_scrolled_with_adjustment(before,recovered),(after,1))
        self.assertEqual(recovered.moves,1)
        with TemporaryDirectory() as folder:
            changed=deepcopy(after);card=changed['cards'][13];box=card['tracking_box']
            output=Path(folder)/'shifted.png'
            with Image.open(card['tracking_source']) as image:
                image=image.convert('RGB');image.paste(ImageChops.offset(image.crop(box),2,0),box);image.save(output)
            card['tracking_source']=str(output)
            rejected=InventoryTraversal();rejected.start(before)
            with self.assertRaises(ValueError):rejected.advance_with_features(before,changed)
            self.assertEqual(rejected.moves,0)

    def test_live_majority_in_each_row_only_authorizes_recovery(self):
        before,after=json.loads((ROOT/'runs/scroll-d3b6-offline.json').read_text(encoding='utf8'))
        self.assertEqual(coherent_overlap_retry_offset(before,after),1)
        traversal=InventoryTraversal();traversal.start(before)
        with self.assertRaises(ValueError):traversal.advance_with_features(before,after)
        self.assertEqual(traversal.moves,0)
