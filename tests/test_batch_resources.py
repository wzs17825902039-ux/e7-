from dataclasses import replace
import unittest

from e7_assistant.batch_resources import BatchResources, MATERIALS, parse_balance, amount, verify_material_preview, verify_actual_resources
from e7_assistant.rules import Equipment
from e7_assistant.workflow import BatchItem


def resources():
    available = {'gold':10000,**{key:0 for key,_ in MATERIALS}}
    available['powder'] = 100
    reserved = {key:0 for key,_ in MATERIALS}
    before = BatchResources(dict(available),dict(available),dict(reserved),0,None,'before.png')
    remaining = {**available,'powder':98}
    prepared = BatchResources(dict(available),remaining,{**reserved,'powder':2},3200,3,'prepared.png')
    after_available = {**remaining,'gold':6800}
    after = BatchResources(after_available,dict(after_available),dict(reserved),0,None,'after.png')
    return before,prepared,after


def items():
    return [BatchItem('0',Equipment('a','purple',85,0,'helmet',{'speed':3,'crit':5,'atk_pct':7},True,True,25),True)]


class ResourceTests(unittest.TestCase):
    def test_green_remaining_is_not_original_balance(self):
        self.assertEqual(parse_balance('95,834(-862)'),(95834,862))
        self.assertEqual(parse_balance('0'),(0,0))
        self.assertEqual(amount('1,379,200'),1379200)

    def test_bad_format_or_missing_sign_is_not_guessed(self):
        for text in ('','O','95,834(862)','95,834(+862)','95,83(-862)','95,834(-8O2)','-1'):
            with self.subTest(text=text),self.assertRaises(ValueError):
                parse_balance(text)

    def test_preview_and_actual_cost_match(self):
        before,prepared,after = resources()
        cost = verify_material_preview(before,prepared,3,items())
        self.assertEqual(cost['powder'],2)
        self.assertEqual(verify_actual_resources(before,prepared,after),cost)

    def test_resource_change_or_wrong_target_rejected(self):
        before,prepared,_ = resources()
        for value in (replace(prepared,target=6),replace(prepared,available={**prepared.available,'powder':99})):
            with self.assertRaises(ValueError):
                verify_material_preview(before,value,3,items())

    def test_jewelry_material_not_applied_to_helmet(self):
        before,prepared,_ = resources()
        bad = replace(prepared,reserved={**prepared.reserved,'jewelry_powder':1})
        with self.assertRaises(ValueError):
            verify_material_preview(before,bad,3,items())

    def test_actual_mismatch_and_pending_preview_rejected(self):
        before,prepared,after = resources()
        with self.assertRaises(ValueError):
            verify_actual_resources(before,prepared,replace(after,available={**after.available,'gold':6799}))
        with self.assertRaises(ValueError):
            verify_actual_resources(before,prepared,prepared)

    def test_zero_template_requires_whole_glyph(self):
        from PIL import Image
        from pathlib import Path
        from e7_assistant.batch_resources import zero_match
        with Image.open(Path(__file__).resolve().parents[1]/'e7_assistant/assets/batch-materials/zero.png') as image:
            self.assertGreaterEqual(zero_match(image.convert('RGB')),.9)
        for color in ('black','white','#808080'):
            self.assertLess(zero_match(Image.new('RGB',(130,40),color)),.9)
        from PIL import ImageDraw
        with Image.open(Path(__file__).resolve().parents[1]/'e7_assistant/assets/batch-materials/zero.png') as image:
            eight = image.convert('RGB')
        ImageDraw.Draw(eight).line((0,9,eight.width-1,9),fill='white',width=3)
        self.assertLess(zero_match(eight),.9)
        from PIL import ImageFont
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
        for digit in '123456789':
            glyph = Image.new('RGB',(40,40),'black')
            ImageDraw.Draw(glyph).text((5,5),digit,font=font,fill='white')
            with self.subTest(digit=digit):
                self.assertLess(zero_match(glyph),.9)

    def test_actual_stage3_result_zero_font(self):
        from pathlib import Path
        from PIL import Image
        from e7_assistant.batch_resources import zero_match
        source = Path(__file__).resolve().parents[1]/'docs/assets/batch-selection-2026-11-10/round-stage3-zero.png'
        with Image.open(source) as image:
            reference = image.convert('RGB').resize((1661,933))
            box = tuple(round(v*(1661/1280 if i%2==0 else 933/720))
                        for i,v in enumerate((1168,528,1270,558)))
            self.assertGreaterEqual(zero_match(reference.crop(box)),.9)
