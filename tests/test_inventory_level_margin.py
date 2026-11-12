from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PIL import Image

from e7_assistant.inventory_vision import _read_levels,inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


class LevelMarginTests(unittest.TestCase):
    def test_actual_red_level_recovers_from_padding_single_digit_conflict(self):
        path=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/31-level-margin-red.png'
        values,proof=_read_levels(path,{'level0':(150,331,176,356)},True)
        self.assertEqual(values['level0'],'85')
        self.assertEqual(proof['level0']['recovery'],'independent_margin_consensus')
        self.assertTrue(any(c['text']=='5' and c['confidence']>=.99
                            for c in proof['level0']['original']['candidates']))

    def test_actual_single_digit_conflict_recovers_only_after_two_new_consistent_crops(self):
        path=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/30-level-margin-conflict.png'
        report=inspect_inventory(inspect_screen(path))
        self.assertEqual(report['cards'][2]['level'],85)
        proof=report['level_evidence']['level0_2']
        self.assertEqual(proof['recovery'],'independent_margin_consensus')
        self.assertFalse(proof['original']['accepted'])
        self.assertTrue(any(c['text']=='5' and c['confidence']>=.9 for c in proof['original']['candidates']))
        for direction in ('left','expanded'):
            self.assertTrue(proof['original']['margin_retries'][direction]['accepted'])
            self.assertEqual(proof['original']['margin_retries'][direction]['text'],'85')

    def scenario(self,values,original_candidates=()):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'blank.png';Image.new('RGB',(1280,720),'black').save(path)
            results=[({'level0':v},{'level0':{'text':v,'accepted':bool(v),'confidence':.99 if v else 0,
                        'candidates':list(original_candidates) if i==0 else []}}) for i,v in enumerate(values)]
            with patch('e7_assistant.local_ocr.read_local_regions',side_effect=results) as reader:
                result=_read_levels(path,{'level0':(350,228,375,251)},True)
                return result,reader.call_count

    def test_accepted_original_is_not_replaced_or_reread(self):
        result,count=self.scenario(['90'])
        self.assertEqual((result[0]['level0'],count),('90',1))

    def test_disagreement_unknown_and_positive_original_conflicts_stay_unknown(self):
        for left,top,candidates in [('85','90',()),('85','',()),('5','5',()),
                ('85','85',({'text':'90','confidence':.96},)),
                ('85','85',({'text':'75','confidence':.96},))]:
            with self.subTest(left=left,top=top,candidates=candidates):
                result,count=self.scenario(['',left,top],candidates)
                self.assertEqual((result[0]['level0'],count),('',3))


if __name__=='__main__': unittest.main()
