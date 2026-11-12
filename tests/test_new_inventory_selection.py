from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import unittest
from PIL import Image,ImageDraw
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.inventory_grid_vision import locate_rows
from e7_assistant.workflow_screen import inspect_screen

ASSETS=Path(__file__).resolve().parents[1]/'docs/assets/sale-preview-2026-11-10'


class NewInventorySelectionTests(unittest.TestCase):
    def test_red_weapon_badge_is_read_from_white_glyph_on_orange_plate(self):
        source=Path(__file__).resolve().parents[1]/'runs/selected-inventory-resume-042639d5/workflow-0046.png'
        from e7_assistant.workflow_screen import inspect_selection_screen
        report=inspect_inventory(inspect_selection_screen(source),ignore_levels=True)
        card=next(c for c in report['cards'] if (c['row'],c['column'])==(2,0))
        self.assertEqual((card['rarity'],card['enhancement'],card['known']),('red',3,True))
        self.assertEqual(report['badge_evidence']['badge2_0']['proof']['value'],3)

    def test_selected_boosted_row_inner_border_is_rechecked_at_fitted_grid(self):
        source=Path(__file__).resolve().parents[1]/'runs/interrupted-batch-resume-639ca33b/workflow-0071.png'
        self.assertEqual(locate_rows(source,{}),[207,379,551])
        with TemporaryDirectory() as directory,Image.open(source) as image:
            ImageDraw.Draw(image).rectangle((732,310,760,350),fill=(0,0,0))
            damaged=Path(directory)/'damaged.png'
            image.save(damaged)
            with self.assertRaises(ValueError):
                locate_rows(damaged,{})

    def reports(self):
        return [inspect_inventory(inspect_screen(ASSETS/name),ignore_levels=True)
                for name in ('new-heads-before-selection.png','new-heads-after-selection.png')]

    def test_new_badges_and_selected_glow_keep_three_complete_rows(self):
        for name in ('new-heads-before-selection.png','new-heads-after-selection.png',
                     'new-heads-four-selected.png','new-heads-seven-selected.png'):
            self.assertEqual(locate_rows(ASSETS/name,{}),[207,379,551])
        before,after=self.reports()
        BatchSelectionDriver._verify_click(before,after,(0,0))
        self.assertEqual(after['selected_count'],1)

    def test_changed_target_icon_cannot_use_inner_content_fallback(self):
        before,after=self.reports()
        old,new=before['cards'][0],deepcopy(after['cards'][0])
        with TemporaryDirectory() as temporary,Image.open(new['tracking_source']) as image:
            # Paint the actual target icon, leaving selection count and surrounding cards intact.
            ImageDraw.Draw(image).rectangle((160,165,200,195),fill=(0,0,0))
            path=Path(temporary)/'changed.png';image.save(path)
            new['tracking_source']=str(path)
            self.assertFalse(BatchSelectionDriver._target_icon_content_unchanged(old,new))

    def test_button_only_selection_keeps_count_and_excludes_attributes(self):
        from e7_assistant.workflow_screen import inspect_selection_screen
        for name,expected in (('new-heads-before-selection.png',0),('new-heads-after-selection.png',1)):
            screen=inspect_selection_screen(ASSETS/name)
            report=inspect_inventory(screen,ignore_levels=True)
            self.assertEqual(report['selected_count'],expected)
            if expected:
                from e7_assistant.inventory_detail import read_selection_header
                detail=read_selection_header(screen,report['cards'][0])
                self.assertEqual((detail['rarity'],detail['slot']),('purple','helmet'))
            self.assertFalse(any(150<w['center'][0]<830 and 300<w['center'][1]<600 for w in screen.words))
