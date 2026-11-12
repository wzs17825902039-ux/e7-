from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

from e7_assistant.inventory_vision import _read_levels, inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


class LevelColorTests(unittest.TestCase):
    def test_actual_conflicting_single_digit_can_use_independent_color_evidence(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/62-level-color-conflict.png'
        report=inspect_inventory(inspect_screen(source))
        self.assertEqual(report['cards'][10]['level'],85)
        proof=report['level_evidence']['level1_3']
        self.assertEqual(proof['recovery'],'original_color_consensus')
        self.assertFalse(proof['original']['accepted'])
        self.assertTrue(any(c['text']=='5' and c['confidence']>=.9
                            for c in proof['original']['candidates']))

    def test_missing_result_without_single_digit_evidence_does_not_add_color_reads(self):
        result,count=self.scenario(['','',''])
        self.assertEqual((result[0]['level0'],count),('',3))

    def test_full_level_conflict_in_masked_margin_also_vetoes_color_recovery(self):
        result,count=self.scenario(['','90','85','85','85'],({'text':'5','confidence':.96},))
        self.assertEqual((result[0]['level0'],count),('',5))

    def test_actual_gold_decoration_does_not_hide_the_first_digit(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/55-level-color-contrast.png'
        report=inspect_inventory(inspect_screen(source))
        self.assertTrue(all(card['known'] for card in report['cards']))
        self.assertEqual(report['cards'][16]['level'],85)
        proof=report['level_evidence']['level2_2']
        self.assertEqual(proof['recovery'],'original_color_consensus')
        self.assertEqual(proof['original']['text'],'5')
        for crop in proof['original']['color_retries'].values():
            self.assertTrue(crop['accepted'])
            self.assertEqual(crop['text'],'85')

    def scenario(self,values,candidates=()):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'blank.png'
            Image.new('RGB',(1280,720),'black').save(path)
            results=[({'level0':v},{'level0':{'text':v,'accepted':bool(v),
                       'confidence':.99 if v else 0,'candidates':list(candidates) if i==0 else []}})
                     for i,v in enumerate(values)]
            with patch('e7_assistant.local_ocr.read_local_regions',side_effect=results) as reader:
                return _read_levels(path,{'level0':(350,228,375,251)},True),reader.call_count

    def test_single_digit_is_never_expanded_without_two_accepted_color_crops(self):
        for left,right in (('5','5'),('85',''),('85','90'),('','')):
            with self.subTest(left=left,right=right):
                result,count=self.scenario(['5',left,right])
                self.assertEqual((result[0]['level0'],count),('5',3))

    def test_positive_full_level_conflict_prevents_color_recovery(self):
        for value in ('75','90'):
            with self.subTest(value=value):
                result,count=self.scenario(['5','85','85'],({'text':value,'confidence':.96},))
                self.assertEqual(result[0]['level0'],'5')


if __name__=='__main__':
    unittest.main()
