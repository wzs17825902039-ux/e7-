from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from e7_assistant.inventory_top_vision import inspect_top,verify_top_anchor,context_pixels_equal
from e7_assistant.inventory_scan import InventoryTraversal
from e7_assistant.workflow_screen import Screen
from test_inventory_scan import report


class TopVisionTests(unittest.TestCase):
    def setUp(self):
        self.assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-top-2026-11-10'

    def screen(self,name):
        return Screen(str(self.assets/name),'inventory_batch_selection_empty',1280,720,(
            {'text':'获得','confidence':1.,'center':(900,100)},
            {'text':'1049/1200','confidence':1.,'center':(1050,100)}))

    def test_visible_head_positive_and_faded_head_negative(self):
        for name in ('01-head-visible.png','03-independent-head.png'):
            self.assertTrue(inspect_top(self.screen(name))['head_visible'])
        self.assertFalse(inspect_top(self.screen('02-settled.png'))['head_visible'])

    def test_blank_or_wrong_page_is_not_top(self):
        from dataclasses import replace
        self.assertFalse(inspect_top(replace(self.screen('01-head-visible.png'),page='home'))['head_visible'])
        with TemporaryDirectory() as folder:
            path=Path(folder)/'blank.png'
            for color in ('white','black','#808080'):
                Image.new('RGB',(1280,720),color).save(path)
                self.assertFalse(inspect_top(replace(self.screen('01-head-visible.png'),source=str(path)))['head_visible'])

    def anchor(self):
        current=report([0,1,2])
        current['inventory_context']=('1049/1200','获得')
        for card in current['cards']:
            card['center']=(card['center'][0],card['center'][1]+11)
        anchor={'method':'visible_head_then_settled','head_visible':True,'head_source':'head.png',
                'stable_source':current['source'],'inventory_context':current['inventory_context']}
        return current,anchor

    def test_anchor_requires_settled_first_row_same_context_and_source(self):
        from copy import deepcopy
        current,anchor=self.anchor()
        self.assertTrue(verify_top_anchor(anchor,current))
        for change in ('row','context','source','selected'):
            altered=deepcopy(current)
            if change=='row':
                altered['cards'][0]['center']=(160,240)
            elif change=='context':
                altered['inventory_context']=('1048/1200','获得')
            elif change=='source':
                altered['source']='other.png'
            else:
                altered['selected_count']=1
            with self.subTest(change=change),self.assertRaises(ValueError):
                verify_top_anchor(anchor,altered)

    def test_new_scan_does_not_inherit_previous_top_or_bottom(self):
        current,anchor=self.anchor()
        traversal=InventoryTraversal()
        traversal.start(current,anchor)
        self.assertTrue(traversal.top_verified)
        traversal.end_verified=True
        traversal.moves=5
        traversal.start(current)
        self.assertFalse(traversal.top_verified)
        self.assertFalse(traversal.end_verified)
        self.assertEqual(traversal.moves,0)

    def test_context_pixel_proof_rejects_single_changed_pixel(self):
        with TemporaryDirectory() as folder:
            a,b=Path(folder)/'a.png',Path(folder)/'b.png'
            image=Image.new('RGB',(1280,720),'white')
            image.save(a)
            image.save(b)
            self.assertTrue(context_pixels_equal(a,b,a))
            image.putpixel((900,100),(0,0,0))
            image.save(b)
            self.assertFalse(context_pixels_equal(a,b,a))
