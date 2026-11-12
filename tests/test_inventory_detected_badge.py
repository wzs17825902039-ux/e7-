from pathlib import Path
import unittest
from e7_assistant.inventory_badge_vision import inspect_numbered_inventory_badge


class DetectedBadgeTests(unittest.TestCase):
    source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-purple-badge-row.png'

    def test_weapon_background_uses_two_detected_badge_readings(self):
        proof=inspect_numbered_inventory_badge(self.source,(201,282,241,313))
        self.assertEqual(proof['enhancement'],3)
        self.assertEqual(proof['proof']['source'],'orange_plate_detected_glyph')
        self.assertEqual([c['text'] for c in proof['proof']['candidates']],['+3','+3'])

    def test_blank_without_orange_plate_is_not_a_number(self):
        self.assertIsNone(inspect_numbered_inventory_badge(self.source,(900,280,940,311)))

    def test_real_selected_weapon_restores_plate_before_two_scale_detection(self):
        source=self.source.with_name('inventory-selected-red-weapon.png')
        proof=inspect_numbered_inventory_badge(source,(201,282,241,313))
        self.assertEqual(proof['enhancement'],3)
        self.assertEqual(proof['proof']['source'],'orange_plate_detected_glyph')
        self.assertGreater(proof['proof']['brightness_gain'],1)
