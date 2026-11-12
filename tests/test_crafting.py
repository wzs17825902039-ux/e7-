from pathlib import Path
import tempfile
import unittest

from e7_assistant.crafting import CraftPreview, CraftTask, parse_material
from e7_assistant.tasks import Journal, Limits, TaskControl


class Driver:
    def __init__(self):
        self.commits = 0

    def prepare(self):
        return CraftPreview({"gold": 100000, "craft_material": 100},
                            {"gold": 21000, "craft_material": 40}, "weapon", "preview.png")

    def commit(self, preview):
        self.commits += 1

    def wait_result(self, preview):
        raise TimeoutError("结果未知")


class CraftingTests(unittest.TestCase):
    def test_material_pair_is_strict(self):
        self.assertEqual(parse_material("275,883/40"), (275883, 40))
        for text in ("275,88i/40", "2758830", "100/0", "100/40(-1)"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_material(text)

    def run_task(self, driver, limits, control=None):
        with tempfile.TemporaryDirectory() as temporary:
            return CraftTask(driver, limits, control or TaskControl(),
                             Journal(Path(temporary) / "run")).run()

    def test_zero_budget_prevents_crafting(self):
        driver = Driver()
        result = self.run_task(driver, Limits(gold=0, craft_material=100))
        self.assertEqual(driver.commits, 0)
        self.assertFalse(result["outcome_unknown"])

    def test_material_budget_prevents_crafting(self):
        driver = Driver()
        self.run_task(driver, Limits(gold=50000, craft_material=39))
        self.assertEqual(driver.commits, 0)

    def test_unknown_result_is_not_retried(self):
        driver = Driver()
        result = self.run_task(driver, Limits(gold=50000, craft_material=100))
        self.assertEqual(driver.commits, 1)
        self.assertTrue(result["outcome_unknown"])

    def test_stopped_task_does_not_craft(self):
        driver = Driver()
        control = TaskControl()
        control.stop()
        result = self.run_task(driver, Limits(gold=50000, craft_material=100), control)
        self.assertEqual(driver.commits, 0)
        self.assertEqual(result["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
