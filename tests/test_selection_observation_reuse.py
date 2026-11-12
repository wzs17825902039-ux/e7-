from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from e7_assistant.batch_selection import BatchSelectionDriver


class SelectionObservationReuseTests(unittest.TestCase):
    def driver(self):
        driver=BatchSelectionDriver.__new__(BatchSelectionDriver)
        driver.defer_details=True
        driver._observed_at=10
        driver.screen=SimpleNamespace(source='fresh.png')
        driver.navigator=SimpleNamespace(journal=SimpleNamespace(emit=Mock()))
        driver.observe_unchanged=Mock(return_value={'source':'reread.png'})
        return driver

    def test_only_recent_matching_native_selection_snapshot_is_reused(self):
        driver=self.driver()
        report={'source':'fresh.png','selected_count':2}
        with patch('e7_assistant.batch_selection.time.monotonic',return_value=10.5):
            self.assertIs(driver.selection_reference(report),report)
        driver.observe_unchanged.assert_not_called()

    def test_expired_replaced_future_or_strict_snapshot_is_reread(self):
        for case in ('expired','replaced','future','strict','missing_time'):
            driver=self.driver()
            report={'source':'fresh.png','selected_count':2}
            if case=='replaced':driver.screen.source='other.png'
            if case=='strict':driver.defer_details=False
            if case=='missing_time':del driver._observed_at
            now=12 if case=='expired' else 9 if case=='future' else 10.5
            with self.subTest(case=case),patch('e7_assistant.batch_selection.time.monotonic',return_value=now):
                self.assertEqual(driver.selection_reference(report),{'source':'reread.png'})
            driver.observe_unchanged.assert_called_once_with(report,allow_expansion=True)
