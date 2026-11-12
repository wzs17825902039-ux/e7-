from pathlib import Path
import unittest
from PIL import Image,ImageEnhance
from e7_assistant.batch_badge_vision import read_numbered_badge
from e7_assistant.batch_vision import inspect_batch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/selected-inventory-resume-a2aeb4d5/workflow-0014.png'


class BadgeGlyphTests(unittest.TestCase):
    def test_touching_plus_and_six_need_confirmed_plus_and_four_agreeing_digit_reads(self):
        source=ROOT/'runs/full-workflow-04553449/workflow-0061.png'
        with Image.open(source) as image:
            crop=image.convert('RGB').resize((1661,933)).crop((733,503,773,530))
        result=read_numbered_badge(crop)
        self.assertEqual(result['value'],6)
        self.assertEqual(result['source'],'orange_plate_split_digits')
        self.assertEqual(len(result['candidates']),4)
        self.assertTrue(all(c['confidence']>=.95 for c in result['candidates']))
        from e7_assistant.batch_badge_vision import _read_split_digits
        import numpy as np
        pixels=np.asarray(crop,dtype=float)
        white=(pixels.min(2)>.78*pixels.max(2))&(pixels.min(2)>150)
        white[:,:20]=False
        self.assertIsNone(_read_split_digits(white))

    def test_actual_unread_three_and_four_have_independent_glyph_evidence(self):
        with Image.open(SOURCE) as image:
            reference=image.convert('RGB').resize((1661,933))
        for index,value in ((6,3),(9,3),(10,3),(14,4)):
            dx,dy=round(index%4*316.667),round(index//4*167.333)
            patch=reference.crop((100+dx,168+dy,140+dx,195+dy))
            for gain in (.5,1):
                with self.subTest(index=index,gain=gain):
                    result=read_numbered_badge(ImageEnhance.Brightness(patch).enhance(gain))
                    self.assertIsNotNone(result)
                    self.assertEqual(result['value'],value)
                    self.assertEqual(len(result['candidates']),2)

    def test_blank_and_unenhanced_art_never_yield_a_number(self):
        for path in (ROOT/'e7_assistant/assets/batch-slots').glob('no-enhancement-badge*.png'):
            with Image.open(path) as image,self.subTest(source=path.name):
                self.assertIsNone(read_numbered_badge(image))
        for color in ('black','white','gray','orange'):
            self.assertIsNone(read_numbered_badge(Image.new('RGB',(40,27),color)))

    def test_real_result_recovers_four_without_repeating_confirmation(self):
        report=inspect_batch(SOURCE,{i:'weapon' for i in range(16)},ignore_levels=True,
                             require_score=False,ignore_purple_main=True)
        self.assertEqual(report['issues'],[])
        actual=[r['equipment']['enhancement'] for r in report['records']]
        self.assertEqual(actual,[0,0,0,0,0,0,3,0,0,3,3,0,0,0,4,0])
        self.assertEqual(report['ocr_details']['badge14']['source'],'orange_plate_white_glyph')
