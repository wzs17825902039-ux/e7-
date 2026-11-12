import unittest
from unittest.mock import patch

from scripts.probe_inventory_traversal import NavigationOnlyAdb


class InventoryProbeTests(unittest.TestCase):
    def test_equipment_or_resource_input_is_blocked_before_adb(self):
        adb=NavigationOnlyAdb('adb','test-device')
        with patch.object(adb,'_run') as execute:
            for intent in (None,{'kind':'navigation_intent','action':'sell','x':500,'y':500},
                           {'kind':'navigation_intent','action':'batch_select','x':400,'y':400}):
                if intent:
                    adb.event(intent)
                with self.assertRaises(ValueError):
                    adb.tap(500,500)
            execute.assert_not_called()

    def test_verified_navigation_intent_is_consumed_once(self):
        adb=NavigationOnlyAdb('adb','test-device')
        adb.event({'kind':'navigation_intent','action':'menu','x':1240,'y':32})
        with patch.object(adb,'_run',return_value=b'') as execute:
            adb.tap(1240,32)
            with self.assertRaises(ValueError):
                adb.tap(1240,32)
            execute.assert_called_once()
        self.assertEqual(adb.navigation_taps,[{'action':'menu','point':(1240,32)}])

    def test_intervening_observation_invalidates_old_intent(self):
        adb=NavigationOnlyAdb('adb','test-device')
        adb.event({'kind':'navigation_intent','action':'menu','x':1240,'y':32})
        adb.event({'kind':'workflow_screen','page':'unknown'})
        with patch.object(adb,'_run') as execute:
            with self.assertRaises(ValueError):
                adb.tap(1240,32)
            execute.assert_not_called()


if __name__=='__main__':
    unittest.main()
