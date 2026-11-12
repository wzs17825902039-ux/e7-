from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from e7_assistant.equipment_protection import EquipmentProtection
from e7_assistant.inventory_detail import read_detail
from e7_assistant.rules import Policy, RIGHT_MAIN_STATS, evaluate
from e7_assistant.settings import Settings,save_settings,load_settings
from test_inventory_detail import screen


def right_detail(slot='项链',name='暴击伤害',value='12%',policy=None,rarity='purple'):
    original=screen()
    words=tuple({**w,'text':('英雄' if rarity=='purple' else '传说')+slot} if w['text']=='传说头盔' else
                {**w,'text':name} if w['text']=='生命值' else w
                for w in original.words if w['center'][1]!=450)
    observed=replace(original,words=words)
    values={'level':'85','score':'23','main':value,'stat0':'3','stat1':'28','stat2':'4%'}
    if rarity=='red':
        observed=replace(observed,words=observed.words+({'text':'生命值','confidence':.99,'center':(950,450)},))
        values['stat3']='8%'
    return read_detail(observed,{'rarity':rarity,'level':85,'enhancement':0},
                       lambda *args:values,policy=policy)


class RightMainTests(unittest.TestCase):
    def test_purple_right_ignores_main_whitelist(self):
        item=right_detail()['equipment']
        self.assertFalse(item.main_stat_usable)
        self.assertEqual(evaluate(item).action,'continue')
        self.assertEqual(evaluate(right_detail(rarity='red')['equipment']).action,'store')

    def test_whitelist_matches_slot_stat_and_unit_then_still_applies_speed_rule(self):
        policy=Policy(right_main_stats={'necklace':['cdmg'],'ring':['atk_pct']})
        detail=right_detail(policy=policy)
        self.assertTrue(detail['equipment'].main_stat_usable)
        self.assertEqual(evaluate(detail['equipment'],policy).action,'continue')
        self.assertFalse(right_detail('戒指','攻击力','12',policy)['equipment'].main_stat_usable)
        self.assertTrue(right_detail('戒指','攻击力','12%',policy)['equipment'].main_stat_usable)
        item=replace(detail['equipment'],stats={'def_flat':28,'effectiveness':4,'hp_pct':8})
        self.assertEqual(evaluate(item,policy).action,'stop')

    def test_invalid_main_units_or_slot_combination_are_not_accepted(self):
        for slot,name,value in (('项链','速度','3'),('戒指','暴击伤害','12%'),
                                ('鞋子','速度','3%'),('项链','暴击伤害','12'),('戒指','攻击力','0%')):
            with self.subTest(slot=slot,name=name,value=value),self.assertRaises(ValueError):
                right_detail(slot,name,value)

    def test_policy_rejects_invalid_slot_stat_type_and_duplicates(self):
        for config in ([],{'helmet':['hp_pct']},{'ring':['crit']},{'boots':['cdmg']},
                        {'necklace':'cdmg'},{'necklace':['cdmg','cdmg']},{'ring':[{}]}):
            with self.subTest(config=config),self.assertRaises(ValueError):
                Policy(right_main_stats=config)
        for slot,stats in RIGHT_MAIN_STATS.items():
            Policy(right_main_stats={slot:list(stats)})

    def test_setting_roundtrip_and_old_protection_do_not_override_new_main_use(self):
        with tempfile.TemporaryDirectory() as directory:
            old=Policy()
            current=Policy(right_main_stats={'necklace':['cdmg']})
            path=Path(directory)/'settings.json'
            save_settings(path,Settings(policy=asdict(current)))
            self.assertEqual(load_settings(path).policy['right_main_stats'],current.right_main_stats)
            original=EquipmentProtection(Path(directory)/'protected','test',old)
            old_detail=right_detail(policy=old,rarity='red')
            original.remember(old_detail)
            changed=EquipmentProtection(Path(directory)/'protected','test',current)
            self.assertNotEqual(original.directory,changed.directory)
            self.assertFalse(changed.should_skip(right_detail(policy=current,rarity='red')))
