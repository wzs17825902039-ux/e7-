from pathlib import Path
import unittest
from e7_assistant.workflow_screen import classify,inspect_screen


class SaleLevelWarningTests(unittest.TestCase):
    def test_real_warning_overrides_background_organize_page(self):
        path=Path(__file__).resolve().parents[1]/'docs/assets/sale-level-warning.png'
        screen=inspect_screen(path)
        self.assertEqual(screen.page,'sale_level_warning')
        self.assertGreater(screen.find('确认',(540,490,735,570),.95)['confidence'],.95)

    def test_generic_confirm_does_not_become_level_warning(self):
        words=[{'text':text,'confidence':1,'center':(640,530)}
               for text in ('批量强化','自动选择','出售','确认','取消')]
        self.assertEqual(classify(words),'batch_organize')
