from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from e7_assistant.custom_targets import match_targets, SET_GROUPS
from e7_assistant.rules import Equipment, Policy, evaluate
from e7_assistant.set_vision import inspect_batch_sets


ROOT=Path(__file__).resolve().parents[1]
RULE={'name':'输出混搭','sets':['speed'],'stats':['atk_pct','crit']}


def gear(**changes):
    return replace(Equipment('custom','red',85,0,'helmet',
        {'atk_pct':8,'crit':3,'effectiveness':8,'resistance':8},True,True,gear_set='speed'),**changes)


def policy(**changes):
    return replace(Policy(red_profile_enabled=True,sell_failed_red=True,
        custom_targets_enabled=True,custom_targets=[RULE]),**changes)


class CustomTargetsTests(unittest.TestCase):
    def test_real_batch_orchestrator_emits_custom_score_and_sells_only_after_gate_failure(self):
        from e7_assistant.workflow import BatchItem,WorkflowTask,WorkflowOptions
        from e7_assistant.tasks import Journal,Limits,TaskControl
        from test_workflow import FlowDriver
        class Driver(FlowDriver):
            def finish_enhancement(self,preview):
                return {'items':[replace(item,equipment=replace(item.equipment,enhancement=self.target))
                                  if item.selected else item for item in self.current],
                        'resources':self.resources(),'image':'after.png'}
        with TemporaryDirectory() as directory:
            journal=Journal(Path(directory)/'run')
            driver=Driver()
            task=WorkflowTask(driver,WorkflowOptions(first_target=3),policy(),Limits(gold=100000,powder=10),TaskControl(),journal)
            result=task.run_batch([BatchItem('0',gear(),True,False)])
            self.assertEqual(result['state'],'complete')
            self.assertEqual(driver.targets,[3,6])
            self.assertEqual(driver.sales,[({'0'},set(),'sell')])
            import json
            events=[json.loads(line) for line in journal.path.read_text(encoding='utf8').splitlines()]
            hits=[event for event in events if event['kind']=='custom_target_match']
            self.assertEqual([event['score'] for event in hits],[28.5]*3)
            self.assertEqual([event['action'] for event in hits],['continue','continue','stop'])

    def test_default_is_off_and_saved_combinations_do_not_change_original_decision(self):
        item=gear()
        self.assertFalse(Policy().custom_targets_enabled)
        self.assertEqual(evaluate(item,policy(custom_targets_enabled=False)),
                         evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True)))
        self.assertEqual(evaluate(item,policy(custom_targets_enabled=False)).action,'stop')

    def test_combination_counts_all_four_substats_without_same_use_requirement(self):
        decision=evaluate(gear(),policy())
        self.assertEqual(decision.weighted_score,28.5)
        self.assertEqual(decision.effective_scores,{'custom:输出混搭':28.5})
        self.assertEqual(decision.action,'continue')
        self.assertIn('输出混搭',decision.reasons[0])

    def test_all_selected_substats_and_any_selected_set_are_required(self):
        self.assertEqual(match_targets(gear(),policy()),['输出混搭'])
        self.assertEqual(match_targets(gear(gear_set='hit'),policy()),[])
        self.assertEqual(match_targets(gear(stats={'atk_pct':8,'hp_pct':8,'effectiveness':8,'resistance':8}),policy()),[])
        p=policy(custom_targets=[{**RULE,'sets':['hit','speed']}])
        self.assertEqual(match_targets(gear(gear_set='hit'),p),['输出混搭'])

    def test_multiple_matches_do_not_add_their_scores_or_lower_threshold(self):
        p=policy(custom_targets=[RULE,{**RULE,'name':'另一个搭配'}],custom_left_gates={
            '0':30,'3':32,'6':34,'9':40,'12':46,'15':52})
        result=evaluate(gear(),p)
        self.assertEqual(result.action,'stop')
        self.assertTrue(result.discard_allowed)
        self.assertEqual(set(result.effective_scores.values()),{28.5})

    def test_unknown_set_is_stored_only_if_a_set_specific_combination_could_match(self):
        result=evaluate(gear(gear_set=None),policy())
        self.assertEqual((result.action,result.discard_allowed),('store',False))
        self.assertEqual(evaluate(gear(gear_set=None),policy(custom_targets=[{**RULE,'sets':[]}])).action,'continue')
        item=gear(gear_set=None,stats={'hp_pct':8,'def_pct':8,'effectiveness':8,'resistance':8})
        self.assertNotIn('套装', '；'.join(evaluate(item,policy()).reasons))

    def test_purple_and_purple_boots_never_use_custom_score(self):
        for slot in ('helmet','boots'):
            item=gear(rarity='purple',slot=slot,stats={'atk_pct':8,'crit':5,'hp_pct':8})
            self.assertEqual(match_targets(item,policy()),[])
            self.assertEqual(evaluate(item,policy()),evaluate(item,policy(custom_targets_enabled=False)))
            self.assertEqual(evaluate(item,policy()).action,'stop')

    def test_speed_priority_and_main_stat_restrictions_still_apply(self):
        item=gear(stats={'speed':2,'atk_pct':1,'crit':1,'resistance':1},enhancement=3)
        self.assertEqual(evaluate(item,policy()).target_level,6)
        self.assertEqual(evaluate(gear(slot='ring',main_stat_usable=False),policy()).action,'store')

    def test_custom_finished_gear_uses_keep_gate_and_existing_lock_margin(self):
        item=gear(enhancement=15,stats={'atk_pct':20,'crit':10,'effectiveness':10,'resistance':10})
        self.assertEqual(evaluate(item,policy()).action,'keep_candidate')
        item=gear(enhancement=15,stats={'atk_pct':20,'crit':10,'effectiveness':10,'resistance':8})
        self.assertEqual(evaluate(item,policy()).action,'store')
        item=gear(enhancement=15,stats={'atk_pct':20,'crit':10,'effectiveness':10,'resistance':6})
        self.assertEqual(evaluate(item,policy()).action,'stop')

    def test_invalid_configs_are_rejected(self):
        invalid=[{'custom_targets_enabled':True,'custom_targets':[]},
                 {'custom_targets':[{'name':'x','sets':['unknown'],'stats':['speed']}]},
                 {'custom_targets':[{**RULE,'stats':[]}]},
                 {'custom_targets':[RULE,RULE]},
                 {'custom_left_gates':{'0':10}},
                 {'custom_left_gates':{'0':20,'3':18,'6':34,'9':40,'12':46,'15':52}},
                 {'custom_left_gates':{'0':float('nan'),'3':26,'6':34,'9':40,'12':46,'15':52}}]
        for changes in invalid:
            with self.subTest(changes=changes),self.assertRaises(ValueError):policy(**changes)


class SetVisionTests(unittest.TestCase):
    def test_real_full_batch_at_two_resolutions(self):
        source=ROOT/'runs/workflow-98a8a0db9e69/workflow-0314.png'
        expected=['hit','crit','speed','speed','speed','speed','hit','hit',
                  'hit','speed','crit','crit','crit','hit','crit','crit']
        for size in ((1280,720),(1661,933)):
            with self.subTest(size=size),TemporaryDirectory() as directory:
                path=Path(directory)/'frame.png'
                with Image.open(source) as im:im.resize(size).save(path)
                results=inspect_batch_sets(path,range(16))
                self.assertEqual([results[i]['set'] for i in range(16)],expected)

    def test_blank_images_are_never_labeled(self):
        with TemporaryDirectory() as directory:
            for color in ('black','white','gray'):
                path=Path(directory)/f'{color}.png';Image.new('RGB',(1280,720),color).save(path)
                self.assertIsNone(inspect_batch_sets(path,[0])[0]['set'])

    def test_source_icon_mapping_is_distinct_for_all_eighteen_sets(self):
        # 验证图标标签表和缩放拒识，不代表其余15种已实机验收。
        with TemporaryDirectory() as directory:
            for source,group in enumerate(SET_GROUPS):
                with Image.open(ROOT/f'e7_assistant/assets/forge-sources/source-{source}-sets.png') as im:
                    for index,name in enumerate(group):
                        x=round(index*34.7)
                        frame=Image.new('RGB',(1280,720),'black')
                        frame.paste(im.crop((x+2,2,x+31,35)),(77,187))
                        path=Path(directory)/'icon.png';frame.save(path)
                        with self.subTest(name=name):self.assertEqual(inspect_batch_sets(path,[0])[0]['set'],name)
