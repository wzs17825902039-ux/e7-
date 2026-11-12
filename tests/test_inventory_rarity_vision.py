from dataclasses import replace
from pathlib import Path
import math
import tempfile
import unittest

from PIL import Image, ImageDraw

from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


class RarityOcclusionTests(unittest.TestCase):
    def test_selected_dimmed_weapon_uses_both_restored_border_regions(self):
        source=Path(__file__).resolve().parents[1]/'runs/pending-sale-resume-aa53f191/workflow-0043.png'
        report=inspect_inventory(inspect_screen(source),ignore_levels=True)
        card=report['cards'][8]
        self.assertIs(card['selected'],True)
        self.assertEqual(card['rarity'],'red')
        self.assertEqual(card['rarity_evidence']['source'],'selected_border_consensus')

    @classmethod
    def setUpClass(cls):
        cls.source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/49-rarity-obscured.png'
        cls.screen=inspect_screen(cls.source)

    def inspect(self,screen):
        # 此原图21件等级均已由独立OCR接受为85；这里单独回归品质取样。
        return inspect_inventory(screen,lambda path,boxes:{k:'85' for k in boxes})

    def test_actual_weapon_art_occlusion_still_recognizes_red(self):
        report=self.inspect(self.screen)
        card=report['cards'][15]
        self.assertEqual((card['row'],card['column']),(2,1))
        self.assertEqual(card['rarity'],'red')
        self.assertTrue(card['known'])
        self.assertEqual(card['rarity_evidence']['source'],'border_consensus')

    def test_three_more_blades_cannot_hide_their_red_background(self):
        screen=inspect_screen(self.source.parent/'54-rarity-weapons-unknown.png')
        report=self.inspect(screen)
        self.assertEqual(len(report['cards']),21)
        for index in (17,18,20):
            with self.subTest(index=index):
                card=report['cards'][index]
                self.assertEqual(card['rarity'],'red')
                self.assertTrue(card['known'])
                self.assertEqual(card['rarity_evidence']['source'],'border_consensus')

    def test_outer_gray_border_is_excluded_without_lowering_color_threshold(self):
        screen=inspect_screen(self.source.parent/'86-border-neutral-top-rarity.png')
        report=inspect_inventory(screen,ignore_levels=True)
        card=report['cards'][7]
        self.assertEqual(card['rarity'],'red')
        self.assertTrue(card['known'])
        self.assertEqual(card['rarity_evidence']['source'],'border_consensus')
        self.assertGreater(card['rarity_evidence']['border_top_red'],.55)
        self.assertGreater(card['rarity_evidence']['border_left_corner_red'],.55)

    def test_all_visible_card_rarities_match_original_picture(self):
        expected=(['red']*5+['purple']*2+['purple']+['red']*6+
                  ['red']*5+['purple','red'])
        self.assertEqual([c['rarity'] for c in self.inspect(self.screen)['cards']],expected)

    def test_red_art_inside_actual_purple_frame_is_never_red(self):
        from e7_assistant.inventory_scan import InventoryTraversal
        folder=self.source.parent
        before=self.inspect(inspect_screen(folder/'50-rarity-purple-before.png'))
        after=self.inspect(inspect_screen(folder/'51-rarity-purple-after.png'))
        self.assertEqual(before['cards'][9]['rarity'],'purple')
        self.assertEqual(after['cards'][2]['rarity'],'purple')
        traversal=InventoryTraversal()
        traversal.start(before)
        self.assertEqual(traversal.advance(before,after),1)

    def changed_borders(self,top=None,corner=None,glow_top=None,glow_bottom=None):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'changed.png'
            with Image.open(self.source) as image:
                draw=ImageDraw.Draw(image)
                for color,box in ((top,(359,543,394,550)),(corner,(329,561,337,575)),
                                  (glow_top,(425,553,428,578)),(glow_bottom,(425,583,428,608))):
                    if color is not None:
                        native=(math.floor(box[0]*1280/1661),math.floor(box[1]*720/933),
                                math.ceil(box[2]*1280/1661),math.ceil(box[3]*720/933))
                        draw.rectangle(native,fill=color)
                image.save(path)
            return self.inspect(replace(self.screen,source=str(path)))['cards'][15]

    def test_one_missing_or_other_colored_border_never_infers_red(self):
        for patch in ('top','corner'):
            for color in ((60,60,60),(20,60,180),(20,150,30),(120,40,120)):
                with self.subTest(patch=patch,color=color):
                    card=self.changed_borders(**{patch:color})
                    self.assertIsNone(card['rarity'])
                    self.assertFalse(card['known'])
                    self.assertFalse(card['eligible'])

    def test_both_neutral_or_blue_or_green_borders_remain_unknown(self):
        for color in ((60,60,60),(20,60,180),(20,150,30)):
            with self.subTest(color=color):
                card=self.changed_borders(top=color,corner=color)
                self.assertIsNone(card['rarity'])
                self.assertFalse(card['eligible'])

    def test_partial_purple_glow_vetoes_red_but_does_not_infer_purple(self):
        for name in ('glow_top','glow_bottom'):
            with self.subTest(part=name):
                card=self.changed_borders(**{name:(100,35,140)})
                self.assertIsNone(card['rarity'])
                self.assertFalse(card['eligible'])


if __name__=='__main__':
    unittest.main()
