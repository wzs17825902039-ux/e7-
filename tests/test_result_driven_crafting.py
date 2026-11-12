"""材料拒识不得阻塞已确认制作，未确认结果不得重发制作。"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import tempfile
import unittest

from e7_assistant.forge_loop import LiveForgeLoop,ForgePreview
from e7_assistant.legendary_crafting import LegendaryForgeLoop,observe_modal,observe_settlement,run_legendary,settle_legendary
from e7_assistant.tasks import Journal,Ledger,Limits,TaskControl
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.disposal_guard import CraftSessionGuard
from tests.test_forge_loop import FakeForge


class ResultDrivenCraftingTests(unittest.TestCase):
    def test_default_forge_and_legendary_preview_never_read_material(self):
        for cls in (LiveForgeLoop,LegendaryForgeLoop):
            for tracking in (False,True):
                with self.subTest(cls=cls,tracking=tracking),tempfile.TemporaryDirectory() as tmp:
                    journal=Journal(Path(tmp)/'run')
                    nav=SimpleNamespace(adb=Mock(serial='preview'),control=Mock())
                    loop=cls(nav,WorkflowOptions(track_craft_consumption=tracking),Ledger(Limits()),nav.control,journal)
                    screen=SimpleNamespace(source='forge.png')
                    with patch('e7_assistant.forge_loop.verify_selection'),patch('e7_assistant.legendary_crafting.verify_selection'),\
                         patch('e7_assistant.forge_loop.number',side_effect=ValueError('拒识')) as normal,\
                         patch('e7_assistant.legendary_crafting.number',side_effect=ValueError('拒识')) as legendary:
                        preview=loop.preview(screen)
                    self.assertEqual((preview.resources,preview.cost,preview.verification),({},{},'result'))
                    self.assertEqual(normal.call_count+legendary.call_count,int(tracking))

    def test_modal_statistics_failure_does_not_retry_or_block(self):
        nav=SimpleNamespace(control=Mock(),read=Mock(),adb=Mock(),journal=Mock())
        screen=SimpleNamespace(page='legendary_craft_confirmation',source='modal.png',find=Mock())
        for tracking in (False,True):
            with patch('e7_assistant.legendary_crafting.verify_set_selection'),\
                 patch('e7_assistant.legendary_crafting.number',side_effect=ValueError('拒识')) as reader:
                self.assertEqual(observe_modal(nav,screen,'speed',{},track_material=tracking),(screen,{}))
            self.assertEqual(reader.call_count,int(tracking))
        nav.read.assert_not_called();nav.adb.tap.assert_not_called()

    def test_successful_result_does_not_require_material_delta(self):
        before={'verification':'result','charges':10,'resources':{'craft_material':1000},'cost':{'craft_material':40}}
        for charges in (9,10):
            final=ForgePreview({}, {},'helmet',1,0,'after.png','result')
            loop=SimpleNamespace(navigator=SimpleNamespace(control=Mock(),journal=Mock()))
            with patch('e7_assistant.legendary_crafting.read_charges',return_value=charges),\
                 patch('e7_assistant.legendary_crafting.auxiliary_material_match') as auxiliary:
                self.assertEqual(observe_settlement(loop,before,final,result_verified=True),(final,charges))
            auxiliary.assert_not_called()

    def test_unknown_result_only_uses_material_as_auxiliary_no_repeat(self):
        before={'verification':'result','charges':10}
        final=ForgePreview({}, {},'helmet',1,0,'after.png','result')
        for match in (False,True):
            nav=SimpleNamespace(control=Mock(),journal=Mock(),read=Mock(),adb=Mock())
            loop=SimpleNamespace(navigator=nav,preview=Mock(return_value=final))
            with patch('e7_assistant.legendary_crafting.read_charges',return_value=10),\
                 patch('e7_assistant.legendary_crafting.auxiliary_material_match',return_value=match) as auxiliary:
                if match:self.assertEqual(observe_settlement(loop,before,final,result_verified=False),(final,10))
                else:
                    with self.assertRaises(ValueError):observe_settlement(loop,before,final,result_verified=False)
            self.assertGreater(auxiliary.call_count,0)
            nav.adb.tap.assert_not_called()

    def test_normal_forge_material_ocr_is_not_required_even_with_statistics_enabled(self):
        for tracking,unknown in ((False,False),(True,False),(False,True)):
            with self.subTest(tracking=tracking,unknown=unknown),tempfile.TemporaryDirectory() as tmp:
                nav=FakeForge(unknown=unknown)
                journal=Journal(Path(tmp)/'run')
                ledger=Ledger(Limits(max_steps=10,craft_material=0))
                loop=LiveForgeLoop(nav,WorkflowOptions(track_craft_consumption=tracking),ledger,nav.control,journal)
                preview=ForgePreview({}, {},'helmet',10,0,'before.png','result')
                loop.configure=Mock(return_value=preview)
                loop.verify_confirmation=Mock()
                loop.settlement_preview=Mock(side_effect=ValueError('统计拒识'))
                if unknown:loop.auxiliary_result=Mock(side_effect=ValueError('结果与材料仍不明确'))
                with patch('e7_assistant.forge_loop.verify_selection'),\
                     patch('e7_assistant.forge_loop.number',side_effect=AssertionError('不应读取材料')):
                    result=loop.run()
                self.assertEqual(result['state'],'failed' if unknown else 'inventory_full',result)
                self.assertEqual(result['batches'],0 if unknown else 2)
                self.assertEqual(result['outcome_unknown'],unknown)
                self.assertEqual(nav.crafted,1 if unknown else 2)
                self.assertEqual(ledger.steps,0 if unknown else 2)
                self.assertEqual(bool(loop.guard.read()),unknown)
                self.assertEqual(result['spent']['craft_material'],0)

    def test_material_shortage_is_normal_end_not_retry_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            nav=FakeForge()
            read=nav.read
            def shortage():
                screen=read()
                if nav.page=='craft_confirmation':screen.words=[{'text':'材料不足','confidence':1}]
                return screen
            nav.read=shortage
            journal=Journal(Path(tmp)/'run')
            loop=LiveForgeLoop(nav,WorkflowOptions(),Ledger(Limits()),nav.control,journal)
            loop.configure=Mock(return_value=ForgePreview({}, {},'helmet',10,0,'before.png','result'))
            with patch('e7_assistant.forge_loop.verify_selection'):
                result=loop.run()
            self.assertEqual(result['state'],'resources_exhausted')
            self.assertEqual(nav.crafted,0)
            self.assertFalse(result['outcome_unknown']);self.assertIsNone(loop.guard.read())

    def test_missing_normal_result_uses_exact_material_delta_without_second_commit(self):
        for delta in (400,399):
            with self.subTest(delta=delta),tempfile.TemporaryDirectory() as tmp:
                nav=FakeForge(unknown=True)
                journal=Journal(Path(tmp)/'run')
                loop=LiveForgeLoop(nav,WorkflowOptions(),Ledger(Limits(max_steps=1)),nav.control,journal)
                loop.configure=Mock(return_value=ForgePreview({}, {},'helmet',10,0,'before.png','result'))
                loop.verify_confirmation=Mock()
                def number(screen,*args):
                    return '5000/400' if screen.source=='before.png' else f'{5000-delta}/400'
                with patch('e7_assistant.forge_loop.verify_selection'),\
                     patch('e7_assistant.workflow_screen.inspect_screen',return_value=SimpleNamespace(source='before.png')),\
                     patch('e7_assistant.forge_loop.number',side_effect=number) as reader:
                    result=loop.run()
                self.assertEqual(nav.crafted,1)
                self.assertEqual(result['state'],'budget_reached' if delta==400 else 'failed',result)
                self.assertEqual(result['outcome_unknown'],delta!=400)
                self.assertEqual(reader.call_count,2)

    def test_optional_statistics_records_observed_total_without_double_counting_steps(self):
        for after in (4200,4201):
            with self.subTest(after=after),tempfile.TemporaryDirectory() as tmp:
                nav=FakeForge()
                ledger=Ledger(Limits(max_steps=10,craft_material=0))
                loop=LiveForgeLoop(nav,WorkflowOptions(track_craft_consumption=True),ledger,nav.control,Journal(Path(tmp)/'run'))
                preview=ForgePreview({'craft_material':5000},{'craft_material':400},'helmet',10,0,'before.png','result')
                loop.configure=Mock(return_value=preview);loop.verify_confirmation=Mock()
                loop.settlement_preview=Mock(return_value=replace(preview,resources={'craft_material':after}))
                with patch('e7_assistant.forge_loop.verify_selection'):
                    result=loop.run()
                self.assertEqual(result['state'],'inventory_full')
                self.assertEqual(result['consumption_complete'],after==4200)
                self.assertEqual(ledger.steps,2)
                self.assertEqual(ledger.spent['craft_material'],800 if after==4200 else 0)

    def test_normal_recovery_uses_matching_archived_result_not_material(self):
        from e7_assistant.craft_recovery import settle_full_craft
        with tempfile.TemporaryDirectory() as tmp:
            original=Journal(Path(tmp)/'original');journal=Journal(Path(tmp)/'recovery')
            guard=CraftSessionGuard(Path(tmp)/'craft-pending','normal-recovery')
            before={'verification':'result','slot':'helmet','count':10,'source_index':0,
                    'resources':{},'cost':{},'image':str(original.directory/'before.png'),'confirmed_batches':0}
            operation=guard.begin('craft',before,{},original.directory)
            original.emit('craft_commit_intent',operation_id=operation)
            original.emit('craft_result_observed',operation_id=operation,image=str(original.directory/'after.png'))
            navigator=SimpleNamespace(directory=journal.directory,read=Mock(),adb=Mock())
            task=SimpleNamespace(craft_guard=guard,enhancement_guard=Mock(),disposal_guard=Mock(),
                navigator=navigator,options=WorkflowOptions(),ledger=Ledger(Limits()),journal=journal,
                run=Mock(return_value={'state':'complete'}),uncertain=True)
            with patch('e7_assistant.workflow_screen.inspect_screen',return_value=SimpleNamespace(page='craft_result')),\
                 patch('e7_assistant.forge_loop.number',side_effect=AssertionError('结果已确认，不应核账')):
                result=settle_full_craft(task)
            self.assertEqual(result['state'],'complete');self.assertIsNone(guard.read())
            self.assertEqual(task.ledger.steps,1);task.run.assert_called_once()
            navigator.read.assert_not_called();navigator.adb.tap.assert_not_called()

    def test_actual_legendary_run_completes_with_no_material_budget_or_observation(self):
        for tracking in (False,True):
            with self.subTest(tracking=tracking),tempfile.TemporaryDirectory() as tmp:
                journal=Journal(Path(tmp)/'run')
                screen=SimpleNamespace(page='legendary_craft_confirmation',source='modal.png',find=Mock(return_value={'center':(816,550)}))
                nav=SimpleNamespace(control=Mock(),adb=Mock(serial='result-test'),read=Mock(return_value=screen),last_image='after.png')
                loop=Mock()
                loop.wait_for.return_value=SimpleNamespace(page='legendary_craft_result')
                loop.settlement_preview.return_value=ForgePreview({}, {},'helmet',1,0,'after.png','result')
                preview={'verification':'result','state':'preview_ready','last_image':'modal.png',
                         'charges':10,'resources':{},'cost':{},'slot':'helmet','gear_set':'speed','source_index':0}
                with patch('e7_assistant.legendary_crafting.preview_legendary',return_value=preview),\
                     patch('e7_assistant.legendary_crafting.observe_modal',return_value=(screen,{})),\
                     patch('e7_assistant.legendary_crafting.wait_legendary_result'),\
                     patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop),\
                     patch('e7_assistant.legendary_crafting.read_charges',return_value=9):
                    result=run_legendary(nav,WorkflowOptions(legendary_count=1,track_craft_consumption=tracking),Ledger(Limits()),journal)
                self.assertEqual((result['state'],result['completed']),('complete',1),result)
                self.assertFalse(result['outcome_unknown']);self.assertEqual(nav.adb.tap.call_count,1)
                self.assertIsNone(CraftSessionGuard(Path(tmp)/'craft-pending','result-test').read())

    def test_new_legendary_recovery_does_not_require_material_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=Journal(Path(tmp)/'original');journal=Journal(Path(tmp)/'recovery')
            before={'verification':'result','source_index':0,'slot':'helmet','gear_set':'speed',
                    'charges':10,'resources':{},'cost':{},'last_image':str(original.directory/'modal.png')}
            guard=CraftSessionGuard(Path(tmp)/'craft-pending','recovery')
            operation=guard.begin('craft',{'mode':'legendary',**before},{},original.directory)
            original.emit('legendary_commit_intent',operation_id=operation,preview=before)
            screen=SimpleNamespace(page='forge')
            nav=SimpleNamespace(adb=Mock(serial='recovery'),read=Mock(return_value=screen),control=Mock())
            final=ForgePreview({}, {},'helmet',1,0,'after.png','result')
            loop=Mock();loop.configure.return_value=final;loop.preview.return_value=replace(final,image='second.png')
            with patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop),\
                 patch('e7_assistant.legendary_crafting.read_charges',return_value=9):
                result=settle_legendary(nav,WorkflowOptions(),Ledger(Limits()),journal)
            self.assertEqual(result['recovered'],1);self.assertEqual(result['actual'],{})
            self.assertIsNone(guard.read());nav.adb.tap.assert_not_called()
