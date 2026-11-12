from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from e7_assistant.batch_entry import verify_entry
from e7_assistant.rules import Policy,Equipment,evaluate
from test_batch_entry import fixtures
import test_batch_selection as selection_tests


class SelectionOnlyTests(unittest.TestCase):
    def test_fixed_right_main_needs_speed_but_other_mains_use_normal_rules(self):
        from e7_assistant.rules import RIGHT_MAIN_STATS
        policy=Policy(right_main_stats={slot:list(stats) for slot,stats in RIGHT_MAIN_STATS.items()})
        for main,stats,usable in (('def_flat',{'atk_pct':8,'crit':5,'cdmg':7,'resistance':4},False),
                                  ('def_flat',{'speed':3,'crit':5,'cdmg':7,'resistance':4},True),
                                  ('atk_pct',{'hp_pct':8,'crit':5,'cdmg':7,'resistance':4},True)):
            selection,report=fixtures(1)
            old=selection['registered'][0];new=report['records'][0]
            old['selection_only']=True
            old['equipment']={key:value for key,value in old['equipment'].items()
                              if key in ('rarity','level','enhancement','slot')}
            old['equipment'].update(level=None,slot='ring',rarity='red')
            new['equipment'].update(level=None,slot='ring',rarity='red',stats=stats)
            new['main']={'stat':main,'value':60}
            new['locked']=False
            with self.subTest(main=main,stats=stats):
                self.assertEqual(verify_entry(selection,report,policy)[0].equipment.main_stat_usable,usable)

    def test_confirmed_fixed_right_main_without_speed_is_disposable(self):
        item=Equipment('fixed','red',None,0,'ring',
                       {'atk_pct':8,'crit':5,'cdmg':7,'hp_pct':8},False,True,main_stat='def_flat')
        policy=Policy(discard_flat_right_without_speed=True,red_profile_enabled=True,sell_failed_red=True,
                      right_main_stats={'ring':['def_flat']})
        self.assertTrue(evaluate(item,policy).discard_allowed)
        self.assertFalse(evaluate(replace(item,recognition_ok=False),policy).discard_allowed)
        fast=replace(item,stats={'speed':3,'crit':5,'cdmg':7,'hp_pct':8},main_stat_usable=True)
        self.assertEqual(evaluate(fast,policy).action,'continue')
        self.assertFalse(evaluate(replace(item,main_stat=None),policy).discard_allowed)

    def test_inventory_does_not_call_attribute_reader(self):
        harness=selection_tests.SelectionTests()
        driver=harness.setup_driver([selection_tests.card(0),selection_tests.card(1,15),selection_tests.card(2,3)])
        driver.defer_details=True
        driver.detail_reader=lambda *args: self.fail('背包不能读取属性')
        def header(screen,candidate):
            return {'rarity':candidate['rarity'],'level':None,'enhancement':candidate['enhancement'],'slot':'helmet'}
        driver.screen=type('Screen',(),{'source':'screen.png'})()
        original=driver.observe
        def observe(*args,**kwargs):
            result=original(*args,**kwargs)
            driver.screen=type('Screen',(),{'source':'screen.png'})()
            return result
        driver.observe=observe
        with patch('e7_assistant.batch_selection.read_selection_header',side_effect=header):
            result=driver.collect_visible(limit=2)
        self.assertEqual(harness.clicks,[(160,200),(360,200)])
        self.assertTrue(all(r['selection_only'] for r in result['registered']))
        self.assertTrue(all('stats' not in r['equipment'] for r in result['registered']))

    def test_batch_page_first_reads_attributes_and_checks_selection(self):
        selection,report=fixtures(2)
        for old,new in zip(selection['registered'],report['records']):
            old['selection_only']=True
            old['equipment']={key:value for key,value in old['equipment'].items()
                              if key in ('rarity','level','enhancement','slot')}
            old['equipment']['level']=None
            new['equipment']['level']=None
            new['locked']=False
        items=verify_entry(selection,report)
        self.assertEqual(items[0].equipment.stats,report['records'][0]['equipment']['stats'])
        no_main=deepcopy(report)
        no_main['records'][0]['main']=None
        self.assertIsNone(verify_entry(selection,no_main)[0].equipment.main_stat)
        for field,value in [('selected',False),('locked',None)]:
            broken=deepcopy(report)
            broken['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                verify_entry(selection,broken)

    def test_confirmed_purple_failures_are_disposable_but_unknowns_are_not(self):
        item=Equipment('test','purple',None,9,'helmet',{'speed':11,'crit':5,'atk_pct':7},True,True)
        policy=Policy(sell_failed_purple=True)
        self.assertTrue(evaluate(item,policy).discard_allowed)
        self.assertFalse(evaluate(replace(item,recognition_ok=False),policy).discard_allowed)
        self.assertFalse(evaluate(item,Policy(sell_failed_purple=False)).discard_allowed)
        self.assertFalse(evaluate(replace(item,reforged_speed=18,reforged_speed_source='game_preview'),policy).discard_allowed)

    def test_red_flow_gates_use_effective_weighted_score_not_game_score(self):
        item=Equipment('red','red',None,6,'helmet',{'atk_pct':14,'crit':8,'cdmg':8,'resistance':4},True,True,1)
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        self.assertEqual(evaluate(item,policy).action,'continue')
        weak=replace(item,stats={'atk_pct':4,'crit':3,'cdmg':4,'resistance':4},game_score=100)
        self.assertTrue(evaluate(weak,policy).discard_allowed)
        slow=replace(item,enhancement=15,stats={'hp_pct':25,'def_pct':20,'resistance':10,'crit':3})
        self.assertEqual(evaluate(slow,policy).action,'keep_candidate')

    def test_red_speed_is_primary_but_high_effective_score_can_rescue(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        item=Equipment('red','red',None,9,'helmet',{'speed':3,'atk_pct':30,'crit':15,'cdmg':25},True,True,100)
        decision=evaluate(item,policy)
        self.assertEqual(decision.action,'continue')
        self.assertTrue(any(route.startswith('red_quality:') for route in decision.routes))
        self.assertFalse(decision.discard_allowed)
        fast=replace(item,stats={**item.stats,'speed':12},red_speed_misses=1)
        self.assertEqual(evaluate(fast,policy).routes,['speed_potential'])
        switched=replace(fast,red_speed_misses=2)
        self.assertTrue(all(route.startswith('red_quality:') for route in evaluate(switched,policy).routes))
        no_speed=replace(item,stats={'hp_pct':8,'atk_pct':30,'crit':15,'cdmg':25})
        self.assertEqual(evaluate(no_speed,policy).action,'continue')
