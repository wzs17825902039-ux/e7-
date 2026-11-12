from dataclasses import asdict,replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from e7_assistant.batch_recovery import settle_submitted_enhancement
from e7_assistant.disposal_guard import BatchEnhancementGuard,DisposalGuard,CraftSessionGuard
from e7_assistant.enhancement_statistics import EnhancementStatistics
from e7_assistant.rules import Equipment,Policy
from e7_assistant.tasks import Journal,Limits,Ledger,TaskControl
from e7_assistant.workflow import BatchItem


class EnhancementRecoveryTests(unittest.TestCase):
    def fixture(self,directory):
        runs=Path(directory)/'runs';prior=runs/'prior';prior.mkdir(parents=True)
        image=prior/'confirm.png'
        before=[BatchItem('0',Equipment('original','red',None,12,'helmet',
            {'speed':10,'atk_pct':20,'crit':8,'cdmg':15},True,True,red_speed_misses=1),True,False)]
        current=[replace(before[0],equipment=replace(before[0].equipment,enhancement=15,
            stats={**before[0].equipment.stats,'speed':14}),selected=False)]
        guard=BatchEnhancementGuard(runs/'enhancement-pending','test')
        operation=guard.begin('batch_enhance',{'items':[asdict(item) for item in before],
            'resources':None,'inventory_context':['100/1200','最大强化']},
            {'target':15,'cost':None,'image':str(image)},prior)
        events=[{'kind':'batch_enhance_commit_intent','target':15,'image':str(image)}]
        (prior/'events.jsonl').write_text('\n'.join(map(json.dumps,events)),encoding='utf8')
        journal=Journal(runs/'recovery')
        screen=SimpleNamespace(page='batch_enhancement',source='live.png')
        nav=SimpleNamespace(directory=journal.directory,last_image='live.png',read=Mock(return_value=screen))
        task=SimpleNamespace(navigator=nav,enhancement_guard=guard,
            disposal_guard=DisposalGuard(runs/'disposal-pending','test'),
            craft_guard=CraftSessionGuard(runs/'craft-pending','test'),policy=Policy(),
            journal=journal,control=TaskControl(),uncertain=False,completed_batches=0,
            ledger=Ledger(Limits()),untracked_enhancements=0,enhancement_statistics=EnhancementStatistics(),
            run_batch=Mock(return_value={'state':'complete'}),enhance_inventory_batches=Mock())
        resources=SimpleNamespace(has_preview=False)
        driver=SimpleNamespace(observe=Mock(return_value=(screen,current,resources)),
            observe_unchanged=Mock(return_value=(screen,current,resources)),
            unchanged=Mock(),same_resources=Mock(),commit_enhancement=Mock())
        return task,driver,before,current,operation,prior,events

    def test_verified_receipt_only_settles_and_returns_batch_without_resubmitting(self):
        with TemporaryDirectory() as directory:
            task,driver,before,current,operation,_,_=self.fixture(directory)
            with patch('e7_assistant.batch_enhancement.BatchEnhancementDriver',return_value=driver):
                result=settle_submitted_enhancement(task)
            self.assertEqual((result['state'],result['recovered_enhancements'],result['outcome_unknown']),('complete',1,False))
            self.assertIsNone(task.enhancement_guard.read())
            archive=json.loads((task.navigator.directory/'original-enhancement-pending.json').read_text(encoding='utf8'))
            self.assertEqual(archive['operation_id'],operation)
            task.run_batch.assert_not_called()
            task.enhance_inventory_batches.assert_not_called()
            self.assertEqual(task.last_batch[0].equipment.stats['speed'],14)
            self.assertEqual(task.last_batch[0].equipment.red_speed_misses,1)
            self.assertEqual(task.completed_batches,0)
            driver.commit_enhancement.assert_not_called()
            self.assertEqual(result['steps'],0)
            self.assertEqual(result['enhancement_statistics']['total14plus'],0)

    def test_wrong_page_failed_target_or_preview_never_clear_guard_or_continue(self):
        for case in ('wrong_page','target_not_reached','preview','record_changed','unstable'):
            with self.subTest(case=case),TemporaryDirectory() as directory:
                task,driver,before,current,operation,_,_=self.fixture(directory)
                if case=='wrong_page':task.navigator.read.return_value.page='inventory'
                if case=='target_not_reached':driver.observe.return_value=(task.navigator.read.return_value,before,SimpleNamespace(has_preview=False))
                if case=='preview':driver.observe.return_value[2].has_preview=True
                if case=='record_changed':
                    original=task.enhancement_guard.read
                    calls=[]
                    def read():
                        calls.append(1)
                        record=original()
                        return record if len(calls)==1 else {**record,'operation_id':'changed'}
                    task.enhancement_guard.read=read
                if case=='unstable':driver.unchanged.side_effect=ValueError('双帧不一致')
                with patch('e7_assistant.batch_enhancement.BatchEnhancementDriver',return_value=driver):
                    result=settle_submitted_enhancement(task)
                self.assertEqual(result['state'],'failed')
                self.assertTrue(result['outcome_unknown'])
                self.assertTrue(task.enhancement_guard.path.exists())
                task.run_batch.assert_not_called()
                driver.commit_enhancement.assert_not_called()

    def test_invalid_original_log_is_rejected_before_live_read(self):
        for kind in ('settled','batch_sale_commit_intent','batch_enhance_commit_intent'):
            with self.subTest(kind=kind),TemporaryDirectory() as directory:
                task,_,_,_,_,prior,events=self.fixture(directory)
                (prior/'events.jsonl').write_text('\n'.join(map(json.dumps,events+[{'kind':kind}])),encoding='utf8')
                with self.assertRaises(ValueError):settle_submitted_enhancement(task)
                task.navigator.read.assert_not_called()
                self.assertTrue(task.enhancement_guard.path.exists())
