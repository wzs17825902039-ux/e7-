import importlib.util
from pathlib import Path
import unittest


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('PIL', 'cv2', 'numpy')),
                     '需要vision依赖')
class DetailLockVisionTests(unittest.TestCase):
    def test_real_existing_lock_and_open_button(self):
        from PIL import Image
        from e7_assistant.lock_vision import inspect_detail_lock
        root = Path(__file__).resolve().parents[1] / 'runs/lock-sample-navigation-f2ca1447'
        for number, expected in [('0004', False), ('0013', True), ('0017', True)]:
            with Image.open(root / ('workflow-' + number + '.png')) as image:
                self.assertIs(inspect_detail_lock(image, 'inventory')['locked'], expected)

    def test_blank_wrong_page_and_wrong_size_are_unknown(self):
        from PIL import Image
        from e7_assistant.lock_vision import inspect_detail_lock
        for color in ('white', 'black', '#808080'):
            self.assertIsNone(inspect_detail_lock(Image.new('RGB', (1280, 720), color), 'inventory')['locked'])
        with Image.open(Path(__file__).resolve().parents[1] / 'e7_assistant/assets/locks/locked.png') as image:
            self.assertIsNone(inspect_detail_lock(image, 'inventory')['locked'])
        self.assertIsNone(inspect_detail_lock(Image.new('RGB', (1280, 720)), 'batch_enhancement')['locked'])
