from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_vision import inspect_inventory,InventoryObservationIncomplete
from e7_assistant.workflow_screen import inspect_screen


class CountRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assets=Path(__file__).resolve().parents[1]/'docs/assets/batch-selection-2026-11-10'
        cls.animation=inspect_screen(assets/'14-animation.png')
        cls.before,cls.after=[inspect_inventory(inspect_screen(assets/name))
            for name in ('14-before.png','14-settled.png')]

    def driver(self):
        nav=SimpleNamespace(control=SimpleNamespace(wait=lambda seconds:None),journal=None)
        return BatchSelectionDriver(nav)

    def test_real_low_count_frame_not_accepted_and_next_frame_verified(self):
        # 全图低置信度只能由两处局部读取恢复；动画图像身份仍不得跳过。
        animation=inspect_inventory(self.animation)
        self.assertEqual(animation['selected_count'],14)
        self.assertTrue(animation['count_evidence']['accepted'])
        with self.assertRaises(ValueError):
            BatchSelectionDriver._verify_click(self.before,animation,(2,0))
        self.assertEqual(self.after['selected_count'],14)
        driver=self.driver()
        with patch.object(driver,'observe',side_effect=[InventoryObservationIncomplete(),self.after]) as read:
            self.assertIs(driver._observe_click(self.before,(2,0)),self.after)
        self.assertEqual(read.call_count,2)

    def test_unstable_count_only_allows_four_reads(self):
        driver=self.driver()
        with patch.object(driver,'observe',side_effect=InventoryObservationIncomplete()) as read:
            with self.assertRaises(InventoryObservationIncomplete):
                driver._observe_click(self.before,(2,0))
        self.assertEqual(read.call_count,4)

    def test_confirmed_wrong_count_cannot_be_hidden_by_retry(self):
        driver=self.driver()
        wrong={**self.after,'selected_count':15}
        with patch.object(driver,'observe',return_value=wrong) as read:
            with self.assertRaises(ValueError):driver._observe_click(self.before,(2,0))
        self.assertEqual(read.call_count,1)


if __name__=='__main__':unittest.main()
