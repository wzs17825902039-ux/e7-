from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,Limits,TaskControl
from e7_assistant.workflow import WorkflowOptions
from test_workflow import FlowDriver


class LiveWorkflowTests(unittest.TestCase):
    def test_readonly_batch_refusal_retries_without_pending_or_user_action(self):
        from e7_assistant.batch_enhancement import BatchObservationError
        task=self.task()
        task.last_batch=['stable'];task.uncertain=False
        task._batch=Mock(side_effect=[BatchObservationError('短暂遮挡'),None])
        task.run_batch_with_recovery(['initial'])
        self.assertEqual(task._batch.call_count,2)
        self.assertEqual(task._batch.call_args.args[0],['stable'])
        self.assertTrue(task._batch.call_args.kwargs['resumed'])

    def test_submitted_sale_failure_recovers_internally_without_resale(self):
        task=self.task();task.last_batch=[]
        operation=task.disposal_guard.begin('sell',{}, {},self.nav.directory)
        task._batch=Mock(side_effect=TimeoutError('返回主页'))
        def recover(*args,**kwargs):
            self.assertEqual(kwargs,{})
            task.disposal_guard.settle(operation);task.uncertain=False
            return {'state':'complete'}
        with patch('e7_assistant.batch_recovery.settle_submitted_sale',side_effect=recover) as receipt:
            task.run_batch_with_recovery([])
        task._batch.assert_called_once();receipt.assert_called_once()
        self.assertIsNone(task.disposal_guard.read())
        self.assertEqual(task.completed_batches,0)

    def test_startup_recovery_counts_batch_once_and_continues_inventory(self):
        for kind in ('sale','enhancement'):
            with self.subTest(kind=kind):
                task=self.task();task.last_batch=[]
                task.recover_pending_batch=Mock(return_value=kind)
                task.run_batch_with_recovery=Mock()
                task.enhance_inventory_batches=Mock()
                result=task.run(inventory_only=True)
                self.assertEqual((result['state'],result['batches']),('complete',1))
                task.enhance_inventory_batches.assert_called_once()
                self.assertEqual(task.run_batch_with_recovery.call_count,int(kind=='enhancement'))

    def test_explicit_recovery_requires_requested_receipt_before_running(self):
        task=self.task();task.run=Mock(return_value={'state':'complete'})
        with self.assertRaises(ValueError):task.resume_pending_batch('sale')
        task.run.assert_not_called()
        operation=task.disposal_guard.begin('sell',{}, {},self.nav.directory)
        self.assertEqual(task.resume_pending_batch('sale'),{'state':'complete'})
        task.run.assert_called_once_with(inventory_only=True)
        task.disposal_guard.settle(operation)

    def test_user_stop_never_triggers_automatic_recovery(self):
        from e7_assistant.tasks import Cancelled
        task=self.task();task._batch=Mock(side_effect=Cancelled('停止'))
        task.recover_pending_batch=Mock()
        with self.assertRaises(Cancelled):task.run_batch_with_recovery([])
        task.recover_pending_batch.assert_not_called()

    def setUp(self):
        self.temporary=TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.journal=Journal(Path(self.temporary.name)/'runs'/'test')
        self.nav=SimpleNamespace(directory=self.journal.directory,adb=SimpleNamespace(serial='test'),
                                 navigate=Mock())
        self.driver=FlowDriver()
        self.driver.last_image=None
        self.forge_calls=[]
        self.selection_calls=[]
        self.cleanup_calls=[]
        self.forge_state='inventory_full'
        self.forge_unknown=False
        self.selection_complete=True
        self.cleanup_pending=False
        outer=self
        class Forge:
            def __init__(self,nav,options,ledger,control,journal):
                self.options,self.ledger=options,ledger
                outer.forge_calls.append(ledger)
            def run(self):
                if outer.forge_state!='inventory_full':
                    return {'state':outer.forge_state,'outcome_unknown':outer.forge_unknown}
                outer.driver.open_forge(self.options)
                preview=outer.driver.prepare_craft(self.options,False)
                self.ledger.check(preview.cost,preview.resources)
                outer.driver.commit_craft(preview)
                after=outer.driver.finish_craft(preview)
                self.ledger.settle(preview.resources,after['resources'],preview.cost)
                return {'state':'inventory_full','outcome_unknown':False}
        self.cleanup=SimpleNamespace(initial_cleanup=Mock(side_effect=self.clean),pending=False)
        for name,value in [('LiveForgeLoop',Forge),('BatchEnhancementDriver',Mock(return_value=self.driver)),
                           ('InitialCleanupDriver',Mock(return_value=self.cleanup)),
                           ('BatchSelectionDriver',Mock(return_value=SimpleNamespace(collect_pages=self.select))),
                           ('BatchEntryDriver',Mock(return_value=SimpleNamespace(enter=self.enter))),
                           ('ensure_ascending',Mock())]:
            patcher=patch('e7_assistant.live_workflow.'+name,value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def clean(self,action):
        self.cleanup_calls.append(action)
        return {'image':'clean.png','removed':0}

    def select(self,**kwargs):
        self.selection_calls.append(kwargs)
        self.batch=self.driver.collect_batch(kwargs['limit'],kwargs['max_pages'])
        return {'selected_count':len(self.batch),'registered':[],
                'source':'selection.png','scan_complete':self.selection_complete}

    def enter(self,selection):
        return {'source':'batch.png'},self.batch

    def task(self,**kwargs):
        return LiveWorkflowTask(self.nav,kwargs.get('options',WorkflowOptions(rounds=2)),Policy(),
            kwargs.get('limits',Limits(gold=100000,powder=30,craft_material=1000,max_steps=50)),
            TaskControl(),self.journal)

    def test_two_rounds_use_actual_batch_orchestrator_and_shared_ledger(self):
        task=self.task()
        result=task.run()
        self.assertEqual(result['state'],'complete')
        self.assertEqual((result['rounds'],result['batches'],result['steps']),(2,2,8))
        self.assertEqual(result['spent']['gold'],48000)
        self.assertEqual(self.driver.targets,[3,6,9,3,6,9])
        self.assertEqual(self.cleanup_calls,['extract','extract'])
        self.assertTrue(all(ledger is task.ledger for ledger in self.forge_calls))
        self.assertTrue(all(c=={'limit':16,'max_pages':200,'start_at_top':True} for c in self.selection_calls))
        self.assertEqual(self.driver.sales,[])

    def test_inventory_only_processes_existing_batch_without_forge_or_cleanup(self):
        result=self.task().run(inventory_only=True)
        self.assertEqual((result['state'],result['scope'],result['rounds'],result['batches']),
                         ('complete','inventory_only',0,1))
        self.assertEqual(self.forge_calls,[])
        self.assertEqual(self.cleanup_calls,[])
        self.assertNotIn('craft',self.driver.confirmations)
        self.assertEqual(self.driver.targets,[3,6,9])

    def test_budget_does_not_reset_after_first_round(self):
        task=self.task(limits=Limits(gold=25000,powder=30,craft_material=1000,max_steps=50))
        result=task.run()
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['rounds'],1)
        self.assertEqual(self.driver.confirmations.count('craft'),1)
        self.assertFalse(result['outcome_unknown'])

    def test_unknown_forge_stops_before_cleanup(self):
        self.forge_state='failed'
        self.forge_unknown=True
        result=self.task().run()
        self.assertEqual(result['state'],'failed')
        self.assertTrue(result['outcome_unknown'])
        self.assertEqual(self.cleanup_calls,[])
        self.nav.navigate.assert_not_called()

    def test_budget_stop_does_not_claim_round_completed(self):
        self.forge_state='budget_reached'
        result=self.task().run()
        self.assertEqual(result['state'],'budget_reached')
        self.assertEqual(result['rounds'],0)
        self.assertEqual(self.cleanup_calls,[])

    def test_incomplete_empty_scan_never_starts_next_round(self):
        self.selection_complete=False
        result=self.task().run()
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['rounds'],0)
        self.assertEqual(self.driver.round,1)
        self.assertEqual(result['batches'],1)

    def test_cleanup_unknown_preserves_unknown_result(self):
        self.cleanup.pending=True
        self.cleanup.initial_cleanup.side_effect=TimeoutError('未确认处置结果')
        result=self.task().run()
        self.assertTrue(result['outcome_unknown'])
        self.assertEqual(self.selection_calls,[])

    def test_pending_previous_confirmation_blocks_before_any_forge(self):
        for kind in ('enhancement_guard','disposal_guard','craft_guard'):
            task=self.task()
            guard=getattr(task,kind)
            action={'enhancement_guard':'batch_enhance','disposal_guard':'sell','craft_guard':'craft'}[kind]
            operation=guard.begin(action,{}, {},self.nav.directory)
            result=task.run()
            self.assertEqual(result['state'],'failed')
            self.assertEqual(self.forge_calls,[])
            self.nav.navigate.assert_not_called()
            self.assertIsNotNone(guard.read())
            guard.settle(operation)

    def test_new_batch_does_not_reuse_previous_lock_anchors(self):
        task=self.task()
        old=task.driver
        self.driver.open_forge(task.options)
        replacement=SimpleNamespace(last_image=None)
        with patch('e7_assistant.live_workflow.BatchEnhancementDriver',return_value=replacement):
            items=task.collect_batch()
        self.assertTrue(items)
        self.assertIs(task.driver,replacement)
        self.assertIsNot(task.driver,old)


if __name__=='__main__':
    unittest.main()
