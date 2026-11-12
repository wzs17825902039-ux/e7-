from pathlib import Path
import unittest

from e7_assistant.batch_selection import BatchSelectionDriver, SelectionImageUnstable
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.inventory_detail import read_detail
from e7_assistant.workflow_screen import inspect_screen


class SelectedEnhancementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        cls.screens=[inspect_screen(folder/name) for name in (
            '69-enhanced-selection-before.png','70-enhanced-selection-dim.png')]
        cls.before,cls.after=[inspect_inventory(screen) for screen in cls.screens]

    def test_selected_darkened_plus_nine_never_becomes_zero(self):
        self.assertEqual(self.before['cards'][6]['enhancement'],9)
        self.assertTrue(self.after['cards'][6]['selected'])
        self.assertEqual(self.after['cards'][6]['enhancement'],9)
        proof=self.after['badge_evidence']['badge0_6']
        self.assertTrue(proof['accepted'])
        # 当前橙底板/双尺度字形路径替代旧固定2.5倍预处理，核验实际证据而非旧元数据。
        self.assertEqual(proof['method'],'orange_plate_numbered_badge')
        self.assertEqual(proof['proof']['value'],9)
        self.assertEqual([c['scale'] for c in proof['proof']['candidates']],[2,3])
        for candidate in proof['proof']['candidates']:
            self.assertEqual(candidate['text'],'+9')
            self.assertGreaterEqual(candidate['confidence'],.95)

    def test_equipment_animation_still_requires_image_recheck(self):
        # 本组前后截图的头盔还有独立的白色流光变化；徽标修复不能绕过身份保护。
        with self.assertRaises(SelectionImageUnstable):
            BatchSelectionDriver._verify_click(self.before,self.after,(0,6))

    def test_unreadable_dimmed_badge_is_unknown_not_zero(self):
        report=inspect_inventory(self.screens[1],read_badges=lambda path,regions:{key:'' for key in regions})
        target=report['cards'][6]
        self.assertIsNone(target['enhancement'])
        self.assertFalse(target['known'])
        self.assertFalse(target['eligible'])

    def test_real_enhanced_detail_is_independently_registered(self):
        detail=read_detail(self.screens[1],self.after['cards'][6])
        equipment=detail['equipment']
        self.assertEqual(equipment.enhancement,9)
        self.assertEqual(equipment.stats,{'speed':8,'atk_pct':15,'crit':10})
        self.assertEqual(equipment.game_score,61)

    def test_two_digit_enhancement_detail_is_independently_registered(self):
        folder=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        screen=inspect_screen(folder/'71-enhanced-plus-ten-detail.png')
        detail=read_detail(screen,{'rarity':'purple','level':85,'enhancement':10})
        self.assertEqual(detail['equipment'].enhancement,10)


if __name__=='__main__':
    unittest.main()
