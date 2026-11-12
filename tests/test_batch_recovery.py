import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from e7_assistant.batch_recovery import recover_unsubmitted_batch
from e7_assistant.batch_recovery import historical_survivor_frames


class RecoveryTests(unittest.TestCase):
    def test_unrelated_truncated_log_does_not_break_valid_sale_evidence(self):
        with TemporaryDirectory() as root:
            broken=Path(root)/'desktop-broken';broken.mkdir()
            (broken/'events.jsonl').write_text('{"kind":',encoding='utf8')
            valid=Path(root)/'desktop-valid';valid.mkdir()
            frames=[str(valid/'a.png'),str(valid/'b.png')]
            (valid/'events.jsonl').write_text(json.dumps({'kind':'batch_sale_survivors_verified',
                'operation_id':'sale-op','images':frames,'time':'2026-11-12T19:00:00'}),encoding='utf8')
            with patch('e7_assistant.workflow_screen.inspect_screen',side_effect=lambda path:path):
                self.assertEqual(historical_survivor_frames(root,'sale-op'),frames)

    def test_corrupt_log_mentioning_same_sale_is_not_ignored(self):
        with TemporaryDirectory() as root:
            broken=Path(root)/'desktop-broken';broken.mkdir()
            (broken/'events.jsonl').write_text('{"operation_id":"sale-op",',encoding='utf8')
            with self.assertRaises(ValueError):historical_survivor_frames(root,'sale-op')

    def test_sale_survivor_evidence_in_original_desktop_run_is_reused(self):
        for mutation in (False,True):
            with self.subTest(mutation=mutation),TemporaryDirectory() as root:
                directory=Path(root)/'desktop-test';directory.mkdir()
                frames=[str(directory/'a.png'),str(directory/'b.png')]
                events=[{'kind':'batch_sale_survivors_verified','operation_id':'sale',
                         'images':frames,'time':'2026-11-12T18:35:46'},
                        {'kind':'navigation_intent','action':'inventory_from_batch'},
                        {'kind':'workflow_screen','page':'home'},
                        {'kind':'workflow_auto_recovery','operation':'sale'}]
                if mutation:events.append({'kind':'batch_sale_commit_intent'})
                (directory/'events.jsonl').write_text('\n'.join(map(json.dumps,events)),encoding='utf8')
                with patch('e7_assistant.workflow_screen.inspect_screen',side_effect=lambda path:path):
                    if mutation:
                        with self.assertRaises(ValueError):historical_survivor_frames(root,'sale')
                    else:self.assertEqual(historical_survivor_frames(root,'sale'),frames)

    def test_home_recovery_only_navigates_then_requires_original_sale_settlement(self):
        from e7_assistant.batch_recovery import settle_submitted_sale
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        from e7_assistant.tasks import Journal
        from dataclasses import asdict
        for page in ('home','home_menu'):
            with self.subTest(page=page),TemporaryDirectory() as root:
                runs=Path(root);original=runs/'original';original.mkdir()
                (original/'events.jsonl').write_text('\n'.join(map(json.dumps,[
                    {'kind':'workflow_screen','page':'batch_enhancement','image':'reference.png'},
                    {'kind':'batch_sale_commit_intent','operation_id':'sale'}])),encoding='utf8')
                item=BatchItem('0',Equipment('0','purple',85,3,'helmet',{'speed':3},True,True),False,False)
                record={'action':'sell','operation_id':'sale','run_directory':str(original),
                    'before':{'items':[asdict(item)],'rejected':['0'],'resources':None,'inventory_count':10,'capacity':1200},
                    'confirmation':{'count':1,'gold':100,'powder':5,'digest':'x','image':'x','jewelry_powder':0}}
                nav=Mock(directory=runs/'new',last_image='inventory.png')
                nav.read.return_value=SimpleNamespace(page=page,source='home.png')
                nav.navigate.return_value=SimpleNamespace(page='inventory',source='inventory.png')
                task=Mock(navigator=nav,journal=Journal(runs/'new'),completed_batches=0)
                task.ledger.steps=0
                task.disposal_guard.read.return_value=record
                task.enhancement_statistics.snapshot.return_value={}
                with patch('e7_assistant.batch_sale.BatchSaleDriver') as sale:
                    sale.return_value.settle_result.side_effect=ValueError('背包数量不匹配')
                    result=settle_submitted_sale(task)
                nav.navigate.assert_called_once_with('inventory')
                sale.return_value.settle_result.assert_called_once()
                task.disposal_guard.settle.assert_not_called()
                task.enhance_inventory_batches.assert_not_called()
                self.assertEqual(result['state'],'failed')
                self.assertTrue(result['outcome_unknown'])

    def test_verified_sale_receipt_does_not_scan_or_count_a_batch_itself(self):
        from e7_assistant.batch_recovery import settle_submitted_sale
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        from e7_assistant.tasks import Journal
        from dataclasses import asdict
        with TemporaryDirectory() as root:
            runs=Path(root);original=runs/'original';original.mkdir()
            (original/'events.jsonl').write_text('\n'.join(map(json.dumps,[
                {'kind':'workflow_screen','page':'batch_enhancement','image':'reference.png'},
                {'kind':'batch_sale_commit_intent','operation_id':'sale'}])),encoding='utf8')
            item=BatchItem('0',Equipment('0','purple',85,3,'helmet',{'speed':3},True,True),False,False)
            record={'action':'sell','operation_id':'sale','run_directory':str(original),
                'before':{'items':[asdict(item)],'rejected':['0'],'resources':None,'inventory_count':10,'capacity':1200},
                'confirmation':{'count':1,'gold':100,'powder':5,'digest':'x','image':'x','jewelry_powder':0}}
            nav=Mock(directory=runs/'new',last_image='inventory.png')
            nav.read.return_value=SimpleNamespace(page='inventory',source='inventory.png')
            task=Mock(navigator=nav,journal=Journal(runs/'new'),completed_batches=0)
            task.ledger.steps=0;task.disposal_guard.read.return_value=record
            task.enhancement_statistics.snapshot.return_value={}
            with patch('e7_assistant.batch_sale.BatchSaleDriver') as sale:
                result=settle_submitted_sale(task)
            self.assertEqual(result['state'],'complete')
            sale.return_value.settle_result.assert_called_once()
            task.enhance_inventory_batches.assert_not_called()
            self.assertEqual(task.completed_batches,0)
            self.assertEqual(task.last_batch,[])
            events=[json.loads(line) for line in task.journal.path.read_text(encoding='utf8').splitlines()]
            self.assertEqual(events[-1]['kind'],'receipt_recovery_finished')
            self.assertNotIn('finished',[event['kind'] for event in events])

    def test_historical_receipt_requires_same_operation_two_frames_and_navigation_only(self):
        for case in ('valid','wrong_operation','single_frame','mutation','outside'):
            with self.subTest(case=case),TemporaryDirectory() as root:
                directory=Path(root)/'recovery-test';directory.mkdir()
                frames=[str(directory/'a.png'),str(directory/'b.png')]
                if case=='outside':frames[1]=str(Path(root)/'outside.png')
                events=[{'kind':'submitted_sale_receipt_recovery','operation_id':'other' if case=='wrong_operation' else 'sale'}]
                events += [{'kind':'workflow_screen','page':'batch_enhancement','image':p}
                           for p in frames[:1 if case=='single_frame' else 2]]
                events += [{'kind':'navigation_intent','action':'inventory','time':'2026-11-11T17:29:00'}]
                if case=='mutation':events.append({'kind':'batch_sale_commit_intent'})
                (directory/'events.jsonl').write_text('\n'.join(map(json.dumps,events)),encoding='utf8')
                with patch('e7_assistant.workflow_screen.inspect_screen',side_effect=lambda path:path):
                    if case=='valid':self.assertEqual(historical_survivor_frames(root,'sale'),frames)
                    else:
                        with self.assertRaises(ValueError):historical_survivor_frames(root,'sale')

    def test_submitted_sale_is_rejected_before_any_live_read(self):
        with TemporaryDirectory() as root:
            runs=Path(root)/'runs'
            previous=runs/'previous';previous.mkdir(parents=True)
            result=previous/'result.json'
            result.write_text(json.dumps({'state':'failed'}),encoding='utf8')
            events=[{'kind':'batch_entry_verified'}, {'kind':'disposal_intent'},
                    {'kind':'batch_sale_commit_intent'}]
            (previous/'events.jsonl').write_text('\n'.join(map(json.dumps,events)),encoding='utf8')
            task=SimpleNamespace(navigator=SimpleNamespace(directory=runs/'new'))
            with self.assertRaisesRegex(ValueError,'从未提交'):
                recover_unsubmitted_batch(task,result)

    def test_wrong_workspace_is_rejected(self):
        task=SimpleNamespace(navigator=SimpleNamespace(directory=Path('runs/new')))
        with self.assertRaisesRegex(ValueError,'本工作区'):
            recover_unsubmitted_batch(task,'other/result.json')

    def test_unsubmitted_recovery_returns_verified_items_without_consumption_or_scan(self):
        from dataclasses import asdict
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        from e7_assistant.tasks import Journal
        with TemporaryDirectory() as root:
            runs=Path(root);prior=runs/'prior';prior.mkdir()
            item=BatchItem('0',Equipment('gear','red',85,3,'helmet',{'speed':4},True,True),False,False)
            data=asdict(item)
            result=prior/'result.json';result.write_text(json.dumps({'state':'failed'}),encoding='utf8')
            events=[{'kind':'batch_entry_verified','equipment':[data]},
                    {'kind':'equipment_decision',**data},
                    {'kind':'workflow_screen','page':'batch_enhancement','image':'before.png'},
                    {'kind':'disposal_intent','rejected':['0']}]
            (prior/'events.jsonl').write_text('\n'.join(map(json.dumps,events)),encoding='utf8')
            (prior/'selection-0001.json').write_text(json.dumps({'registered':[{}],
                'inventory_context':['10/1200','最大强化']}),encoding='utf8')
            screen=SimpleNamespace(page='batch_enhancement',source='current.png')
            nav=Mock(directory=runs/'new');nav.read.return_value=screen
            task=Mock(navigator=nav,journal=Journal(runs/'new'))
            task.driver.observe_unchanged.return_value=(screen,[item],SimpleNamespace(has_preview=False))
            with patch('e7_assistant.batch_recovery.inspect_selection_flags',return_value=[False]),\
                 patch('e7_assistant.batch_recovery.verify_stable_batch_pixels'):
                observed=recover_unsubmitted_batch(task,result)
            self.assertEqual(observed,[item]);self.assertEqual(task.last_batch,[item])
            task.run_batch.assert_not_called();task.enhance_inventory_batches.assert_not_called()
            nav.adb.tap.assert_not_called()
