from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from e7_assistant.equipment_protection import EquipmentProtection
from e7_assistant.inventory_detail import detail_fingerprint
from e7_assistant.rules import Equipment, Policy


def detail(speed=False, **changes):
    stats = {'speed':3,'crit':5,'atk_pct':7} if speed else {'hp_pct':5,'crit':5,'atk_pct':7}
    equipment = Equipment('sample','purple',85,0,'helmet',stats,True,True,25)
    equipment = replace(equipment,**changes)
    main = ('生命值','540')
    return {'equipment':equipment,'fingerprint':detail_fingerprint(equipment,main),
            'main':main,'source':'offline.png'}


class EquipmentProtectionTests(unittest.TestCase):
    def test_stopped_zero_gear_survives_new_instance_and_idempotent_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EquipmentProtection(directory,'device',Policy())
            entry = detail()
            store.remember(entry)
            restored = EquipmentProtection(directory,'device',Policy())
            self.assertTrue(restored.should_skip(entry))
            restored.remember(entry)
            self.assertEqual(len(restored.records()),1)
            self.assertEqual(restored.records()[0]['equipment']['enhancement'],0)

    def test_different_policy_device_and_attributes_do_not_inherit_old_conclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EquipmentProtection(directory,'device',Policy())
            store.remember(detail())
            self.assertFalse(EquipmentProtection(directory,'another',Policy()).should_skip(detail()))
            self.assertFalse(EquipmentProtection(directory,'device',Policy(initial_speed_min=3)).should_skip(detail()))
            changed = detail(game_score=26)
            self.assertFalse(store.should_skip(changed))

    def test_current_main_stat_approval_is_reassessed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EquipmentProtection(directory,'device',Policy())
            unapproved = detail(True,rarity='red',main_stat_usable=False,
                                stats={'speed':3,'crit':5,'atk_pct':7,'hp_pct':8})
            store.remember(unapproved)
            self.assertTrue(store.should_skip(unapproved))
            approved = detail(True,rarity='red',stats={'speed':3,'crit':5,'atk_pct':7,'hp_pct':8})
            self.assertEqual(unapproved['fingerprint'],approved['fingerprint'])
            self.assertFalse(store.should_skip(approved))

    def test_continuing_finished_and_unconfirmed_gear_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EquipmentProtection(directory,'device',Policy())
            for entry in (detail(True),detail(enhancement=15),detail(recognition_ok=False)):
                with self.subTest(entry=entry), self.assertRaises(ValueError):
                    store.remember(entry)
            forged = {**detail(),'fingerprint':'0'*64}
            with self.assertRaises(ValueError):
                store.remember(forged)

    def test_stopped_unfinished_gear_remains_protected_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EquipmentProtection(directory,'device',Policy())
            entry = detail(True, enhancement=9, stats={'speed':6,'crit':5,'atk_pct':7})
            store.remember(entry)
            restored = EquipmentProtection(directory,'device',Policy())
            self.assertTrue(restored.should_skip(entry))
            self.assertEqual(restored.records()[0]['equipment']['enhancement'],9)

    def test_corrupt_or_tampered_record_stops_instead_of_ignoring_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EquipmentProtection(directory,'device',Policy())
            entry = detail()
            store.remember(entry)
            path = store.directory/(entry['fingerprint']+'.json')
            record = json.loads(path.read_text(encoding='utf-8'))
            record['equipment']['stats']['hp_pct'] = 8
            path.write_text(json.dumps(record),encoding='utf-8')
            with self.assertRaises(ValueError):
                store.should_skip(entry)
            path.write_text('{broken',encoding='utf-8')
            with self.assertRaises(ValueError):
                store.records()
