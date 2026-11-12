from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from e7_assistant.disposal_guard import DisposalGuard


class DisposalGuardTests(unittest.TestCase):
    def test_record_survives_writer_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c',
                            'import sys; from e7_assistant.disposal_guard import DisposalGuard; '
                            'DisposalGuard(sys.argv[1], "test-device").begin("sell", '
                            '{"count": 10}, {"digest": "preview"}, "old-run")', directory],
                           cwd=Path(__file__).resolve().parents[1], check=True,
                           capture_output=True, timeout=15)
            guard = DisposalGuard(directory, 'test-device')
            self.assertEqual(guard.read()['before']['count'], 10)
            with self.assertRaisesRegex(ValueError, '未结算'):
                guard.check_clear()

    def test_exclusive_claim_and_matching_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DisposalGuard(directory, '127.0.0.1:16384')
            other = DisposalGuard(directory, '127.0.0.1:16384')
            token = first.begin('sell', {'count':10}, {'digest':'preview'}, 'run')
            with self.assertRaises(ValueError):
                other.begin('extract', {}, {}, 'new-run')
            with self.assertRaises(ValueError):
                other.settle('wrong-token')
            self.assertEqual(first.read()['operation_id'], token)
            other.settle(token)
            self.assertIsNone(first.read())

    def test_device_scope_isolated_and_invalid_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DisposalGuard(directory, 'device-a')
            other = DisposalGuard(directory, 'device-b')
            first.begin('extract', {}, {}, 'run')
            other.check_clear()
            first.path.write_text('[]', encoding='utf-8')
            with self.assertRaises(ValueError):
                first.check_clear()
            self.assertTrue(first.path.exists())
        with self.assertRaises(ValueError):
            DisposalGuard(Path('.'), '')
