from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.inventory_vision import inspect_inventory, _read_levels
from e7_assistant.workflow_screen import inspect_screen


class VerticalLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/76-numeric-grid-clipped-levels.png'

    def test_actual_numeric_grid_reads_all_twenty_one_levels(self):
        report=inspect_inventory(inspect_screen(self.source))
        self.assertEqual(len(report['cards']),21)
        self.assertTrue(all(c['level']==85 and c['known'] for c in report['cards']))

    def test_clipped_original_requires_two_independent_vertical_crops(self):
        values,proof=_read_levels(self.source,{'level':(150,330,176,355)},True)
        self.assertEqual(values['level'],'85')
        self.assertEqual(proof['level']['recovery'],'independent_vertical_consensus')
        self.assertEqual(set(proof['level']['original']['vertical_retries']),{'down2','down3'})

    def test_disagreeing_or_missing_vertical_read_never_recovers_a_level(self):
        original=_read_levels
        for second in ('88',''):
            reads=[]
            def local(path,boxes,**kwargs):
                return ({key:'' for key in boxes},
                        {key:{'text':'','confidence':0,'accepted':False,'candidates':[]} for key in boxes})
            def recurse(path,boxes,*args,**kwargs):
                if kwargs.get('_vertical_retry') is False:
                    reads.append(dict(boxes))
                    value='85' if len(reads)==1 else second
                    return ({key:value for key in boxes},
                            {key:{'text':value,'confidence':.99 if value else 0,
                                  'accepted':bool(value),'candidates':[]} for key in boxes})
                return original(path,boxes,*args,**kwargs)
            with self.subTest(second=second),patch('e7_assistant.local_ocr.read_local_regions',side_effect=local),\
                    patch('e7_assistant.inventory_vision._read_levels',side_effect=recurse):
                values=original(self.source,{'level':(150,330,176,355)})
                self.assertEqual(values['level'],'')
                self.assertEqual(len(reads),2)


if __name__=='__main__':
    unittest.main()
