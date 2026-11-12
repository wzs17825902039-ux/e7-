from pathlib import Path
import tempfile
import unittest

from PIL import Image

from e7_assistant.inventory_grid_vision import locate_rows


class NewMarkerGridTests(unittest.TestCase):
    source=Path(__file__).resolve().parents[1]/'runs/desktop-350c17e018be/workflow-0290.png'

    def test_actual_new_marker_grid_has_three_contiguous_rows(self):
        # 该帧三行真实锚点为207/380/554；现有中位数拟合得到208起点。
        self.assertEqual(locate_rows(self.source,{}),[208,380,552])

    def test_missing_middle_card_edge_is_not_filled_from_spacing(self):
        with Image.open(self.source) as raw, tempfile.TemporaryDirectory() as folder:
            image=raw.convert('RGB')
            # 遮掉第二行第四张的完整右边框，不能靠相邻行或其余六列补造证据。
            image.paste((20,20,20),(520,300,540,385))
            source=Path(folder)/'missing-edge.png'
            image.save(source)
            with self.assertRaises(ValueError):locate_rows(source,{})
