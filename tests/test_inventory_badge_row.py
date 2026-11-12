from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PIL import Image,ImageDraw
from e7_assistant.inventory_grid_vision import locate_rows


class BadgeRowTests(unittest.TestCase):
    source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-purple-badge-row.png'

    def test_badges_and_purple_glow_do_not_shift_existing_row(self):
        self.assertEqual(locate_rows(self.source,{}),[208,380,552])

    def test_glow_one_pixel_contour_variation_keeps_same_complete_grid(self):
        source=self.source.with_name('inventory-purple-glow-row.png')
        self.assertEqual(locate_rows(source,{}),[208,380,552])

    def test_corrected_row_still_requires_every_card_border(self):
        with TemporaryDirectory() as directory,Image.open(self.source) as image:
            ImageDraw.Draw(image).rectangle((735,310,750,350),fill='black')
            damaged=Path(directory)/'damaged.png';image.save(damaged)
            with self.assertRaises(ValueError):locate_rows(damaged,{})
