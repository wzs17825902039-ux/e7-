from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from e7_assistant.adb import Adb
from e7_assistant.tasks import TaskControl,Cancelled


class ScreenshotRetryTests(unittest.TestCase):
    @patch('e7_assistant.adb.time.sleep')
    def test_png_with_internal_corruption_is_rejected_and_reread(self,wait):
        with tempfile.TemporaryDirectory() as folder:
            adb=Adb(serial='test');png=self.png(folder)
            damaged=bytearray(png);damaged[45]^=1
            with patch.object(adb,'_run',side_effect=[bytes(damaged),png]):
                report=adb.screenshot(str(Path(folder)/'result.png'))
            self.assertEqual(report['attempts'],2)
            self.assertEqual(Path(report['path']).read_bytes(),png)

    @patch('e7_assistant.adb.time.sleep')
    def test_persistent_truncated_png_has_bounded_reads_and_no_output_file(self,wait):
        with tempfile.TemporaryDirectory() as folder:
            adb=Adb(serial='test');target=Path(folder)/'result.png'
            with patch.object(adb,'_run',return_value=self.png(folder)[:40]) as run:
                with self.assertRaises(RuntimeError):adb.screenshot(str(target))
            self.assertEqual(run.call_count,3)
            self.assertFalse(target.exists())

    @patch('e7_assistant.adb.time.sleep')
    def test_truncated_screenshot_is_reread_before_any_file_is_written(self,wait):
        with tempfile.TemporaryDirectory() as folder:
            adb=Adb(serial='test');png=self.png(folder)
            with patch.object(adb,'_run',side_effect=[png[:40],png]) as run:
                report=adb.screenshot(str(Path(folder)/'result.png'))
            self.assertEqual(report['attempts'],2)
            self.assertEqual(Path(report['path']).read_bytes(),png)
            self.assertEqual(run.call_count,2)

    @patch('e7_assistant.adb.time.sleep')
    def test_screenshot_timeout_is_read_only_and_can_recover(self,wait):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            adb=Adb(serial='test')
            with patch.object(adb,'_run',side_effect=[subprocess.TimeoutExpired('screencap',20),self.png(folder)]) as run:
                report=adb.screenshot(str(Path(folder)/'result.png'))
            self.assertEqual(report['attempts'],2)
            self.assertTrue(all(call.args[0]==['exec-out','screencap','-p'] for call in run.call_args_list))

    def png(self,folder):
        path=Path(folder)/'source.png'
        Image.new('RGB',(1280,720)).save(path)
        return path.read_bytes()

    @patch('e7_assistant.adb.time.sleep')
    def test_transport_failure_retries_only_screenshot(self,wait):
        with tempfile.TemporaryDirectory() as folder:
            adb=Adb(serial='test')
            with patch.object(adb,'_run',side_effect=[RuntimeError('cannot connect to daemon'),self.png(folder)]) as run:
                report=adb.screenshot(str(Path(folder)/'result.png'))
            self.assertEqual(report['attempts'],2)
            self.assertTrue(Path(report['path']).is_file())
            self.assertEqual(run.call_count,2)
            self.assertTrue(all(call.args==(['exec-out','screencap','-p'],) and call.kwargs=={'device':True}
                                for call in run.call_args_list))

    @patch('e7_assistant.adb.time.sleep')
    def test_persistent_failure_stops_without_writing(self,wait):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'result.png';adb=Adb(serial='test')
            with patch.object(adb,'_run',side_effect=RuntimeError('could not read ok from ADB Server')) as run:
                with self.assertRaises(RuntimeError):adb.screenshot(str(target))
            self.assertEqual(run.call_count,3)
            self.assertFalse(target.exists())

    def test_device_error_and_invalid_png_do_not_retry(self):
        for value in (RuntimeError('device unauthorized'),b'not a PNG'):
            with tempfile.TemporaryDirectory() as folder:
                adb=Adb(serial='test')
                with patch.object(adb,'_run',side_effect=[value]) as run:
                    with self.assertRaises(RuntimeError):adb.screenshot(str(Path(folder)/'result.png'))
                self.assertEqual(run.call_count,1)

    def test_stop_during_wait_prevents_another_read(self):
        control=TaskControl();control.wait=lambda seconds:control.stop()
        adb=Adb(serial='test',control=control)
        with patch.object(adb,'_run',side_effect=RuntimeError('cannot connect to daemon')) as run:
            with self.assertRaises(Cancelled):adb.screenshot('unused.png')
        self.assertEqual(run.call_count,1)

    def test_tap_transport_failure_is_never_repeated(self):
        adb=Adb(serial='test')
        with patch.object(adb,'_run',side_effect=RuntimeError('cannot connect to daemon')) as run:
            with self.assertRaises(RuntimeError):adb.tap(100,100)
        self.assertEqual(run.call_count,1)
