from pathlib import Path
import unittest
from e7_assistant.workflow_screen import inspect_selection_screen
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.selection_state import verify_selection_state


class SelectedWeaponRarityTests(unittest.TestCase):
    def test_red_weapon_art_does_not_change_purple_rarity_when_selected(self):
        assets=Path(__file__).resolve().parents[1]/'docs/assets'
        before,after=[inspect_inventory(inspect_selection_screen(assets/name),ignore_levels=True)
            for name in ('inventory-selected-weapon-before.png','inventory-selected-weapon-after.png')]
        self.assertEqual(before['cards'][4]['rarity'],'purple')
        self.assertEqual(after['cards'][4]['rarity'],'purple')
        verify_selection_state(before,after,(0,4),True)
