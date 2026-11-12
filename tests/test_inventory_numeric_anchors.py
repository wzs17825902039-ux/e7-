from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.inventory_vision import inspect_inventory, InventoryObservationIncomplete
from e7_assistant.workflow_screen import inspect_screen


class NumericAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/62-missing-all-level-anchors.png'
        cls.screen = inspect_screen(cls.source)

    def test_real_page_without_level_anchors_still_reads_every_level(self):
        report = inspect_inventory(self.screen)
        self.assertEqual(len(report['cards']), 21)
        self.assertEqual([c['center'][1] for c in report['cards'][::7]], [247, 380, 514])
        self.assertTrue(all(c['level'] == 85 and c['enhancement'] == 0 and c['known']
                            and not c['selected'] for c in report['cards']))

    def test_missing_main_number_requires_all_twenty_one_independent_levels(self):
        for mode in ('missing', 'weak'):
            words = []
            for word in self.screen.words:
                if word['text'] == '540' and 270 < word['center'][1] < 310 and word['center'][0] > 750:
                    if mode == 'missing':
                        continue
                    word = {**word, 'confidence': .94}
                words.append(word)
            observed=replace(self.screen, words=tuple(words))
            with self.subTest(mode=mode):
                report=inspect_inventory(observed)
                self.assertEqual(len(report['cards']),21)
                self.assertTrue(all(c['level']==85 and c['known'] for c in report['cards']))
                with self.assertRaises(InventoryObservationIncomplete):
                    inspect_inventory(observed,read_numbers=lambda path,boxes:
                                      {key:('' if key.endswith('_3') else '85') for key in boxes})

    def test_local_level_failure_does_not_inherit_eighty_five_from_layout(self):
        def rejected(path, boxes):
            return {key: ('' if key.endswith('_3') else '85') for key in boxes}
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(self.screen, read_numbers=rejected)

    def test_partial_rewind_frame_does_not_claim_complete_equipment_observation(self):
        source = self.source.with_name('66-rewind-two-full-rows.png')
        with self.assertRaises(ValueError):
            inspect_inventory(inspect_screen(source))

    def test_low_confidence_mask_requires_independent_color_consensus(self):
        from e7_assistant.inventory_vision import _read_levels
        source = self.source.with_name('63-numeric-anchor-low-confidence-mask.png')
        values, evidence = _read_levels(source, {'level': (644, 198, 671, 222)}, evidence=True)
        self.assertEqual(values['level'], '85')
        self.assertEqual(evidence['level']['recovery'], 'original_color_consensus')
        self.assertFalse(evidence['level']['original']['accepted'])
        report = inspect_inventory(inspect_screen(source))
        self.assertEqual(len(report['cards']), 21)
        self.assertTrue(all(c['level'] == 85 and c['known'] for c in report['cards']))

    def test_color_retry_cannot_overwrite_full_number_conflict_or_crop_disagreement(self):
        from e7_assistant.inventory_vision import _read_levels
        source = self.source.with_name('63-numeric-anchor-low-confidence-mask.png')
        for mode in ('full_conflict', 'different_color_values'):
            calls = []
            def reader(path, boxes):
                values, details = {}, {}
                color = Path(path) == source
                for key in boxes:
                    candidates = [{'text': '85', 'confidence': .85}]
                    if mode == 'full_conflict':
                        candidates.append({'text': '75', 'confidence': .99})
                    if color:
                        calls.append(key)
                        value = '88' if mode == 'different_color_values' and len(calls) == 2 else '85'
                        values[key] = value
                        details[key] = {'text': value, 'confidence': .99, 'accepted': True,
                                        'candidates': [{'text': value, 'confidence': .99}]}
                    else:
                        values[key] = ''
                        details[key] = {'text': '', 'confidence': 0, 'accepted': False, 'candidates': candidates}
                return values, details
            with self.subTest(mode=mode), patch('e7_assistant.local_ocr.read_local_regions', side_effect=reader):
                values = _read_levels(source, {'level': (644, 198, 671, 222)})
                self.assertEqual(values['level'], '')
                self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
