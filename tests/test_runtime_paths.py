import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from e7_assistant.runtime_paths import default_workspace,resource_root


class RuntimePathTests(unittest.TestCase):
    def test_frozen_data_is_separate_from_extracted_resources(self):
        with patch.object(sys,'frozen',True,create=True),\
             patch.object(sys,'_MEIPASS','C:/temporary/bundle',create=True),\
             patch.dict(os.environ,{'LOCALAPPDATA':'C:/users/example/local'}):
            self.assertEqual(resource_root(),Path('C:/temporary/bundle'))
            self.assertEqual(default_workspace(),Path('C:/users/example/local/E7ForgeAssistant'))
            self.assertNotEqual(default_workspace(),resource_root())

    def test_source_mode_keeps_repository_workspace(self):
        with patch.object(sys,'frozen',False,create=True):
            self.assertEqual(default_workspace(),Path(__file__).resolve().parents[1])
