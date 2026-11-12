from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver,SelectionImageUnstable
from tests.test_batch_selection import card


class ClickJitterTests(unittest.TestCase):
    def frames(self):
        cards=[card(0),card(1)]
        for c in cards:
            x,y=c['center'];c.update(tracking_source='fake.png',tracking_box=(x-35,y-50,x+38,y+48))
        before={'cards':cards,'selected_count':0}
        after=deepcopy(before);after['selected_count']=1;after['cards'][0]['selected']=True
        item=after['cards'][1];item['center']=(item['center'][0],item['center'][1]+1)
        box=item['tracking_box'];item['tracking_box']=(box[0],box[1]+1,box[2],box[3]+1)
        return before,after

    def test_actual_non_target_row_jitter_after_single_click(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_vision import inspect_inventory
        assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before,after=[inspect_inventory(inspect_screen(assets/name)) for name in
                      ('37-click-before.png','38-click-after.png')]
        self.assertNotEqual(before['cards'][7]['center'],after['cards'][7]['center'])
        # 原图目标卡片仍有选中闪光，必须拒绝；不能以非目标抖动证明替代目标身份。
        with self.assertRaises(SelectionImageUnstable):
            BatchSelectionDriver._verify_click(before,after,(0,0))
        # 仅隔离验证非目标卡片的一像素配准；此副本不是实机通过证据。
        after['cards'][0]['identity_vector']=before['cards'][0]['identity_vector']
        BatchSelectionDriver._verify_click(before,after,(0,0))
        self.assertEqual(after['selected_count'],1)
        self.assertEqual([c['selected'] for c in after['cards']],[True]+[False]*20)

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_one_pixel_requires_complete_non_target_card_proof(self,proof):
        before,after=self.frames()
        after['cards'][1]['identity_vector']=[.99,.14]
        BatchSelectionDriver._verify_click(before,after,(0,0))
        proof.assert_called_once()

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':False})
    def test_missing_pixel_proof_cannot_pass(self,proof):
        before,after=self.frames()
        with self.assertRaises(SelectionImageUnstable):BatchSelectionDriver._verify_click(before,after,(0,0))

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_two_pixels_target_movement_conflicts_and_nan_remain_rejected(self,proof):
        for case in ('two_pixels','target','rarity','selection','nan','no_box'):
            before,after=self.frames()
            if case=='two_pixels':after['cards'][1]['center']=(260,202)
            if case=='target':
                before['cards'][0]['center']=(160,199)
            if case=='rarity':after['cards'][1]['rarity']='red'
            if case=='selection':after['cards'][1]['selected']=True
            if case=='nan':after['cards'][1]['identity_vector']=[float('nan'),0.]
            if case=='no_box':after['cards'][1].pop('tracking_box')
            with self.subTest(case=case),self.assertRaises(ValueError):
                BatchSelectionDriver._verify_click(before,after,(0,0))


if __name__=='__main__':unittest.main()
