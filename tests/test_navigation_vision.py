from pathlib import Path
import tempfile
import unittest
from PIL import Image,ImageDraw,ImageEnhance,ImageOps
from e7_assistant.navigation_vision import has_back_arrow


class BackArrowTests(unittest.TestCase):
    def test_actual_back_arrow_is_present_but_home_and_modal_background_are_rejected(self):
        root=Path(__file__).resolve().parents[1]
        self.assertTrue(has_back_arrow(root/'runs/desktop-e6fa5dc4e0cf/workflow-0091.png'))
        self.assertFalse(has_back_arrow(root/'runs/desktop-e6fa5dc4e0cf/workflow-0093.png'))
        self.assertFalse(has_back_arrow(root/'docs/assets/legendary-crafting/wyvern-speed-helmet-confirmation.png'))

    def test_arrow_shape_orientation_and_brightness_are_required(self):
        root=Path(__file__).resolve().parents[1]
        with Image.open(root/'e7_assistant/assets/navigation/back-arrow-reference.png') as ref:
            arrow=ref.convert('RGB').resize((28,36))
        with tempfile.TemporaryDirectory() as tmp:
            for variant in ('arrow','mirror','dark','circle'):
                image=Image.new('RGB',(1280,720))
                if variant=='circle':ImageDraw.Draw(image).ellipse((20,14,48,50),fill='white')
                else:
                    patch=ImageOps.mirror(arrow) if variant=='mirror' else ImageEnhance.Brightness(arrow).enhance(.2) if variant=='dark' else arrow
                    image.paste(patch,(20,14))
                path=Path(tmp)/(variant+'.png');image.save(path)
                self.assertEqual(has_back_arrow(path),variant=='arrow',variant)
