from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from e7_assistant.crafting import CraftPreview
from e7_assistant.rules import Equipment, Policy
from e7_assistant.tasks import Journal, Limits, TaskControl
from e7_assistant.workflow import BatchItem, WorkflowOptions, WorkflowTask


class FlowDriver:
    def __init__(self):
        self.gold = 1000000
        self.material = 1000
        self.powder = 100
        self.round = 0
        self.batch_calls = 0
        self.confirmations = []
        self.sales = []
        self.cleanup_actions = []
        self.targets = []
        self.wrong_result = False

    def resources(self):
        return {"gold": self.gold, "craft_material": self.material, "powder": self.powder}

    def open_forge(self, options):
        self.round += 1
        self.batch_calls = 0

    def prepare_craft(self, options, repeat):
        if repeat:
            return None  # 本模拟背包在一次十连后满。
        return CraftPreview(self.resources(), {"gold": 21000, "craft_material": 40}, options.slot, "craft.png")

    def commit_craft(self, preview):
        self.confirmations.append("craft")
        self.gold -= 21000
        self.material -= 40

    def finish_craft(self, preview):
        return {"resources": self.resources(), "image": "crafted.png"}

    def initial_cleanup(self, action):
        self.cleanup_actions.append(action)

    def collect_batch(self, limit, max_pages):
        self.batch_calls += 1
        if self.batch_calls > 1:
            return []
        return [BatchItem("0", Equipment(f"{self.round}-good", "purple", 85, 0, "helmet",
                    {"speed": 3, "crit": 5, "atk_pct": 7}, True, True, 25), True, False),
                BatchItem("1", Equipment(f"{self.round}-bad", "purple", 85, 0, "helmet",
                    {"hp_pct": 5, "crit": 5, "atk_pct": 7}, True, True, 25), True, False)]

    def select_active(self, items, active):
        self.current = [replace(item, selected=item.token in active) for item in items]
        return self.current

    def prepare_enhancement(self, items, target):
        self.targets.append(target)
        self.target = target
        return CraftPreview(self.resources(), {"gold": 1000, "powder": 1}, "helmet", "preview.png")

    def commit_enhancement(self, preview):
        self.confirmations.append("enhance")
        self.gold -= 1000
        self.powder -= 1

    def finish_enhancement(self, preview):
        result = [replace(item, equipment=replace(item.equipment, enhancement=self.target,
                    stats={**item.equipment.stats, "speed": min(9,3+self.target)})) if item.selected else item
                  for item in self.current]
        if self.wrong_result:
            result[0] = replace(result[0], token="changed")
        return {"items": result, "resources": self.resources(), "image": "after.png"}

    def dispose_batch(self, items, rejected, protected, action):
        self.sales.append((set(rejected), set(protected), action))
        return {"disposed": list(rejected)}


class WorkflowTests(unittest.TestCase):
    def test_red_speed_history_is_not_skipped_by_first_target_six(self):
        driver=FlowDriver()
        item=BatchItem('red',Equipment('red','red',85,0,'helmet',
            {'speed':3,'crit':3,'atk_pct':4,'resistance':4},True,True),True,False)
        with tempfile.TemporaryDirectory() as directory:
            task=WorkflowTask(driver,WorkflowOptions(first_target=6),
                Policy(red_profile_enabled=True,sell_failed_red=True),Limits(gold=10000,powder=10,max_steps=10),
                TaskControl(),Journal(Path(directory)/'run'))
            result=task.run_batch([item])
        self.assertEqual(result['state'],'complete')
        self.assertEqual(driver.targets,[3,6,9,12])
        self.assertEqual(result['items'][0]['equipment']['red_speed_misses'],2)

    def test_verified_completed_result_updates_statistics_once_before_lock(self):
        class CompletionDriver(FlowDriver):
            def finish_enhancement(self,preview):
                return {'items':[replace(i,equipment=replace(i.equipment,enhancement=15,
                    stats={**i.equipment.stats,'speed':16})) if i.selected else i for i in self.current],
                    'resources':self.resources(),'image':'after.png'}
            def lock_items(self,items,targets):
                return [replace(i,locked=True) if i.token in targets else i for i in items]
        item=BatchItem('red',Equipment('red','red',85,12,'helmet',
            {'speed':13,'crit':3,'atk_pct':4,'resistance':4},True,True,red_speed_misses=1),True,False)
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(Path(directory)/'run')
            task=WorkflowTask(CompletionDriver(),WorkflowOptions(),Policy(red_profile_enabled=True),
                Limits(gold=10000,powder=10,max_steps=10),TaskControl(),journal)
            result=task.run_batch([item])
            events=journal.path.read_text(encoding='utf8')
        self.assertEqual(result['state'],'complete')
        self.assertEqual(result['enhancement_statistics']['speed16plus'],1)
        self.assertEqual(events.count('"kind": "enhancement_statistics"'),1)

    def test_red_miss_counter_is_cumulative_not_last_stage_only(self):
        from e7_assistant.workflow import record_speed_roll
        for hit in (True,False):
            old=BatchItem('red',Equipment('red','red',85,6,'helmet',
                {'speed':7,'def_flat':33,'def_pct':7,'atk_flat':40},True,True,red_speed_misses=1),True,False)
            nine=replace(old,equipment=replace(old.equipment,enhancement=10,
                         stats={**old.equipment.stats,'speed':7+3*hit}))
            nine=record_speed_roll([old],[nine],9)[0]
            self.assertEqual(nine.equipment.red_speed_misses,1+int(not hit))
            twelve=replace(nine,equipment=replace(nine.equipment,enhancement=12))
            self.assertEqual(record_speed_roll([nine],[twelve],12)[0].equipment.red_speed_misses,2+int(not hit))
        zero=replace(old,equipment=replace(old.equipment,enhancement=0,red_speed_misses=None))
        recovered=record_speed_roll([zero],[zero],0)[0]
        self.assertIsNone(recovered.equipment.early_speed_increased)
        self.assertIsNone(recovered.equipment.red_speed_misses)
        unknown=replace(old,equipment=replace(old.equipment,red_speed_misses=None))
        self.assertIsNone(record_speed_roll([unknown],[nine],9)[0].equipment.red_speed_misses)

    def test_red_early_speed_hit_tracks_either_first_roll_without_inventing_history(self):
        from e7_assistant.workflow import record_speed_roll
        for first_hit,second_hit in ((False,True),(True,False),(False,False)):
            old=BatchItem('red',Equipment('red','red',85,0,'helmet',
                {'speed':4,'def_flat':33,'def_pct':7,'atk_flat':40},True,True),True,False)
            three=replace(old,equipment=replace(old.equipment,enhancement=3,
                          stats={**old.equipment.stats,'speed':4+2*first_hit}))
            three=record_speed_roll([old],[three],3)[0]
            six=replace(three,equipment=replace(three.equipment,enhancement=6,
                        stats={**three.equipment.stats,'speed':three.equipment.stats['speed']+2*second_hit}))
            six=record_speed_roll([three],[six],6)[0]
            self.assertIs(six.equipment.early_speed_increased,first_hit or second_hit)
            unknown=replace(three,equipment=replace(three.equipment,early_speed_increased=None))
            missed=replace(unknown,equipment=replace(unknown.equipment,enhancement=6))
            self.assertIsNone(record_speed_roll([unknown],[missed],6)[0].equipment.early_speed_increased)

    def test_purple_first_miss_stops_at_three_and_is_sold(self):
        class MissDriver(FlowDriver):
            def finish_enhancement(self,preview):
                return {'items':[replace(i,equipment=replace(i.equipment,enhancement=self.target))
                                 if i.selected else i for i in self.current],
                        'resources':self.resources(),'image':'miss.png'}
        with tempfile.TemporaryDirectory() as temporary:
            driver=MissDriver();journal=Journal(Path(temporary)/'run')
            task=WorkflowTask(driver,WorkflowOptions(first_target=6),Policy(sell_failed_purple=True),
                              Limits(gold=200000,powder=30,craft_material=1000,max_steps=50),TaskControl(),journal)
            result=task.run()
            self.assertEqual(result['state'],'complete')
            self.assertEqual(driver.targets,[3])
            self.assertEqual(driver.sales,[({'0','1'},set(),'sell')])

    def test_purple_twelve_new_substat_is_not_a_missed_speed_roll(self):
        from e7_assistant.workflow import record_speed_roll
        old=BatchItem('0',Equipment('purple','purple',85,9,'helmet',{'speed':12,'crit':3,'atk_pct':4},True,True),True,False)
        after=replace(old,equipment=replace(old.equipment,enhancement=12,stats={**old.equipment.stats,'hp_pct':4}))
        result=record_speed_roll([old],[after],12)
        self.assertIsNone(result[0].equipment.last_speed_increased)

    def run_flow(self, driver=None, options=None, limits=None, control=None):
        driver = driver or FlowDriver()
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary) / "run")
            result = WorkflowTask(driver, options or WorkflowOptions(), Policy(),
                limits or Limits(gold=200000, powder=30, craft_material=1000, max_steps=50),
                control or TaskControl(), journal).run()
            events = journal.path.read_text(encoding="utf-8")
        return result, driver, events

    def test_full_two_round_flow_preserves_store_and_stop(self):
        result, driver, events = self.run_flow(options=WorkflowOptions(rounds=2))
        self.assertEqual(result["state"], "complete")
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(result["spent"]["gold"], 48000)
        self.assertEqual(driver.cleanup_actions, ["extract", "extract"])
        self.assertEqual(driver.targets, [3, 6, 9, 3, 6, 9])
        self.assertEqual(driver.sales, [])
        self.assertIn('"protected": ["0", "1"]', events)

    def test_sale_requires_separate_explicit_discard_decision(self):
        from e7_assistant.rules import evaluate
        def explicit(item, policy):
            decision = evaluate(item, policy)
            if item.equipment_id.endswith('-bad'):
                decision.discard_allowed = True
            return decision
        with patch('e7_assistant.workflow.evaluate', side_effect=explicit):
            result, driver, _ = self.run_flow()
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(driver.sales, [({'1'}, {'0'}, 'sell')])

    def test_purple_starts_three_even_with_red_first_target_six(self):
        result, driver, _ = self.run_flow(options=WorkflowOptions(first_target=6, initial_disposal="sell"))
        self.assertEqual(result["state"], "complete")
        self.assertEqual(driver.targets, [3, 6, 9])
        self.assertEqual(driver.cleanup_actions, ["sell"])

    def test_shared_budget_cannot_reset_at_next_round(self):
        result, driver, _ = self.run_flow(options=WorkflowOptions(rounds=2),
            limits=Limits(gold=25000, powder=20, craft_material=1000, max_steps=50))
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(driver.confirmations.count("craft"), 1)
        self.assertFalse(result["outcome_unknown"])

    def test_finished_equipment_is_not_accepted_as_new_batch(self):
        driver = FlowDriver()
        collect = driver.collect_batch
        def wrong(**kwargs):
            items = collect(**kwargs)
            items[0].equipment.enhancement = 15
            return items
        driver.collect_batch = wrong
        result, driver, _ = self.run_flow(driver)
        self.assertEqual(result["state"], "failed")
        self.assertNotIn("enhance", driver.confirmations)

    def test_mixed_unfinished_batch_only_selects_items_below_each_target(self):
        class MixedDriver(FlowDriver):
            def __init__(self):
                super().__init__()
                self.requests=[]

            def collect_batch(self, **kwargs):
                self.batch_calls += 1
                if self.batch_calls > 1:
                    return []
                return [BatchItem(str(stage), Equipment(f'stage-{stage}', 'red',85,stage,'helmet',
                    {'speed':12,'crit':5,'atk_pct':7,'hp_pct':6},True,True),
                    True,False) for stage in (0,3,6,9,12,14)]

            def prepare_enhancement(self, items, target):
                selected=[item for item in items if item.selected]
                if not selected or any(item.equipment.enhancement>=target for item in selected):
                    raise ValueError('强化目标未高于已选择装备的实际等级')
                self.requests.append((target,[item.equipment.enhancement for item in selected]))
                return super().prepare_enhancement(items,target)

            def finish_enhancement(self, preview):
                items=[]
                for item in self.current:
                    if item.selected:
                        stats={**item.equipment.stats,**({'hp_pct':6} if self.target>=12 else {})}
                        if self.target==15:
                            stats['speed']=16
                        item=replace(item,equipment=replace(item.equipment,enhancement=self.target,stats=stats))
                    items.append(item)
                return {'items':items,'resources':self.resources(),'image':'after.png'}

            def lock_items(self,items,targets):
                return [replace(item,locked=True) if item.token in targets else item for item in items]

        for first,targets in ((3,[3,6,9,12,15]),(6,[6,9,12,15])):
            with self.subTest(first=first):
                result,driver,_=self.run_flow(MixedDriver(),WorkflowOptions(first_target=first))
                self.assertEqual(result['state'],'complete')
                self.assertEqual(driver.targets,targets)
                self.assertEqual(driver.sales,[])
                self.assertEqual(driver.requests[-1],(15,[12,12,12,12,12,14]))

    def test_incomplete_inventory_scan_does_not_start_next_round(self):
        driver = FlowDriver()
        driver.collect_batch = lambda **kwargs: None
        result, driver, _ = self.run_flow(driver, WorkflowOptions(rounds=2))
        self.assertEqual(result["state"], "failed")
        self.assertEqual(driver.round, 1)

    def test_wrong_result_is_unknown_and_not_sold_or_retried(self):
        driver = FlowDriver()
        driver.wrong_result = True
        result, driver, _ = self.run_flow(driver)
        self.assertTrue(result["outcome_unknown"])
        self.assertEqual(driver.confirmations.count("enhance"), 1)
        self.assertEqual(driver.sales, [])

    def test_stop_before_navigation_does_nothing(self):
        control = TaskControl()
        control.stop()
        result, driver, _ = self.run_flow(control=control)
        self.assertEqual(result["state"], "stopped")
        self.assertEqual(driver.round, 0)

    def test_invalid_workflow_parameters(self):
        for data in ({"craft_count": 5}, {"first_target": 9}, {"rounds": 0},
                     {"source_index": True}, {"initial_disposal": "discard"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                WorkflowOptions(**data)


if __name__ == "__main__":
    unittest.main()
