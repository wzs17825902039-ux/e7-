import subprocess
import unittest
from unittest.mock import patch
from e7_assistant.adb import Adb
from e7_assistant.tasks import TaskControl


class PredispatchRetryTests(unittest.TestCase):
    def adb(self):
        control=TaskControl()
        control.wait=lambda _:None
        return Adb('adb','test',control)

    def test_daemon_connection_failure_can_retry_before_shell_dispatch(self):
        error=subprocess.CompletedProcess([],1,b'',b'adb: cannot connect to daemon')
        ok=subprocess.CompletedProcess([],0,b'',b'')
        with patch('e7_assistant.adb.subprocess.run',side_effect=[error,ok]) as run:
            self.adb().tap(10,20)
        self.assertEqual(run.call_count,2)
        self.assertEqual(run.call_args_list[0],run.call_args_list[1])

    def test_offline_shell_error_and_timeout_never_repeat_input(self):
        for error in (b'device offline',b'shell input failed'):
            with self.subTest(error=error),patch('e7_assistant.adb.subprocess.run',
                    return_value=subprocess.CompletedProcess([],1,b'',error)) as run:
                with self.assertRaises(RuntimeError):self.adb().tap(10,20)
                self.assertEqual(run.call_count,1)
        with patch('e7_assistant.adb.subprocess.run',side_effect=subprocess.TimeoutExpired('adb',20)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):self.adb().tap(10,20)
            self.assertEqual(run.call_count,1)
