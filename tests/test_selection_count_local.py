from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.inventory_vision import inspect_inventory,InventoryObservationIncomplete
from e7_assistant.workflow_screen import inspect_screen

ASSET=Path(__file__).resolve().parents[1]/'docs/assets/batch-selection-2026-11-10/14-persistent-low-count.png'


class LocalCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.screen=inspect_screen(ASSET)

    def test_real_local_two_crops_confirm_fourteen(self):
        report=inspect_inventory(self.screen)
        self.assertEqual(report['selected_count'],14)
        self.assertEqual(sum(c['selected'] is True for c in report['cards']),14)
        self.assertTrue(report['count_evidence']['accepted'])

    def test_local_conflict_or_unknown_does_not_use_global_low_count(self):
        for text,accepted,exc in (('批量强化(15)',True,ValueError),('',False,InventoryObservationIncomplete)):
            values={key:text for key in ('count_outer','count_inner')}
            details={key:{'text':text,'accepted':accepted,'confidence':.99 if accepted else 0,
                          'candidates':[]} for key in values}
            with self.subTest(text=text),patch('e7_assistant.local_ocr.read_local_regions',return_value=(values,details)):
                with self.assertRaises(exc):inspect_inventory(self.screen)


if __name__=='__main__':unittest.main()
