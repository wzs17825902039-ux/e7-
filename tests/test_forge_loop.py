from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

from e7_assistant.forge_loop import ForgePreview,LiveForgeLoop
from e7_assistant.tasks import Journal,Ledger,Limits,TaskControl
from e7_assistant.workflow import WorkflowOptions


class FakeForge:
    def __init__(self,capacity=2,wrong_gold=False,wrong_material=False,unknown=False):
        self.control=TaskControl()
        self.control.wait=lambda seconds:self.control.checkpoint()
        self.adb=self
        self.serial='test-forge'
        self.page='forge';self.gold=2000000;self.material=5000;self.crafted=0
        self.capacity=capacity;self.wrong_gold=wrong_gold;self.wrong_material=wrong_material
        self.unknown=unknown;self.taps=[]

    def read(self):
        def find(label,region=None):
            points={'制作':(1167,670) if self.page=='forge' else (816,532),'重新制作':(831,654)}
            return {'center':points[label]}
        return SimpleNamespace(page=self.page,source='fake.png',find=find,
                               gold=self.gold,material=self.material)

    def navigate(self,target):
        self.page=target
        if self.wrong_material:
            self.material-=1
        return self.read()

    def tap(self,x,y):
        self.control.checkpoint()
        self.taps.append((x,y))
        if self.page=='forge':
            self.page='craft_confirmation'
            return
        if self.page=='craft_result':
            self.page='inventory_full' if self.crafted>=self.capacity else 'craft_confirmation'
            return
        self.crafted+=1;self.gold-=210001 if self.wrong_gold else 210000;self.material-=400
        self.page='unknown' if self.unknown else 'craft_result'


class ForgeLoopTests(unittest.TestCase):
    def test_configure_keeps_already_selected_parameters_without_clicks(self):
        with tempfile.TemporaryDirectory() as directory:
            nav=FakeForge()
            loop=LiveForgeLoop(nav,WorkflowOptions(),Ledger(Limits()),nav.control,Journal(Path(directory)/'run'))
            expected=Mock()
            loop.preview=Mock(return_value=expected)
            with patch('e7_assistant.forge_loop.verify_selection'):
                self.assertIs(loop.configure(),expected)
            self.assertEqual(nav.taps,[])

    def test_legendary_configuration_never_touches_normal_batch_count(self):
        with tempfile.TemporaryDirectory() as directory:
            nav=FakeForge()
            loop=LiveForgeLoop(nav,WorkflowOptions(),Ledger(Limits()),nav.control,Journal(Path(directory)/'run'))
            loop.preview=Mock()
            with patch('e7_assistant.forge_loop.verify_selection') as verify:
                loop.configure(select_count=False)
            self.assertEqual(nav.taps,[])
            self.assertEqual([call.kwargs['fields'] for call in verify.call_args_list],
                             [('source',),('slot',)])

    def test_settlement_missing_material_retries_read_only_but_conflict_does_not(self):
        for message,retry in (('material未可靠识别',True),('打造来源选中状态未确认',False)):
            with self.subTest(message=message),tempfile.TemporaryDirectory() as directory:
                forge=FakeForge()
                loop=LiveForgeLoop(forge,WorkflowOptions(),Ledger(Limits()),forge.control,Journal(Path(directory)/'run'))
                expected=ForgePreview({'craft_material':4200},{'craft_material':400},'helmet',10,0,'fake.png')
                loop.preview=Mock(side_effect=(ValueError(message),expected))
                if retry:self.assertEqual(loop.settlement_preview(),expected)
                else:
                    with self.assertRaises(ValueError):loop.settlement_preview()
                self.assertEqual(loop.preview.call_count,2 if retry else 1)
                self.assertEqual(forge.taps,[])

    def run_loop(self,forge=None,guard=None,track_gold=True,**limits):
        forge=forge or FakeForge()
        ledger=Ledger(Limits(gold=limits.get('gold',1000000),craft_material=2000,max_steps=10))
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'run')
            loop=LiveForgeLoop(forge,WorkflowOptions(track_craft_gold=track_gold),ledger,forge.control,journal,guard=guard)
            def preview(screen):
                resources={'craft_material':screen.material};cost={'craft_material':400}
                if track_gold:
                    resources['gold']=screen.gold;cost['gold']=210000
                return ForgePreview(resources,cost,'helmet',10,0,screen.source)
            loop.configure=lambda:preview(forge.read())
            loop.preview=preview
            loop.verify_confirmation=lambda screen,preview:None
            def number(screen,key,box,pattern=None,contrast=False):
                if not track_gold and key=='gold':raise AssertionError('免金币模式读取了金币')
                return str(screen.gold if key=='gold' else 210000)
            with patch('e7_assistant.forge_loop.number',side_effect=number):
                result=loop.run()
            events=journal.path.read_text(encoding='utf8')
        return result,forge,ledger,events

    def test_repeat_until_full_then_reconcile_actual_material_total(self):
        result,forge,ledger,events=self.run_loop()
        self.assertEqual(result['state'],'inventory_full')
        self.assertEqual(result['batches'],2)
        self.assertEqual(ledger.spent['gold'],420000)
        self.assertEqual(ledger.spent['craft_material'],800)
        self.assertEqual(ledger.steps,2)
        self.assertEqual(forge.taps,[(1167,670),(816,532),(831,654),(816,532),(831,654)])
        self.assertFalse(result['outcome_unknown'])
        self.assertIn('craft_session_settled',events)

    def test_budget_ends_before_next_repeat_and_reconciles(self):
        result,forge,ledger,_=self.run_loop(gold=210000)
        self.assertEqual(result['state'],'budget_reached')
        self.assertEqual(forge.crafted,1)
        self.assertEqual(ledger.steps,1)
        self.assertNotIn((831,654),forge.taps)

    def test_insufficient_budget_never_opens_confirmation(self):
        result,forge,ledger,_=self.run_loop(gold=1)
        self.assertEqual(result['state'],'budget_reached')
        self.assertEqual(forge.taps,[])
        self.assertEqual(ledger.steps,0)
        self.assertFalse(result['outcome_unknown'])

    def test_wrong_gold_stops_without_repeat_or_assumed_material_spend(self):
        result,forge,ledger,_=self.run_loop(FakeForge(wrong_gold=True))
        self.assertEqual(result['state'],'failed')
        self.assertTrue(result['outcome_unknown'])
        self.assertEqual(forge.crafted,1)
        self.assertEqual(ledger.spent['craft_material'],0)

    def test_unknown_result_is_not_retried(self):
        result,forge,ledger,_=self.run_loop(FakeForge(unknown=True))
        self.assertEqual(result['state'],'failed')
        self.assertTrue(result['outcome_unknown'])
        self.assertEqual(forge.crafted,1)
        self.assertEqual(len(forge.taps),2)

    def test_final_material_mismatch_is_failure_and_records_actual_spend(self):
        result,forge,ledger,_=self.run_loop(FakeForge(wrong_material=True))
        self.assertEqual(result['state'],'failed')
        self.assertEqual(ledger.spent['craft_material'],801)

    def test_unknown_confirmation_blocks_new_loop_before_inputs(self):
        from e7_assistant.disposal_guard import CraftSessionGuard
        with tempfile.TemporaryDirectory() as folder:
            guard=CraftSessionGuard(Path(folder),'test-forge')
            result,_,_,_=self.run_loop(FakeForge(unknown=True),guard=guard)
            self.assertTrue(result['outcome_unknown'])
            self.assertIsNotNone(guard.read())
            # 独立对象读取同一持久化记录，不依赖旧loop内存状态。
            restarted=CraftSessionGuard(Path(folder),'test-forge')
            result,forge,_,_=self.run_loop(guard=restarted)
            self.assertEqual(result['state'],'failed')
            self.assertEqual(forge.taps,[])

    def test_successful_reconciliation_clears_craft_session(self):
        from e7_assistant.disposal_guard import CraftSessionGuard
        with tempfile.TemporaryDirectory() as folder:
            guard=CraftSessionGuard(Path(folder),'test-forge')
            result,_,_,_=self.run_loop(guard=guard)
            self.assertEqual(result['state'],'inventory_full')
            self.assertIsNone(guard.read())

    def test_no_gold_mode_uses_repeat_confirmation_and_tracks_material_only(self):
        result,forge,ledger,_=self.run_loop(FakeForge(wrong_gold=True),track_gold=False,gold=0)
        self.assertEqual(result['state'],'inventory_full')
        self.assertEqual(forge.crafted,2)
        self.assertEqual(ledger.spent['gold'],0)
        self.assertEqual(ledger.spent['craft_material'],800)
        self.assertEqual(ledger.steps,2)
        self.assertFalse(result['outcome_unknown'])
