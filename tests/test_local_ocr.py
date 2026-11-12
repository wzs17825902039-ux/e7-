import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from e7_assistant.local_ocr import _value_text


class ValueParsing(unittest.TestCase):
    def test_badge_optional_plus_is_equivalent_without_changing_other_fields(self):
        self.assertEqual(_value_text('+4','badge14'),'4')
        self.assertEqual(_value_text('4','badge14'),'4')
        self.assertEqual(_value_text('+14','badge14'),'14')
        self.assertEqual(_value_text('+10 ','badge7'),'10')
        self.assertEqual(_value_text('+4','stat0_0'),'+4')
        self.assertEqual(_value_text('4?','badge14'),'4?')

    def test_growth_is_separate_from_current_stat(self):
        self.assertEqual(_value_text('12%(+7%)(1)', 'stat0_0'), '12%')
        self.assertEqual(_value_text('7(+4)(1)', 'stat0_1'), '7')
        self.assertEqual(_value_text('70%', 'stat0_1'), '70%')
        self.assertEqual(_value_text('B%', 'stat0_1'), 'B%')
        self.assertEqual(_value_text('1885(+1345)', 'main0'), '1885')
        self.assertEqual(_value_text('1,188', 'main0'), '1188')
        self.assertEqual(_value_text('11,88', 'main0'), '11,88')


@unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('PIL'),
                     '本地OCR需要numpy及Pillow')
class RecognitionConsensus(unittest.TestCase):
    def test_preprocessing_does_not_enable_contrast_for_next_region(self):
        import numpy as np
        from PIL import Image,ImageDraw
        from e7_assistant.local_ocr import read_local_regions
        calls = []
        def engine(pixels,**kwargs):
            calls.append(pixels.copy())
            return [['100',.99]],None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'regions.png'
            image = Image.new('RGB',(40,24),(20,20,20))
            ImageDraw.Draw(image).rectangle((10,6,29,17),fill=(200,200,200))
            image.save(path)
            with patch('e7_assistant.local_ocr._engine',return_value=engine):
                read_local_regions(path,{'first':(0,0,40,24),'second':(0,0,40,24)})
        raw = [array for array in calls if array.shape==(24,40,3)]
        self.assertEqual(len(raw),2)
        self.assertTrue(all(int(array.min())==20 and int(array.max())==200 for array in raw))

    def read(self, predictions, detections=None):
        from PIL import Image
        from e7_assistant.local_ocr import read_local_regions
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.png'
            Image.new('RGB', (40, 24), 'white').save(path)
            engine = lambda *args, **kwargs: ([predictions.pop(0)], None)
            with patch('e7_assistant.local_ocr._engine', return_value=engine):
                return read_local_regions(path, {'stat0_0': (0, 0, 40, 24)}, detections=detections)

    def test_high_confidence_disagreement_is_rejected(self):
        values, details = self.read([['8%', .99], ['3%', .98], ['3%', .99], ['3%', .99]])
        self.assertEqual(values['stat0_0'], '')
        self.assertFalse(details['stat0_0']['accepted'])

    def test_agreed_stat_with_growth_is_accepted(self):
        values, _ = self.read([['12%(+7%)(1)', .99], ['12%', .98], ['12%', .99], ['12%', .99]])
        self.assertEqual(values['stat0_0'], '12%')

    def test_original_context_and_guided_crop_override_transform_artifacts(self):
        box = [[0,0],[40,0],[40,24],[0,24]]
        values, _ = self.read([['7%',.99],['70%',.99],['70%',.99],['70%',.99],['7%',.99]],
                              [(box,'7%',.99)])
        self.assertEqual(values['stat0_0'],'7%')

    def test_weak_context_cannot_resolve_high_confidence_disagreement(self):
        box = [[0,0],[40,0],[40,24],[0,24]]
        values, _ = self.read([['7%',.99],['70%',.99],['70%',.99],['70%',.99],['7%',.99]],
                              [(box,'7%',.7)])
        self.assertEqual(values['stat0_0'],'')
