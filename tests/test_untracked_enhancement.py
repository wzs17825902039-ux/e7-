from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
from e7_assistant.batch_resources import inspect_untracked_resources
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal, Limits, TaskControl
from e7_assistant.workflow import WorkflowOptions, WorkflowTask


class UntrackedEnhancementTests(unittest.TestCase):
    def test_only_stage_pixels_read_no_resource_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'frame.png'
            image=Image.new('RGB',(1280,720),'black')
            ImageDraw.Draw(image).rectangle((225,652,241,657),fill='white')
            image.save(source)
            with patch('e7_assistant.local_ocr.read_local_regions',side_effect=AssertionError('不得读取资源')):
                resources=inspect_untracked_resources(SimpleNamespace(page='batch_enhancement',source=source))
            self.assertEqual(resources.target,6)
            self.assertTrue(resources.has_preview)
            self.assertIsNone(resources.available)
            self.assertIsNone(resources.gold_cost)

    def test_untracked_spend_does_not_enforce_resource_budgets_or_invent_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            driver=SimpleNamespace(resource_untracked=True,settle_enhancement=Mock())
            task=WorkflowTask(driver,WorkflowOptions(),Policy(),Limits(gold=0,powder=0),
                              TaskControl(),Journal(Path(directory)/'run'))
            preview=SimpleNamespace(cost=None,resources=None,image='preview.png')
            commit=Mock()
            result=task._spend('batch_enhance',lambda:preview,commit,
                               lambda p:{'resources':None,'image':'after.png'})
            self.assertIsNone(result['resources'])
            self.assertEqual(task.ledger.steps,1)
            self.assertEqual(task.untracked_enhancements,1)
            commit.assert_called_once_with(preview)
            driver.settle_enhancement.assert_called_once_with(preview)
            self.assertFalse(task.uncertain)

    def test_untracked_unknown_result_remains_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            task=WorkflowTask(SimpleNamespace(resource_untracked=True),WorkflowOptions(),Policy(),
                              Limits(),TaskControl(),Journal(Path(directory)/'run'))
            preview=SimpleNamespace(cost=None,resources=None,image='preview.png')
            commit=Mock()
            with self.assertRaises(TimeoutError):
                task._spend('batch_enhance',lambda:preview,commit,Mock(side_effect=TimeoutError()))
            self.assertTrue(task.uncertain)
            self.assertEqual(task.ledger.steps,0)
            commit.assert_called_once()
