from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
import unittest

from e7_assistant.rules import Equipment,Policy,evaluate
from e7_assistant.inventory_detail import read_detail
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.inventory_scan import InventoryTraversal
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.inventory_badge_vision import inspect_selected_three
from test_inventory_detail import screen
from test_inventory_scan import report


ROOT=Path(__file__).resolve().parents[1]


class IgnoreLevelTests(unittest.TestCase):
    def test_unknown_level_is_not_fabricated_and_does_not_block_speed_policy(self):
        item=Equipment('unknown-grade','purple',None,0,'helmet',
                       {'speed':3,'crit':5,'atk_pct':8},True,True,25)
        self.assertTrue(Policy().ignore_equipment_level)
        self.assertEqual(evaluate(item).action,'continue')
        self.assertIsNone(asdict(item)['level'])
        self.assertEqual(evaluate(item,Policy(ignore_equipment_level=False)).action,'review')
        for level in (70,88,90):
            self.assertEqual(evaluate(replace(item,level=level)).action,'continue')
        self.assertEqual(evaluate(replace(item,recognition_ok=False)).action,'review')

    def test_detail_never_requests_level_when_ignored_and_still_checks_stage(self):
        observed=replace(screen(),words=screen().words+(
            {'text':'+3','center':(950,178),'confidence':1.},))
        values={'score':'41','main':'864','enhancement':'+3',
                'stat0':'3','stat1':'28','stat2':'7%','stat3':'14%'}
        requests=[]
        def read(path,boxes):
            requests.append(set(boxes))
            return values
        candidate={'level':None,'rarity':'red','enhancement':3}
        detail=read_detail(observed,candidate,read,policy=Policy())
        self.assertNotIn('level',requests[0])
        self.assertIsNone(detail['equipment'].level)
        self.assertEqual(detail['equipment'].enhancement,3)
        with self.assertRaises(ValueError):
            read_detail(observed,{**candidate,'enhancement':15},read,policy=Policy())
        with self.assertRaises(ValueError):
            read_detail(observed,candidate,lambda *args:{**values,'enhancement':'+6'},policy=Policy())

    def test_two_row_overlap_ignores_only_grade_when_explicitly_configured(self):
        before,after=report([0,1,2]),report([1,2,3])
        for view in (before,after):
            view['level_scope']='ignored'
            for card in view['cards']:
                card['level']=None
        self.assertEqual(InventoryTraversal().advance(before,after),1)
        bad=deepcopy(after)
        bad['cards'][0]['enhancement']=None
        with self.assertRaises(ValueError):
            InventoryTraversal().advance(before,bad)
        del after['level_scope']
        with self.assertRaises(ValueError):
            InventoryTraversal().advance(before,after)

    def test_real_locked_selected_three_uses_graphic_badge_and_no_grade_gate(self):
        source=ROOT/'docs/assets/inventory-traversal-2026-11-10/80-locked-three-selected.png'
        observed=inspect_screen(source)
        result=inspect_inventory(observed,ignore_levels=True)
        target=next(c for c in result['cards'] if (c['row'],c['column'])==(1,2))
        self.assertTrue(target['selected'])
        self.assertTrue(target['known'])
        self.assertEqual(target['enhancement'],3)
        self.assertIsNone(target['level'])
        self.assertEqual(result['badge_evidence']['badge1_2']['method'],'selected_badge_template')
        detail=read_detail(observed,target,policy=Policy())
        self.assertIsNone(detail['equipment'].level)
        self.assertEqual(detail['equipment'].stats,{'atk_pct':14,'speed':3,'resistance':7,'hp_pct':6})

    def test_selected_three_template_rejects_blank_and_other_real_badge(self):
        from PIL import Image
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'blank.png'
            Image.new('RGB',(1280,720),(50,50,50)).save(source)
            self.assertFalse(inspect_selected_three(source,(399,326,439,357))['accepted'])
        # 已有+9样本的局部徽标不得误认为+3。
        source=ROOT/'docs/assets/inventory-traversal-2026-11-10/70-enhanced-selection-dim.png'
        self.assertFalse(inspect_selected_three(source,(795,194,835,225))['accepted'])


if __name__=='__main__':
    unittest.main()
