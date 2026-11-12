import unittest
from unittest.mock import Mock,patch
from e7_assistant.desktop_instance import DesktopInstance,TITLE


class DesktopInstanceTests(unittest.TestCase):
    def instance(self,window=0,error=0,handle=123):
        kernel,user=Mock(),Mock()
        user.FindWindowW.return_value=window
        kernel.CreateMutexW.return_value=handle
        return DesktopInstance(kernel,user,lambda:error)

    def test_existing_legacy_window_is_reused_without_creating_another(self):
        instance=self.instance(window=55)
        self.assertFalse(instance.acquire())
        instance.user.FindWindowW.assert_called_once_with(None,TITLE)
        instance.user.SetForegroundWindow.assert_called_once_with(55)
        instance.kernel.CreateMutexW.assert_not_called()

    def test_simultaneous_launch_race_does_not_create_second_window(self):
        instance=self.instance(error=183)
        self.assertFalse(instance.acquire())
        instance.kernel.CloseHandle.assert_called_once_with(123)
        self.assertIsNone(instance.handle)

    def test_normal_lifetime_closes_only_its_own_handle_once(self):
        instance=self.instance()
        self.assertTrue(instance.acquire())
        instance.close();instance.close()
        instance.kernel.CloseHandle.assert_called_once_with(123)

    def test_mutex_failure_is_visible_and_not_treated_as_success(self):
        instance=self.instance(error=5,handle=0)
        with self.assertRaises(OSError):instance.acquire()
        instance.kernel.CloseHandle.assert_not_called()

    def test_duplicate_default_launch_never_creates_a_window_or_initializes_a_task(self):
        from e7_assistant.desktop import launch
        instance=Mock();instance.acquire.return_value=False
        webview=Mock()
        with patch.dict('sys.modules',{'webview':webview}),\
             patch('e7_assistant.desktop_instance.desktop_instance',return_value=instance),\
             patch('e7_assistant.desktop.DesktopApi') as api:
            self.assertEqual(launch(),0)
        webview.create_window.assert_not_called()
        api.assert_not_called()

    def test_duplicate_acceptance_launch_does_not_test_an_existing_old_version(self):
        from e7_assistant.desktop import launch
        instance=Mock();instance.acquire.return_value=False
        with patch.dict('sys.modules',{'webview':Mock()}),\
             patch('e7_assistant.desktop_instance.desktop_instance',return_value=instance),\
             patch('e7_assistant.desktop._launch') as inner:
            with self.assertRaises(RuntimeError):launch(on_loaded=Mock())
        inner.assert_not_called()

    def test_failed_startup_releases_instance_marker(self):
        from e7_assistant.desktop import launch
        instance=Mock();instance.acquire.return_value=True
        with patch.dict('sys.modules',{'webview':Mock()}),\
             patch('e7_assistant.desktop_instance.desktop_instance',return_value=instance),\
             patch('e7_assistant.desktop._launch',side_effect=RuntimeError('missing assets')):
            with self.assertRaises(RuntimeError):launch()
        instance.close.assert_called_once()


if __name__=='__main__':unittest.main()
