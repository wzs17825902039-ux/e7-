from pathlib import Path
import unittest
from copy import deepcopy

from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.inventory_scan import InventoryTraversal, rows
from e7_assistant.inventory_tracking import inspect_tracking


class ScrollRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        cls.before, cls.after = [inspect_inventory(inspect_screen(folder/name))
                                for name in ('64-tracking-before.png', '65-tracking-after.png')]

    def test_complete_two_row_vertical_registration_recovers_real_scroll(self):
        self.assertFalse(inspect_tracking(rows(self.before)[1][0], rows(self.after)[0][0])['matched'])
        tracker = InventoryTraversal()
        tracker.start(self.before)
        self.assertEqual(tracker.advance(self.before, self.after), 1)
        self.assertEqual(tracker.covered_rows, 4)

    def test_wrong_row_or_one_mismatched_field_cannot_be_registered(self):
        for mode in ('wrong_field', 'wrong_card'):
            after = deepcopy(self.after)
            if mode == 'wrong_field':
                after['cards'][3]['level'] = 90
            else:
                after['cards'][3]['tracking_box'] = after['cards'][4]['tracking_box']
            tracker = InventoryTraversal()
            tracker.start(self.before)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                tracker.advance(self.before, after)
            self.assertEqual(tracker.moves, 0)

    def test_each_complete_row_has_independent_ocr_location_error(self):
        folder = Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before, after = [inspect_inventory(inspect_screen(folder/name)) for name in
                         ('67-row-specific-offset-before.png', '68-row-specific-offset-after.png')]
        tracker = InventoryTraversal()
        tracker.start(before)
        self.assertEqual(tracker.advance(before, after), 1)
        self.assertEqual(tracker.covered_rows, 4)


if __name__ == '__main__':
    unittest.main()
