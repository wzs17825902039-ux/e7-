from pathlib import Path
import unittest

from e7_assistant.inventory_vision import inspect_inventory, InventoryObservationIncomplete
from e7_assistant.workflow_screen import inspect_screen


class MiddleAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/61-middle-anchor-only.png'
        cls.screen=inspect_screen(source)

    def test_actual_middle_only_anchor_recovers_all_three_rows_by_local_ocr(self):
        report=inspect_inventory(self.screen)
        self.assertEqual(len(report['cards']),21)
        self.assertEqual([c['row'] for c in report['cards']],[0]*7+[1]*7+[2]*7)
        self.assertTrue(all(c['level']==85 for c in report['cards']))

    def test_missing_local_top_level_never_becomes_an_implicit_row(self):
        calls=[]
        def reader(path,boxes):
            calls.extend(boxes)
            return {key:('' if key.endswith('_3') else '85') for key in boxes}
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(self.screen,reader)
        self.assertEqual(len(calls),7)
        self.assertTrue(all(key.startswith('level_leading_anchor') for key in calls))


if __name__=='__main__':
    unittest.main()
