from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

from e7_assistant.batch_selection import BatchSelectionDriver, SelectionImageUnstable
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.inventory_vision import inspect_inventory


class TargetJitterTests(unittest.TestCase):
    def test_native_one_pixel_and_normalized_two_pixel_anchor_rounding(self):
        root=Path(__file__).resolve().parents[1]/'runs/full-workflow-ea1671cf'
        before,after=[inspect_inventory(inspect_screen(root/name),ignore_levels=True)
                      for name in ('workflow-0034.png','workflow-0035.png')]
        BatchSelectionDriver._verify_click(before,after,(1,0))

    def test_unshifted_peer_glow_requires_full_registration_and_stationary_interior(self):
        root=Path(__file__).resolve().parents[1]/'runs/full-workflow-ae2170a0'
        before,after=[inspect_inventory(inspect_screen(root/name),ignore_levels=True)
                      for name in ('workflow-0124.png','workflow-0128.png')]
        BatchSelectionDriver._verify_click(before,after,(2,2))

    def test_changed_target_art_does_not_pass_illumination_invariant_proof(self):
        from PIL import Image,ImageChops
        root=Path(__file__).resolve().parents[1]/'runs/full-workflow-ea1671cf'
        before,after=[inspect_inventory(inspect_screen(root/name),ignore_levels=True)
                      for name in ('workflow-0034.png','workflow-0035.png')]
        with TemporaryDirectory() as folder:
            output=Path(folder)/'changed.png'
            with Image.open(root/'workflow-0035.png') as image:
                image=image.convert('RGB')
                box=(151,295,198,326)
                image.paste(ImageChops.offset(image.crop(box),6,0),box)
                image.save(output)
            for card in after['cards']:card['tracking_source']=str(output)
            with self.assertRaises(ValueError):BatchSelectionDriver._verify_click(before,after,(1,0))

    @classmethod
    def setUpClass(cls):
        assets=Path(__file__).resolve().parents[1]/'docs/assets/batch-selection-2026-11-10'
        cls.before,cls.animation,cls.after=[inspect_inventory(inspect_screen(assets/name))
            for name in ('08-before.png','08-animation.png','08-settled.png')]

    def test_real_eighth_selection_settled_at_same_pixels(self):
        self.assertEqual(self.before['selected_count'],7)
        self.assertEqual(self.after['selected_count'],8)
        self.assertEqual(self.after['cards'][8]['center'][1]-self.before['cards'][8]['center'][1],-1)
        BatchSelectionDriver._verify_click(self.before,self.after,(1,1))

    def test_identity_crop_rounding_changes_without_native_card_motion(self):
        root=Path(__file__).resolve().parents[1]/'runs/selected-inventory-resume-f9951d09'
        before,after=[inspect_inventory(inspect_screen(root/name),ignore_levels=True)
                      for name in ('workflow-0041.png','workflow-0045.png')]
        self.assertEqual(before['cards'][4]['center'],after['cards'][4]['center'])
        self.assertNotEqual(before['cards'][4]['identity_box'],after['cards'][4]['identity_box'])
        BatchSelectionDriver._verify_click(before,after,(0,4))

    def test_selected_peer_glow_does_not_hide_stationary_interior_proof(self):
        from e7_assistant.workflow_screen import inspect_selection_screen
        root=Path(__file__).resolve().parents[1]/'runs/pending-inventory-resume-a3186bdf'
        before,after=[inspect_inventory(inspect_selection_screen(root/name),ignore_levels=True)
                      for name in ('workflow-0182.png','workflow-0186.png')]
        BatchSelectionDriver._verify_click(before,after,(1,3))

    def test_animation_still_requires_readonly_retry(self):
        with self.assertRaises(SelectionImageUnstable):
            BatchSelectionDriver._verify_click(self.before,self.animation,(1,1))

    def test_missing_peer_proof_or_identity_metadata_stops(self):
        for case in ('peer_missing','peer_moved','identity_missing','target_moved','changed_level','extra_tick'):
            before,after=deepcopy(self.before),deepcopy(self.after)
            if case=='peer_missing':after['cards'][7]['tracking_source']=None
            if case=='peer_moved':after['cards'][7]['center']=(188,345)
            if case=='identity_missing':before['cards'][8].pop('identity_box')
            if case=='target_moved':after['cards'][8]['center']=(287,342)
            if case=='changed_level':after['cards'][8]['level']=90
            if case=='extra_tick':after['cards'][9]['selected']=True
            with self.subTest(case=case),self.assertRaises(ValueError):
                BatchSelectionDriver._verify_click(before,after,(1,1))

    def test_real_movement_offset_does_not_prove_stationary_row(self):
        with patch('e7_assistant.inventory_tracking.inspect_tracking',
                   return_value={'matched':True,'offset':(0,0)}):
            with self.assertRaises(SelectionImageUnstable):
                BatchSelectionDriver._verify_click(self.before,self.after,(1,1))


if __name__=='__main__':unittest.main()
