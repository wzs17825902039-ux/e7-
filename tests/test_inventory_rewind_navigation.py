from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.inventory_vision import inventory_context
from tests.test_inventory_scan import report


class RewindNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/66-rewind-two-full-rows.png'
        cls.partial = inspect_screen(path)

    def harness(self, stable=None):
        screen = self.partial
        context = inventory_context(screen)
        current = report([0, 1, 2])
        current.update(source=screen.source, inventory_context=context)
        final = report([0, 1, 2])
        final.update(source=screen.source, inventory_context=context)
        for card in final['cards']:
            card['center'] = (card['center'][0], card['center'][1]+11)
        navigator = SimpleNamespace(read=Mock(side_effect=[screen, stable or screen, screen, screen]),
                                    control=SimpleNamespace(checkpoint=lambda: None, wait=lambda _: None),
                                    adb=SimpleNamespace(swipe=Mock()), journal=None)
        heads = iter([False, True])
        top = lambda s: {'head_visible': next(heads), 'source': s.source, 'inventory_context': context}
        reader = Mock(return_value=final)
        return BatchSelectionDriver(navigator, reader=reader, top_reader=top), current, reader

    def test_intermediate_frame_only_checks_navigation_then_top_requires_full_reader(self):
        driver, current, reader = self.harness()
        result, anchor = driver.rewind_to_top(current, 2)
        self.assertEqual(driver.navigator.adb.swipe.call_count, 2)
        self.assertEqual(reader.call_count, 1)
        self.assertTrue(anchor['head_visible'])
        self.assertEqual(len(result['cards']), 21)

    def test_navigation_entry_never_claims_equipment_or_scan_coverage(self):
        from e7_assistant.inventory_scan import InventoryTraversal
        driver, _, reader = self.harness()
        snapshot = driver._begin(16, navigation_only=True)
        self.assertTrue(snapshot['navigation_only'])
        self.assertEqual(snapshot['cards'], [])
        reader.assert_not_called()
        with self.assertRaises(ValueError):
            InventoryTraversal().start(snapshot)

    def test_changed_context_or_nonzero_layout_stops_before_next_swipe(self):
        for mode in ('context', 'page'):
            if mode == 'context':
                words = tuple({**w, 'text': '1048/1200'} if w['text'] == '1049/1200' else w
                              for w in self.partial.words)
                stable = replace(self.partial, words=words)
            else:
                stable = replace(self.partial, page='inventory_batch_selection')
            driver, current, reader = self.harness(stable)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                driver.rewind_to_top(current, 2)
            self.assertEqual(driver.navigator.adb.swipe.call_count, 1)
            reader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
