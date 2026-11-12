from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from e7_assistant.locking import ensure_locks
from e7_assistant.rules import Equipment,Policy,evaluate
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import BatchItem,WorkflowOptions,WorkflowTask,verify_lock_update


def valuable(locked=False):
    item=Equipment('valuable','red',85,15,'helmet',{'speed':16,'crit':5,'atk_pct':8,'cdmg':7},
                   True,True,60,20,'game_preview')
    return BatchItem('0',item,False,locked)


class LockTests(unittest.TestCase):
    def test_only_unlocked_target_is_clicked_once(self):
        current=[valuable(),replace(valuable(True),token='1')]
        clicks=[]
        def tap(token):
            clicks.append(token)
            current[:]=[replace(item,locked=True) if item.token==token else item for item in current]
        with tempfile.TemporaryDirectory() as temporary:
            result=ensure_locks(list(current),{'0','1'},lambda:list(current),tap,TaskControl(),
                                Journal(Path(temporary)/'run'))
        self.assertEqual(clicks,['0'])
        self.assertTrue(all(item.locked for item in result))

    def test_unknown_state_never_toggles(self):
        clicks=[];items=[valuable(None)]
        with tempfile.TemporaryDirectory() as temporary,self.assertRaises(ValueError):
            ensure_locks(items,{'0'},lambda:items,clicks.append,TaskControl(),Journal(Path(temporary)/'run'))
        self.assertEqual(clicks,[])

    def test_unchanged_after_click_is_not_retried(self):
        clicks=[];items=[valuable(False)]
        with tempfile.TemporaryDirectory() as temporary,self.assertRaises(ValueError):
            ensure_locks(items,{'0'},lambda:items,clicks.append,TaskControl(),Journal(Path(temporary)/'run'))
        self.assertEqual(clicks,['0'])

    def test_unlocking_other_equipment_is_rejected(self):
        before=[valuable(False),replace(valuable(True),token='1')]
        after=[valuable(True),replace(valuable(False),token='1')]
        with self.assertRaises(ValueError):
            verify_lock_update(before,after,{'0'})

    def test_workflow_locks_keep_candidate_before_cleanup(self):
        class Driver:
            calls=[]
            def lock_items(self,items,targets):
                self.calls.append(targets)
                return [replace(item,locked=True) for item in items]
        driver=Driver();item=valuable(False)
        with tempfile.TemporaryDirectory() as temporary:
            task=WorkflowTask(driver,WorkflowOptions(),Policy(),Limits(),TaskControl(),Journal(Path(temporary)/'run'))
            after=task._lock_candidates([item],{'0':evaluate(item.equipment)})
        self.assertEqual(driver.calls,[{'0'}])
        self.assertTrue(after[0].locked)

    def test_current_speed_without_reforge_preview_reaches_verified_lock_flow(self):
        class Driver:
            def lock_items(self,items,targets):
                self.targets=targets
                return [replace(item,locked=True) for item in items]
        driver=Driver();item=valuable(False)
        item=replace(item,equipment=replace(item.equipment,reforged_speed=None,reforged_speed_source=None))
        with tempfile.TemporaryDirectory() as temporary:
            task=WorkflowTask(driver,WorkflowOptions(),Policy(),Limits(),TaskControl(),Journal(Path(temporary)/'run'))
            decision=evaluate(item.equipment)
            after=task._lock_candidates([item],{'0':decision})
        self.assertEqual(decision.routes,['speed_optional'])
        self.assertEqual(driver.targets,{'0'})
        self.assertTrue(after[0].locked)
