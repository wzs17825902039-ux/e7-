from pathlib import Path
import tempfile
import unittest

from PIL import Image
import numpy as np

from e7_assistant.inventory_vision import inspect_inventory, _level_region
from e7_assistant.workflow_screen import Screen


def sample_screen(source):
    words = [{'text':'批量强化(16)', 'confidence':1., 'center':(1114,674)}]
    for y in (220,393,566):
        for x in (213,341.5):
            words.append({'text':'85', 'confidence':1., 'center':(x*1280/1661,y*720/933)})
    words.append({'text':'+3', 'confidence':1., 'center':(616.88,428.3)})
    return Screen(str(source), 'inventory_batch_selection', 1661, 933, tuple(words))


class InventoryVisionTests(unittest.TestCase):
    def setUp(self):
        self.source = Path(__file__).resolve().parents[1] / 'docs/assets/user-workflow-2026-11-09/15-select-unenhanced.png'

    @staticmethod
    def levels(path, boxes):
        # 测试图形部分；实际数字模型另由截图验证脚本覆盖。
        return {key:'85' for key in boxes}

    def test_real_tick_and_enhancement_badge(self):
        report = inspect_inventory(sample_screen(self.source), self.levels)
        self.assertEqual(len(report['cards']),21)
        self.assertEqual([c['selected'] for c in report['cards']], [True]*16+[False]*5)
        self.assertEqual(report['cards'][18]['enhancement'],3)
        self.assertTrue(report['cards'][18]['eligible'])
        self.assertTrue(report['cards'][19]['eligible'])
        self.assertFalse(report['scan_complete'])

    def test_numeric_failure_does_not_become_zero_level(self):
        report = inspect_inventory(sample_screen(self.source), lambda path,boxes: {})
        self.assertTrue(all(c['level'] is None and not c['eligible'] for c in report['cards']))

    def test_non_85_level_is_not_coerced_to_85(self):
        baseline=inspect_inventory(sample_screen(self.source),self.levels)
        for text in ('88','90'):
            with self.subTest(level=text):
                original=sample_screen(self.source)
                screen=Screen(original.source,original.page,original.width,original.height,
                              tuple({**w,'text':text} if w['text']=='85' else w for w in original.words))
                report=inspect_inventory(screen,lambda path,boxes:{key:text for key in boxes})
                self.assertEqual(len(report['cards']),21)
                self.assertTrue(all(c['level']==int(text) and not c['eligible']
                                    for c in report['cards']))
                self.assertEqual([c['known'] for c in report['cards']],
                                 [c['known'] for c in baseline['cards']])

    def test_unverified_single_digit_is_not_a_supported_level(self):
        report=inspect_inventory(sample_screen(self.source),lambda path,boxes:{key:'5' for key in boxes})
        self.assertTrue(all(c['level'] is None and not c['known'] and not c['eligible']
                            for c in report['cards']))

    def test_orange_badge_without_readable_number_stays_unknown(self):
        screen = sample_screen(self.source)
        screen = Screen(screen.source,screen.page,screen.width,screen.height,
                        tuple(w for w in screen.words if w['text'] != '+3'))
        report = inspect_inventory(screen,self.levels,read_badges=lambda path,regions:{})
        self.assertIsNone(report['cards'][18]['enhancement'])
        self.assertFalse(report['cards'][18]['eligible'])

    def test_orange_badge_can_use_local_number_but_never_become_plus_zero(self):
        screen=sample_screen(self.source)
        screen=Screen(screen.source,screen.page,screen.width,screen.height,
                      tuple(w for w in screen.words if w['text']!='+3'))
        for value,expected in [('+3',3),('3',3),('15',15),('0',None),('16',None),('',None)]:
            with self.subTest(value=value):
                report=inspect_inventory(screen,self.levels,
                    read_badges=lambda path,regions:{key:value for key in regions})
                self.assertEqual(report['cards'][18]['enhancement'],expected)
                self.assertEqual(report['cards'][18]['eligible'], expected is not None and expected < 15)

    def test_blank_frame_with_stale_ocr_anchors_cannot_select(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'blank.png'
            Image.new('RGB',(1661,933),'black').save(source)
            report = inspect_inventory(sample_screen(source),self.levels)
        self.assertTrue(all(not c['eligible'] for c in report['cards']))

    def test_no_row_anchors_is_not_empty_inventory(self):
        screen = sample_screen(self.source)
        screen = Screen(screen.source,screen.page,screen.width,screen.height,(screen.words[0],))
        with self.assertRaises(ValueError):
            inspect_inventory(screen,self.levels)

    def test_level_mask_removes_separate_speck_but_preserves_thin_digit(self):
        pixels = np.zeros((40, 40, 3), dtype=float)
        pixels[7:19, 10:12] = (220, 180, 30)  # 细长数字笔画
        pixels[17:19, 25:28] = (220, 180, 30)  # 独立金色装饰
        crop, mask, removed = _level_region(pixels, (0, 0, 30, 25), 1, 1)
        self.assertEqual(int((mask == 255).sum()), 24)
        self.assertTrue(np.all(mask[2:14, 4:6] == 255))
        self.assertEqual([r['area'] for r in removed], [6])

    def test_level_mask_blank_remains_blank_and_invalid_crop_is_rejected(self):
        pixels = np.zeros((40, 40, 3), dtype=float)
        _, mask, removed = _level_region(pixels, (0, 0, 30, 25), 1, 1)
        self.assertFalse(np.any(mask == 255))
        self.assertEqual(removed, [])
        with self.assertRaises(ValueError):
            _level_region(pixels, (0, 0, 5, 5), 1, 1)
