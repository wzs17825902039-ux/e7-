import unittest

from e7_assistant.rules import Equipment, Policy, evaluate
from e7_assistant.replay import replay


def observation(**changes):
    raw = dict(equipment_id="test-1", rarity="purple", level=85, enhancement=0,
               slot="helmet", stats={"speed": 2, "crit": 3, "atk_pct": 4},
               main_stat_usable=True, recognition_ok=True)
    raw.update(changes)
    return raw


class RuleScenarios(unittest.TestCase):
    def test_stricter_red_quality_gates_stop_below_boundary_and_preserve_speed_route(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True,
            red_left_gates={'0':22,'3':28,'6':38,'9':44,'12':50,'15':56},
            red_right_gates={'0':20,'3':26,'6':36,'9':42,'12':48,'15':54})
        for slot,gates in (('helmet',policy.red_left_gates),('ring',policy.red_right_gates)):
            for stage in (0,3,6,9,12,15):
                for delta in (-1,0):
                    score=gates[str(stage)]+delta
                    item=Equipment(**observation(rarity='red',slot=slot,enhancement=stage,
                        stats={'hp_pct':score/3,'def_pct':score/3,'resistance':score-score/3*2,'atk_flat':1},
                        preferred_use='bulk_resistance'))
                    decision=evaluate(item,policy)
                    self.assertEqual(decision.action,('store' if stage==15 else 'continue') if delta==0 else 'stop')
        speed_item=Equipment(**observation(rarity='red',enhancement=9,
            stats={'speed':10,'atk_flat':1,'def_flat':1,'resistance':1},red_speed_misses=1))
        self.assertEqual(evaluate(speed_item,policy).action,'continue')

    def test_completed_low_speed_purple_is_discarded_without_quality_fallback(self):
        for speed in (0,10,11,12):
            item=Equipment(**observation(enhancement=15,
                stats={'atk_pct':30,'hp_pct':25,'crit':15,**({'speed':speed} if speed else {'def_pct':20})}))
            decision=evaluate(item,Policy(sell_failed_purple=True))
            self.assertEqual(decision.action,'stop')
            self.assertTrue(decision.discard_allowed)
        item=Equipment(**observation(enhancement=15,
            stats={'atk_pct':9,'effectiveness':6,'speed':12,'crit':5}))
        self.assertFalse(evaluate(item,Policy(sell_failed_purple=False)).discard_allowed)
        item.stats['speed']=13
        self.assertEqual(evaluate(item,Policy()).action,'store')

    def test_defense_percent_supports_damage_profiles_without_lowering_stage_gates(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        for profile,primary in (('crit_dps','atk_pct'),('slow_dps','atk_pct'),('hp_dps','hp_pct')):
            item=Equipment(**observation(rarity='red',preferred_use=profile,
                stats={primary:8,'def_pct':8,'crit':4,'effectiveness':1}))
            decision=evaluate(item,policy)
            self.assertEqual(decision.effective_scores[profile],22)
            self.assertEqual(decision.action,'continue')
            item.enhancement=3
            self.assertEqual(evaluate(item,policy).action,'stop')

    def test_defense_percent_can_save_and_lock_completed_damage_gear(self):
        item=Equipment(**observation(rarity='red',enhancement=15,preferred_use='crit_dps',
            stats={'atk_pct':20,'def_pct':20,'crit':10,'effectiveness':1}))
        decision=evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True))
        self.assertEqual(decision.effective_scores['crit_dps'],55)
        self.assertEqual(decision.action,'keep_candidate')
        self.assertFalse(decision.discard_allowed)

    def test_red_unknown_miss_history_does_not_sell_or_assume_speed_chase(self):
        item=Equipment(**observation(rarity='red',enhancement=9,
            stats={'speed':12,'atk_flat':1,'def_flat':1,'resistance':1}))
        d=evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True))
        self.assertEqual(d.action,'store')
        self.assertFalse(d.discard_allowed)

    def test_red_under_two_total_misses_keeps_chasing_each_stage(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        for stage,target in ((9,12),(10,12),(12,15),(13,15)):
            item=Equipment(**observation(rarity='red',enhancement=stage,
                stats={'speed':8,'atk_flat':40,'def_flat':30,'resistance':4},red_speed_misses=1))
            d=evaluate(item,policy)
            self.assertEqual((d.action,d.target_level,d.discard_allowed),('continue',target,False))

    def test_red_two_total_misses_use_effective_score_before_plus12(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        for stage in (9,):
            item=Equipment(**observation(rarity='red',enhancement=stage,
                stats={'speed':12,'atk_flat':40,'def_flat':30,'resistance':4},red_speed_misses=2))
            self.assertEqual(evaluate(item,policy).action,'stop')
            item.stats={'speed':10,'hp_pct':20,'def_pct':12,'atk_flat':1}
            d=evaluate(item,policy)
            self.assertEqual(d.action,'continue')
            self.assertTrue(any(route.startswith('red_quality:') for route in d.routes))
            item.stats={'speed':14,'atk_flat':1,'def_flat':1,'resistance':1}
            self.assertEqual(evaluate(item,policy).action,'continue')

    def test_red_plus12_twelve_speed_continues_independent_of_misses_and_score(self):
        for stage in (12,13,14):
            for misses in (None,1,2,3,4):
                for profiles in (False,True):
                    item=Equipment(**observation(rarity='red',enhancement=stage,
                        stats={'speed':12,'atk_flat':1,'def_flat':1,'resistance':1},red_speed_misses=misses))
                    decision=evaluate(item,Policy(red_profile_enabled=profiles,sell_failed_red=True))
                    self.assertEqual((decision.action,decision.target_level,decision.discard_allowed),('continue',15,False))
        item=Equipment(**observation(rarity='red',enhancement=12,
            stats={'speed':11,'atk_flat':1,'def_flat':1,'resistance':1},red_speed_misses=2))
        self.assertEqual(evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True)).action,'stop')
        item.enhancement=15;item.stats['speed']=12
        self.assertNotEqual(evaluate(item,Policy(red_profile_enabled=True)).action,'continue')
        item.enhancement=12
        policy=Policy(custom_targets_enabled=True,custom_targets=[{'name':'带速输出','sets':['speed'],'stats':['speed']}])
        self.assertEqual(evaluate(item,policy).target_level,15)

    def test_red_unrefforged_fourteen_speed_is_retained_with_configurable_boundary(self):
        for minimum in (14,15,16):
            for speed in (minimum-1,minimum):
                item=Equipment(**observation(rarity='red',enhancement=15,
                    stats={'speed':speed,'atk_flat':1,'def_flat':1,'resistance':1}))
                d=evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True,red_raw_speed_keep_min=minimum))
                self.assertEqual(d.action=='keep_candidate',speed>=minimum)
                if speed>=minimum:self.assertFalse(d.discard_allowed)
        for value in (13,17,14.5,True):
            with self.assertRaises(ValueError):Policy(red_raw_speed_keep_min=value)

    def test_red_first_two_rolls_one_speed_hit_continues_from_six(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        item=Equipment(**observation(rarity='red',enhancement=6,
            stats={'def_flat':33,'speed':7,'def_pct':7,'atk_flat':77},early_speed_increased=True))
        decision=evaluate(item,policy)
        self.assertEqual((decision.action,decision.target_level,decision.discard_allowed),('continue',9,False))
        item.early_speed_increased=False
        self.assertEqual(evaluate(item,policy).action,'stop')

    def test_red_quality_lock_is_three_above_retention_and_speed_is_unchanged(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        for slot,stats,action in (
                ('helmet',{'hp_pct':18,'def_pct':17,'resistance':17,'atk_pct':1},'store'),
                ('helmet',{'hp_pct':19,'def_pct':18,'resistance':18,'atk_pct':1},'keep_candidate'),
                ('ring',{'hp_pct':18,'def_pct':16,'resistance':16,'atk_pct':1},'store'),
                ('ring',{'hp_pct':19,'def_pct':17,'resistance':17,'atk_pct':1},'keep_candidate'),
                ('helmet',{'speed':16,'crit':3,'effectiveness':4,'resistance':4},'keep_candidate')):
            decision=evaluate(Equipment(**observation(rarity='red',enhancement=15,slot=slot,stats=stats)),policy)
            self.assertEqual(decision.action,action)
            self.assertFalse(decision.discard_allowed)

    def test_hp_percent_counts_for_every_damage_profile_without_changing_gates(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        for profile,primary in [('crit_dps','atk_pct'),('slow_dps','atk_pct'),('def_dps','def_pct')]:
            item=Equipment(**observation(rarity='red',preferred_use=profile,
                stats={primary:8,'hp_pct':8,'crit':4,'effectiveness':1}))
            decision=evaluate(item,policy)
            self.assertEqual(decision.effective_scores[profile],22)
            self.assertEqual(decision.action,'continue')
            item.enhancement=3
            self.assertEqual(evaluate(item,policy).action,'stop')

    def test_red_only_first_two_gates_are_relaxed_with_inclusive_boundaries(self):
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        self.assertEqual(policy.red_left_gates,{'0':20,'3':26,'6':34,'9':40,'12':46,'15':52})
        self.assertEqual(policy.red_right_gates,{'0':18,'3':24,'6':32,'9':38,'12':44,'15':50})
        for slot,stage,gate in [('helmet',0,20),('ring',0,18),('helmet',3,26),('ring',3,24),
                                ('helmet',6,34),('ring',6,32)]:
            for score in (gate-1,gate):
                with self.subTest(slot=slot,stage=stage,score=score):
                    item=Equipment(**observation(rarity='red',slot=slot,enhancement=stage,
                        stats={'hp_pct':score-8,'def_pct':4,'resistance':4,'atk_pct':1}))
                    decision=evaluate(item,policy)
                    self.assertEqual(decision.action,'continue' if score>=gate else 'stop')
                    self.assertEqual(decision.discard_allowed,score<gate)

    def test_total_above_twenty_does_not_override_effective_profile_gate(self):
        item=Equipment(**observation(rarity='red',slot='ring',
            stats={'atk_pct':7,'effectiveness':8,'crit':5,'resistance':7}))
        d=evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True))
        self.assertEqual(d.weighted_score,29.5)
        self.assertEqual(max(d.effective_scores.values()),14.5)
        self.assertEqual(d.action,'stop')
        self.assertTrue(d.discard_allowed)
        self.assertIn('副属性总分29.500',d.reasons[0])
        self.assertIn('最高同用途有效分14.500',d.reasons[0])
        self.assertIn('阶段门槛18',d.reasons[0])

    def test_flat_substats_use_toolbox_weights_and_only_matching_profiles(self):
        item=Equipment(**observation(rarity='red',slot='ring',
            stats={'atk_flat':39,'def_flat':31,'hp_flat':174,'crit':5}))
        d=evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True))
        self.assertAlmostEqual(d.weighted_score,19.04)
        self.assertAlmostEqual(d.effective_scores['slow_dps'],19.04)
        self.assertAlmostEqual(d.effective_scores['bulk_resistance'],8.08)
        self.assertEqual(d.action,'continue')
        self.assertFalse(d.discard_allowed)

    def test_five_real_flat_substat_rings_are_no_longer_all_stored(self):
        cases=[({'hp_flat':179,'hp_pct':6,'atk_pct':8,'resistance':8},'stop'),
               ({'def_flat':32,'hp_pct':8,'effectiveness':8,'resistance':6},'continue'),
               ({'def_pct':7,'atk_pct':7,'crit':5,'atk_flat':45},'continue'),
               ({'atk_flat':42,'resistance':8,'effectiveness':7,'def_pct':7},'stop'),
               ({'hp_pct':8,'cdmg':7,'def_flat':34,'def_pct':6},'continue')]
        for stats,action in cases:
            with self.subTest(stats=stats):
                item=Equipment(**observation(rarity='red',slot='ring',stats=stats))
                d=evaluate(item,Policy(red_profile_enabled=True,sell_failed_red=True))
                self.assertEqual(d.action,action)
                self.assertEqual(d.discard_allowed,action=='stop')

    def test_purple_plus6_speed_gate_and_sale_authorization(self):
        for stage in (6,7,8):
            for speed in (3,4,6,7,8):
                with self.subTest(stage=stage,speed=speed):
                    item=Equipment(**observation(enhancement=stage,stats={'speed':speed,'crit':3,'atk_pct':4}))
                    decision=evaluate(item,Policy(sell_failed_purple=True))
                    self.assertEqual(decision.action,'stop' if speed<8 else 'continue')
                    self.assertEqual(decision.discard_allowed,speed<8)
        item=Equipment(**observation(enhancement=3,stats={'speed':3,'crit':3,'atk_pct':4}))
        self.assertEqual(evaluate(item,Policy(sell_failed_purple=True)).action,'continue')

    def test_purple_missed_speed_roll_stops_at_plus3(self):
        for stage in (3,4,6,9):
            item=Equipment(**observation(enhancement=stage,stats={'speed':8,'crit':3,'atk_pct':4},last_speed_increased=False))
            decision=evaluate(item,Policy(sell_failed_purple=True))
            self.assertEqual(decision.action,'stop')
            self.assertTrue(decision.discard_allowed)
        item=Equipment(**observation(enhancement=12,stats={'speed':12,'crit':3,'atk_pct':4,'hp_pct':4}))
        self.assertEqual(evaluate(item,Policy(sell_failed_purple=True)).action,'continue')

    def test_no_speed_purple_does_not_enter_quality_or_user_route(self):
        item = Equipment(**observation(stats={"atk_pct": 8, "crit": 5, "cdmg": 7}, user_target=True))
        self.assertEqual(evaluate(item, Policy(allow_draft_quality_rules=True)).action, "stop")

    def test_speed_candidate_ignores_quality_score(self):
        policy = Policy(allow_draft_quality_rules=True, game_score_formula_confirmed=True,
                        game_score_gates={"0": 100})
        decision = evaluate(Equipment(**observation(game_score=10)), policy)
        self.assertEqual((decision.action, decision.target_level), ("continue", 3))
        self.assertIn("speed_potential", decision.routes)

    def test_purple_plus9_boundary(self):
        for speed, expected in [(11, "store"), (12, "continue")]:
            with self.subTest(speed=speed):
                item = Equipment(**observation(enhancement=9, stats={"speed": speed, "crit": 3, "atk_pct": 4}))
                self.assertEqual(evaluate(item).action, expected)

    def test_purple_plus12_requires_new_substat(self):
        item = Equipment(**observation(enhancement=12, stats={"speed": 12, "crit": 3, "atk_pct": 4}))
        self.assertEqual(evaluate(item).action, "review")

    def test_reforged_retention_boundaries_and_unknown(self):
        for speed, route in [(15, None), (16, "speed_optional"), (19, "speed_optional"), (20, "speed_priority")]:
            with self.subTest(speed=speed):
                item = Equipment(**observation(enhancement=15,
                    stats={"speed": 13, "crit": 3, "atk_pct": 4, "hp_pct": 4},
                    reforged_speed=speed, reforged_speed_source="game_preview"))
                decision = evaluate(item)
                self.assertEqual(decision.action, "keep_candidate" if route else "store")
                if route:
                    self.assertIn(route, decision.routes)
        item = Equipment(**observation(enhancement=15,
            stats={"speed": 16, "crit": 3, "atk_pct": 4, "hp_pct": 4}))
        decision=evaluate(item)
        self.assertEqual(decision.action, "keep_candidate")
        self.assertEqual(decision.routes,["speed_optional"])  # 不硬编码16→20
        self.assertIsNone(item.reforged_speed)

    def test_observed_finished_speed_protects_without_inventing_reforge(self):
        for speed,route in [(15,None),(16,'speed_optional'),(19,'speed_optional'),(20,'speed_priority')]:
            item=Equipment(**observation(enhancement=15,
                stats={'speed':speed,'crit':3,'atk_pct':4,'hp_pct':4}))
            decision=evaluate(item)
            with self.subTest(speed=speed):
                self.assertEqual(decision.action,'keep_candidate' if route else 'store')
                self.assertEqual(decision.routes,[route] if route else [])
                self.assertIsNone(item.reforged_speed)
                self.assertFalse(decision.discard_allowed)

    def test_observed_retention_respects_policy_and_recognition(self):
        raw=observation(enhancement=15,stats={'speed':19,'crit':3,'atk_pct':4,'hp_pct':4})
        policy=Policy(retain_speed_min=20,priority_speed_min=22)
        self.assertEqual(evaluate(Equipment(**raw),policy).action,'store')
        for changes in ({'recognition_ok':False},):
            with self.subTest(changes=changes):
                self.assertNotEqual(evaluate(Equipment(**{**raw,**changes})).action,'keep_candidate')
        self.assertEqual(evaluate(Equipment(**{**raw,'main_stat_usable':False})).action,'keep_candidate')
        self.assertNotEqual(evaluate(Equipment(**{**raw,'level':90}),
                                     Policy(ignore_equipment_level=False)).action,'keep_candidate')

    def test_slow_red_requires_opt_in_and_scores_are_separate(self):
        item = Equipment(**observation(rarity="red", preferred_use="slow_dps", game_score=99,
            stats={"atk_pct": 8, "crit": 5, "cdmg": 7, "hp_pct": 8}))
        self.assertEqual(evaluate(item).action, "review")
        decision = evaluate(item, Policy(allow_draft_quality_rules=True))
        self.assertEqual(decision.action, "continue")
        self.assertEqual(decision.game_score, 99)
        self.assertEqual(decision.weighted_score, 31.375)
        self.assertEqual(decision.effective_scores["slow_dps"], 31.375)

    def test_quality_cannot_rescue_low_speed_purple(self):
        item = Equipment(**observation(enhancement=9, preferred_use="crit_dps",
            stats={"speed": 11, "crit": 5, "atk_pct": 16}))
        decision = evaluate(item, Policy(allow_draft_quality_rules=True))
        self.assertEqual(decision.action, "store")
        self.assertFalse(any(route.startswith('quality:') for route in decision.routes))

    def test_purple_speed_scope_and_user_target_do_not_bypass_speed_gate(self):
        for speed,expected in ((11,'store'),(12,'continue')):
            item=Equipment(**observation(enhancement=9,stats={'speed':speed},
                                         observation_scope='purple_speed',user_target=True))
            self.assertEqual(evaluate(item,Policy(allow_draft_quality_rules=True)).action,expected)
        with self.assertRaises(ValueError):
            Equipment(**observation(rarity='red',stats={'speed':12},observation_scope='purple_speed'))

    def test_speed_only_observation_does_not_report_incomplete_quality_scores(self):
        item = Equipment(**observation(enhancement=9, stats={'speed':12},
                                       observation_scope='purple_speed'))
        decision = evaluate(item)
        self.assertEqual(decision.action, 'continue')
        self.assertIsNone(decision.weighted_score)
        self.assertEqual(decision.effective_scores, {})
        self.assertIsNone(decision.game_score)

        complete = Equipment(**observation(stats={'speed':2, 'crit':3, 'atk_pct':4}))
        self.assertEqual(evaluate(complete).weighted_score, 12.5)

    def test_missing_game_score_not_zero_or_pass(self):
        item = Equipment(**observation(rarity="red", stats={"atk_pct": 8, "crit": 5, "cdmg": 7, "hp_pct": 8}))
        policy = Policy(allow_draft_quality_rules=True, game_score_formula_confirmed=True,
                        game_score_gates={"0": 28})
        self.assertEqual(evaluate(item, policy).action, "review")

    def test_unconfirmed_or_invalid_input_is_not_executed(self):
        self.assertEqual(evaluate(Equipment(**observation(recognition_ok=False))).action, "review")
        self.assertEqual(evaluate(Equipment(**observation(level=88)),
                                  Policy(ignore_equipment_level=False)).action, "review")
        for changes in [dict(game_score=float("nan")), dict(reforged_speed=20),
                        dict(stats={"speed": 2.5}), dict(recognition_ok="true")]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Equipment(**observation(**changes))
        with self.assertRaises(ValueError):
            Policy(game_score_gates={"9": 60})

    def test_fixed_values_are_not_silently_penalized(self):
        item = Equipment(**observation(rarity="red", stats={"atk_flat": 40, "hp_pct": 8, "def_pct": 8, "crit": 3}))
        self.assertEqual(evaluate(item).action, "review")

    def test_replay_rejects_wrong_equipment_or_shortfall_or_regression(self):
        first = observation()
        variants = [observation(equipment_id="other", enhancement=3),
                    observation(enhancement=2),
                    observation(enhancement=3, stats={"speed": 1, "crit": 3, "atk_pct": 4})]
        for second in variants:
            with self.subTest(second=second), self.assertRaises(ValueError):
                replay([first, second], Policy())

    def test_replay_uses_actual_level_when_result_exceeds_target(self):
        records = [observation(enhancement=3,stats={'speed':8,'crit':3,'atk_pct':4}),
                   observation(enhancement=7,stats={'speed':8,'crit':3,'atk_pct':4})]
        decisions = replay(records, Policy())
        self.assertEqual(decisions[-1]["action"], "continue")
        self.assertEqual(decisions[-1]["target_level"], 9)
        self.assertTrue(any("实际+7" in reason for reason in decisions[-1]["reasons"]))

    def test_replay_pauses_if_extra_stat_checkpoint_was_crossed(self):
        decisions = replay([observation(), observation(enhancement=6)], Policy())
        self.assertEqual(decisions[-1]["action"], "review")
        self.assertIsNone(decisions[-1]["target_level"])

    def test_replay_stops_on_store(self):
        records = [observation(enhancement=9, stats={"speed": 11, "crit": 3, "atk_pct": 4}),
                   observation(equipment_id="must-not-be-read", enhancement=12)]
        decisions = replay(records, Policy())
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["action"], "store")


if __name__ == "__main__":
    unittest.main()
