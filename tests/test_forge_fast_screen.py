from pathlib import Path
import unittest
from unittest.mock import patch
from e7_assistant.workflow_screen import inspect_forge_screen
from e7_assistant.initial_cleanup import inspect_inventory

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'docs/assets/sale-preview-2026-11-10'


class FastForgeScreenTests(unittest.TestCase):
    def test_full_inventory_modal_wins_over_dimmed_craft_result(self):
        screen=inspect_forge_screen(ROOT/'runs/full-workflow-82fb2fba/workflow-0098.png')
        self.assertEqual(screen.page,'inventory_full')
        self.assertTrue(screen.find('取消',(350,350,650,650)))

    def test_result_and_confirmation_buttons_keep_original_coordinates(self):
        for name,page,button,region in (
            ('craft-result-dimmed-gold.png','craft_result','重新制作',(750,615,925,695)),
            ('craft-repeat-confirmation.png','craft_confirmation','制作',(770,500,880,565))):
            with self.subTest(page=page):
                screen=inspect_forge_screen(ASSETS/name)
                self.assertEqual(screen.page,page)
                self.assertTrue(screen.find(button,region))

    def test_non_forge_screen_uses_full_reader(self):
        from e7_assistant.workflow_screen import inspect_screen
        source=ASSETS/'cleanup-zero-selection.png'
        with patch('e7_assistant.workflow_screen.inspect_screen',wraps=inspect_screen) as fallback:
            screen=inspect_forge_screen(source)
            self.assertEqual(screen.page,'inventory_organize')
            fallback.assert_called_once_with(source)

    def test_real_zero_selection_without_full_page_detection(self):
        from e7_assistant.workflow_screen import inspect_screen
        screen=inspect_screen(ASSETS/'cleanup-zero-selection.png')
        inventory=inspect_inventory(screen)
        self.assertEqual(inventory.selected,0)
        self.assertEqual(inventory.count,1203)

    def test_navigation_crops_find_buttons_and_count_without_equipment_ocr(self):
        from e7_assistant.workflow_screen import inspect_navigation_screen
        screen=inspect_navigation_screen(ASSETS/'cleanup-zero-selection.png',{'inventory_organize'})
        self.assertEqual(screen.page,'inventory_organize')
        self.assertTrue(screen.find('快速选择',(130,75,280,135)))
        self.assertFalse(any(150<w['center'][0]<830 and 300<w['center'][1]<490 for w in screen.words))

    def test_extract_preview_header_animation_does_not_change_product_digest(self):
        from e7_assistant.initial_cleanup import inspect_confirmation
        from e7_assistant.workflow_screen import inspect_screen
        sources=[ASSETS/name for name in ('extract-preview-before.png','extract-preview-after.png')]
        confirmations=[inspect_confirmation(inspect_screen(source),'extract') for source in sources]
        self.assertEqual(confirmations[0].digest,confirmations[1].digest)
