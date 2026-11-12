from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from e7_assistant.settings import Settings, load_settings, save_settings
from e7_assistant.tasks import Limits


class SettingsTests(unittest.TestCase):
    def test_roundtrip_does_not_persist_running_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui.json"
            settings = Settings(adb_path="test.exe", serial="127.0.0.1:12345")
            save_settings(path, settings)
            loaded = load_settings(path)
            self.assertEqual(asdict(loaded), asdict(settings))
            self.assertNotIn("running", path.read_text())

    def test_invalid_limits_rejected_before_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui.json"
            bad = Settings(limits={**asdict(Limits()), "gold": -1})
            with self.assertRaises(ValueError):
                save_settings(path, bad)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
