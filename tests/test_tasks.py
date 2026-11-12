from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from e7_assistant.rules import Equipment, Policy
from e7_assistant.tasks import EnhancementTask, Journal, Limits, Preview, Snapshot, TaskControl


def snapshot(enhancement=0, speed=3, gold=100000, powder=100):
    equipment = Equipment("gear-1", "purple", 85, enhancement, "armor",
                          {"speed": speed, "def_pct": 8, "crit": 3}, True, True, game_score=23)
    return Snapshot(equipment, "icon-1", {"gold": gold, "powder": powder, "lesser_stone": 0,
                                        "greater_stone": 0, "epic_stone": 0}, "frame.png")


class FakeDriver:
    def __init__(self):
        self.before = snapshot()
        self.after = snapshot(enhancement=3, speed=6, gold=98400, powder=99)
        self.commits = self.clears = 0
        self.cost = {"gold": 1600, "powder": 1}
        self.on_prepare = None
        self.result_error = None
        self.preview_identity = "icon-1"
        self.target_override = None

    def observe(self):
        return self.before

    def prepare(self, target, before):
        if self.on_prepare:
            self.on_prepare()
        return Preview(self.target_override or target, dict(self.cost), replace(before, identity=self.preview_identity))

    def commit(self, preview):
        self.commits += 1

    def wait_result(self, before, preview):
        if self.result_error:
            raise self.result_error
        return self.after

    def clear(self):
        self.clears += 1


class TaskBoundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.driver = FakeDriver()
        self.control = TaskControl()
        self.journal = Journal(Path(self.temporary.name) / "run")

    def run_task(self, limits=None):
        return EnhancementTask(self.driver, Policy(), limits or Limits(gold=2000, powder=2, max_steps=1),
                               self.control, self.journal).run()

    def test_one_step_consumption_is_verified_and_logged(self):
        result = self.run_task()
        self.assertEqual(result["state"], "limit_reached")
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["spent"]["gold"], 1600)
        self.assertEqual(self.driver.commits, 1)
        events = [json.loads(line) for line in self.journal.path.read_text(encoding="utf-8").splitlines()]
        kinds = [event["kind"] for event in events]
        self.assertLess(kinds.index("commit_intent"), kinds.index("result_observed"))
        self.assertIn("settled", kinds)

    def test_budget_shortfall_prevents_commit_and_clears_selection(self):
        result = self.run_task(Limits(gold=1599, powder=2, max_steps=1))
        self.assertEqual(result["state"], "failed")
        self.assertEqual(self.driver.commits, 0)
        self.assertEqual(self.driver.clears, 1)

    def test_stop_between_preview_and_commit(self):
        self.driver.on_prepare = self.control.stop
        self.assertEqual(self.run_task()["state"], "stopped")
        self.assertEqual(self.driver.commits, 0)
        self.assertEqual(self.driver.clears, 1)

    def test_stopped_task_does_not_observe_or_commit(self):
        self.control.stop()
        self.assertEqual(self.run_task()["state"], "stopped")
        self.assertEqual(self.driver.commits, 0)

    def test_unknown_result_is_never_retried(self):
        self.driver.result_error = TimeoutError("network timeout")
        result = self.run_task()
        self.assertEqual(self.driver.commits, 1)
        self.assertTrue(result["outcome_unknown"])
        self.assertEqual(self.driver.clears, 0)

    def test_equipment_change_prevents_commit(self):
        self.driver.preview_identity = "another-icon"
        self.assertEqual(self.run_task()["state"], "failed")
        self.assertEqual(self.driver.commits, 0)

    def test_target_mismatch_prevents_commit(self):
        self.driver.target_override = 9
        self.assertEqual(self.run_task()["state"], "failed")
        self.assertEqual(self.driver.commits, 0)

    def test_actual_cost_mismatch_is_recorded_then_stopped(self):
        self.driver.after.resources["powder"] = 98
        result = self.run_task()
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["spent"]["powder"], 2)
        self.assertEqual(self.driver.commits, 1)

    def test_rule_stop_does_not_register_or_consume(self):
        self.driver.before = snapshot(enhancement=9, speed=9)
        result = self.run_task()
        self.assertEqual(result["state"], "store")
        self.assertEqual(self.driver.commits, 0)
        self.assertEqual(result["spent"]["gold"], 0)

    def test_overshoot_within_checkpoint_is_accepted(self):
        self.driver.after.equipment.enhancement = 4
        self.assertEqual(self.run_task()["state"], "limit_reached")

    def test_extra_checkpoint_pauses_after_accounting(self):
        self.driver.after.equipment.enhancement = 6
        result = self.run_task()
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["spent"]["gold"], 1600)


if __name__ == "__main__":
    unittest.main()
