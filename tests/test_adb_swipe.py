import unittest
from unittest.mock import patch

from e7_assistant.adb import Adb
from e7_assistant.tasks import TaskControl,Cancelled


class SwipeTests(unittest.TestCase):
    def test_bounds_and_duration_are_checked_before_command(self):
        adb=Adb(serial='test')
        with patch.object(adb,'_run') as command:
            for args in [(-1,10,20,30),(0,0,1280,20),(1,1,2,2,99),(1,1,2,2,True)]:
                with self.subTest(args=args),self.assertRaises(ValueError):
                    adb.swipe(*args)
            command.assert_not_called()

    def test_stopped_control_never_sends_swipe(self):
        control=TaskControl();control.stop()
        adb=Adb(serial='test',control=control)
        with patch.object(adb,'_run') as command,self.assertRaises(Cancelled):
            adb.swipe(600,200,600,600)
        command.assert_not_called()
