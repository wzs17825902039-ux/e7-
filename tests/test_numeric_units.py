from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PIL import Image,ImageDraw
from e7_assistant.numeric_units import read_percent_value
from e7_assistant.batch_vision import inspect_batch


class NumericUnitTests(unittest.TestCase):
    def test_actual_seven_percent_with_orange_increment(self):
        source=Path(__file__).resolve().parents[1]/'runs/desktop-13bb83c713de/workflow-0573.png'
        result=read_percent_value(source,(133,313,250,334))
        self.assertIsNotNone(result)
        self.assertEqual(result['text'],'7%')
        self.assertGreaterEqual(result['percent_match'],.92)
        report=inspect_batch(source,'helmet',ignore_levels=True,require_score=False,ignore_purple_main=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['records'][4]['equipment']['stats'],
                         {'def_pct':8,'crit':7,'speed':3,'resistance':7})
        with TemporaryDirectory() as folder,Image.open(source) as image:
            ImageDraw.Draw(image).rectangle((144,317,157,330),fill='black')
            missing=Path(folder)/'missing-percent.png';image.save(missing)
            self.assertIsNone(read_percent_value(missing,(133,313,250,334)))

    source=Path(__file__).resolve().parents[1]/'docs/assets/sale-preview-2026-11-10/percent-and-main-icon-entry.png'

    def test_selected_eleven_percent_uses_independent_number_and_unit(self):
        source=Path(__file__).resolve().parents[1]/'runs/selected-inventory-resume-268a8262/workflow-0011.png'
        result=read_percent_value(source,(621,313,738,334))
        self.assertEqual(result['text'],'11%')
        self.assertGreaterEqual(result['percent_match'],.92)
        slots={i:'helmet' if i<3 else 'armor' for i in range(16)}
        report=inspect_batch(source,slots,ignore_levels=True,require_score=False,ignore_purple_main=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['records'][6]['equipment']['stats']['cdmg'],11)

    def test_rejected_seven_percent_is_recovered_as_independent_number_and_unit(self):
        result=read_percent_value(self.source,(868,206,983,227))
        self.assertEqual(result['text'],'7%')
        self.assertGreater(result['percent_match'],.92)

    def test_missing_unit_or_number_cannot_be_inferred(self):
        for box in ((876,209,890,223),(865,206,875,227)):
            with self.subTest(box=box),TemporaryDirectory() as directory,Image.open(self.source) as image:
                ImageDraw.Draw(image).rectangle(box,fill='black')
                path=Path(directory)/'missing.png';image.save(path)
                self.assertIsNone(read_percent_value(path,(868,206,983,227)))

    def test_full_real_batch_recovers_number_and_wide_main_icons(self):
        report=inspect_batch(self.source,{i:'boots' if i<2 else 'ring' for i in range(16)},ignore_levels=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['records'][3]['equipment']['stats']['effectiveness'],7)
        for index in (6,7,11,14,15):
            self.assertEqual(report['records'][index]['main'],{'stat':'effectiveness','value':12})
