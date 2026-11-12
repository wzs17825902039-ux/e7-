from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from PIL import Image,ImageDraw
from e7_assistant.inventory_sort import ascending_selected,ensure_ascending
from e7_assistant.workflow_screen import inspect_screen


class InventorySortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.open=inspect_screen(cls.root/'docs/assets/inventory-traversal-2026-11-10/87-sort-max-ascending.png')
        cls.before=inspect_screen(cls.root/'docs/assets/inventory-traversal-2026-11-10/88-sort-before-open.png')

    def test_actual_up_arrow_is_recognized_and_missing_graphic_is_rejected(self):
        self.assertTrue(ascending_selected(self.open.source))
        with TemporaryDirectory() as folder,Image.open(self.open.source) as image:
            ImageDraw.Draw(image).rectangle((914,157,978,191),fill='black')
            path=Path(folder)/'missing.png';image.save(path)
            self.assertFalse(ascending_selected(path))

    def test_already_ascending_only_opens_and_closes_sort(self):
        nav=SimpleNamespace(read=Mock(side_effect=(self.before,self.open,self.before)),
                            adb=SimpleNamespace(tap=Mock()),control=SimpleNamespace(wait=Mock()),journal=None)
        ensure_ascending(nav)
        self.assertEqual(nav.adb.tap.call_count,2)
        self.assertEqual(nav.adb.tap.call_args_list[-1].args,(1045,110))

    def test_low_confidence_button_text_still_verifies_sort_menu_and_arrow(self):
        before=replace(self.before,words=tuple({**word,'text':'Y最大强化','confidence':.8967}
            if 845<=word['center'][0]<985 and 80<=word['center'][1]<130 else word
            for word in self.before.words))
        nav=SimpleNamespace(read=Mock(side_effect=(before,self.open,self.before)),
                            adb=SimpleNamespace(tap=Mock()),control=SimpleNamespace(wait=Mock()),journal=None)
        ensure_ascending(nav)
        self.assertEqual([call.args for call in nav.adb.tap.call_args_list],[(950,107),(1045,110)])

    def test_missing_menu_labels_stops_without_guessing_arrow(self):
        nav=SimpleNamespace(read=Mock(side_effect=(self.before,*([replace(self.open,words=())]*3))),
                            adb=SimpleNamespace(tap=Mock()),control=SimpleNamespace(wait=Mock()),journal=None)
        with self.assertRaises(ValueError):ensure_ascending(nav)
        self.assertEqual(nav.adb.tap.call_count,1)

    def test_open_animation_retries_only_reading(self):
        nav=SimpleNamespace(read=Mock(side_effect=(self.before,self.before,self.open,self.before)),
                            adb=SimpleNamespace(tap=Mock()),control=SimpleNamespace(wait=Mock()),journal=None)
        ensure_ascending(nav)
        self.assertEqual(nav.adb.tap.call_count,2)
