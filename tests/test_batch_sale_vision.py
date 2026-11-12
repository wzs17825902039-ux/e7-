from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
import unittest
from PIL import Image,ImageDraw

from e7_assistant.batch_sale_vision import inspect_organized,inspect_sale_confirmation,content_proof,selected_state
from e7_assistant.workflow_screen import inspect_screen


class SaleVisionTests(unittest.TestCase):
    def test_live_sale_survivor_roll_highlight_can_fade_to_white(self):
        from e7_assistant.batch_sale_vision import verify_sale_survivors
        from e7_assistant.workflow import BatchItem
        from e7_assistant.rules import Equipment
        import json
        root=Path(__file__).resolve().parents[1]
        pending=json.loads((root/'runs/pending-sale-resume-6eeaef61/original-pending.json').read_text(encoding='utf8'))
        items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in pending['before']['items']]
        verify_sale_survivors(inspect_screen(root/'runs/pending-sale-resume-6eeaef61/workflow-0007.png'),
                             root/'runs/selected-inventory-resume-4467e66d/workflow-0004.png',
                             items,set(pending['before']['rejected']))

    def test_live_locked_survivors_use_lock_and_icon_proof(self):
        root=Path(__file__).resolve().parents[1]
        folder=root/'runs/selected-inventory-resume-741b452c'
        current=inspect_screen(folder/'workflow-0028.png')
        reference=folder/'workflow-0024.png'
        result=inspect_organized(current,reference,16,track_gold=False,locked_indices={5,13})
        self.assertEqual(result.selected,(False,)*16)
        with self.assertRaises(ValueError):
            inspect_organized(current,reference,16,track_gold=False,locked_indices={0,5,13})
        with TemporaryDirectory() as temporary,Image.open(current.source) as image:
            ImageDraw.Draw(image).rectangle((264,260,281,282),fill='black')
            path=Path(temporary)/'missing-lock.png';image.save(path)
            with self.assertRaises(ValueError):
                inspect_organized(replace(current,source=str(path)),reference,16,track_gold=False,locked_indices={5,13})

    @classmethod
    def setUpClass(cls):
        cls.assets=Path(__file__).resolve().parents[1]/'docs/assets/sale-preview-2026-11-10'
        cls.organize=inspect_screen(cls.assets/'organize.png')
        cls.sale=inspect_screen(cls.assets/'sale-dialog.png')

    def test_actual_dimmed_card_and_selected_count_are_independently_verified(self):
        state=inspect_organized(self.organize,self.assets/'normal.png',1)
        self.assertEqual(state.selected,(True,))
        self.assertEqual(state.gold,339420079)
        self.assertGreater(min(p['correlation'] for p in state.evidence[0]),.995)

    def test_actual_sale_reports_gold_and_returned_powder(self):
        result=inspect_sale_confirmation(self.sale)
        self.assertEqual((result.count,result.gold,result.powder),(1,25525,5))

    def test_actual_equipment_jewelry_and_mixed_reward_layouts(self):
        for name,expected in (('equipment',(1,15315,5,0)),('jewelry',(1,25525,0,5)),
                              ('mixed',(2,40840,5,5))):
            with self.subTest(layout=name):
                screen=inspect_screen(self.assets/f'sale-{name}.png')
                result=inspect_sale_confirmation(screen)
                self.assertEqual((result.count,result.gold,result.powder,result.jewelry_powder),expected)

    def test_missing_any_mixed_reward_icon_prevents_confirmation(self):
        screen=inspect_screen(self.assets/'sale-mixed.png')
        for box in ((498,339,565,388),(605,339,674,388),(713,339,782,388)):
            with self.subTest(box=box),TemporaryDirectory() as folder,Image.open(screen.source) as original:
                changed=original.copy();ImageDraw.Draw(changed).rectangle(box,fill='black')
                path=Path(folder)/'unknown-mixed.png';changed.save(path)
                with self.assertRaises(ValueError):inspect_sale_confirmation(replace(screen,source=str(path)))

    def test_changed_attribute_score_or_missing_content_is_rejected(self):
        with Image.open(self.assets/'normal.png') as normal,Image.open(self.assets/'organize.png') as organized:
            for box in ((110,181,185,204),(37,219,85,240),(25,139,101,160),(110,140,185,157)):
                changed=organized.copy();ImageDraw.Draw(changed).rectangle(box,fill='black')
                with self.subTest(box=box),self.assertRaises(ValueError): content_proof(normal,changed,0)

    def test_green_check_alone_or_yellow_border_alone_does_not_prove_selected(self):
        with Image.open(self.assets/'organize.png') as organized:
            for box in ((30,126,235,129),(38,160,88,198)):
                changed=organized.copy();ImageDraw.Draw(changed).rectangle(box,fill='black')
                with self.subTest(box=box),self.assertRaises(ValueError): selected_state(changed,0)

    def test_unknown_reward_icon_prevents_sale_confirmation(self):
        with TemporaryDirectory() as folder,Image.open(self.sale.source) as original:
            changed=original.copy();ImageDraw.Draw(changed).rectangle((659,339,728,388),fill='black')
            path=Path(folder)/'unknown-reward.png';changed.save(path)
            with self.assertRaises(ValueError): inspect_sale_confirmation(replace(self.sale,source=str(path)))


if __name__=='__main__': unittest.main()
