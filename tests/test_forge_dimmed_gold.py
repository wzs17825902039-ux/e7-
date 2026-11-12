from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from e7_assistant.forge_loop import number, _dimmed_number
from e7_assistant.workflow_screen import inspect_screen


IMAGE = Path(__file__).resolve().parents[1] / 'docs/assets/sale-preview-2026-11-10/craft-result-dimmed-gold.png'


class DimmedForgeGoldTests(unittest.TestCase):
    def test_real_result_with_animation_sparkle_reads_full_balance(self):
        screen = inspect_screen(IMAGE)
        self.assertEqual(screen.page, 'craft_result')
        self.assertEqual(number(screen, 'gold', (665, 15, 805, 55), contrast=True), '334,739,059')

    def test_conflicting_full_patch_is_rejected(self):
        values = [('334,739,058', .99)] + [('334,739,059', .99)] * 3
        with patch('e7_assistant.local_ocr._engine') as engine:
            engine.return_value.side_effect = [([[text, confidence]], None) for text, confidence in values]
            with self.assertRaises(ValueError):
                _dimmed_number(IMAGE, (665, 15, 805, 55), r'[0-9,]+')

    def test_transformed_disagreement_or_low_confidence_rejected(self):
        for rival in [('334,739,058', .99), ('334,739,059', .94)]:
            with self.subTest(rival=rival), patch('e7_assistant.local_ocr._engine') as engine:
                values = [('', 0), ('334,739,059', .99), rival, ('334,739,059', .99)]
                engine.return_value.side_effect = [([[text, confidence]], None) for text, confidence in values]
                with self.assertRaises(ValueError):
                    _dimmed_number(IMAGE, (665, 15, 805, 55), r'[0-9,]+')

    def test_whole_page_conflict_blocks_recovery(self):
        screen = SimpleNamespace(source=str(IMAGE), words=[{'text': '334,739,058',
                                 'confidence': .99, 'center': (700, 30)}])
        with patch('e7_assistant.forge_loop.read_local_regions', return_value=({'gold': ''}, {})), \
             patch('e7_assistant.forge_loop._dimmed_number', return_value='334,739,059'):
            with self.assertRaises(ValueError):
                number(screen, 'gold', (665, 15, 805, 55), contrast=True)


if __name__ == '__main__':
    unittest.main()
