import threading
import time
import unittest
from unittest.mock import patch

from e7_assistant.adb import Adb
from e7_assistant.tasks import Cancelled, TaskControl


class InputSpeed(unittest.TestCase):
    def test_stop_interrupts_throttled_input_without_sending_second_tap(self):
        control = TaskControl(action_interval=1)
        adb = Adb(serial='test', control=control)
        with patch.object(adb, '_run', return_value=b'') as command:
            adb.tap(100,100)
            timer = threading.Timer(.03,control.stop)
            timer.start()
            started = time.monotonic()
            try:
                with self.assertRaises(Cancelled):
                    adb.tap(200,200)
            finally:
                timer.join()
            self.assertLess(time.monotonic()-started,.8)
            self.assertEqual(command.call_count,1)

    def test_interval_boundaries(self):
        for value in (-1,6,True,float('nan'),float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TaskControl(value)
