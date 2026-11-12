"""实际批量驱动与工作流联测；仅替换截图解析与外部输入边界。"""
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_resources import BatchResources, MATERIALS
from e7_assistant.disposal_guard import BatchEnhancementGuard
from e7_assistant.rules import Equipment, Policy
from e7_assistant.tasks import Journal, Limits, TaskControl
from e7_assistant.workflow import BatchItem, WorkflowOptions, WorkflowTask


class NativeScene:
    def __init__(self, directory, failure=None):
        self.item = BatchItem('registered:0', Equipment('gear', 'purple', 85, 0,
            'helmet', {'speed':3, 'crit':5, 'atk_pct':7}, True, True, 25), True, False)
        self.balance = {'gold':100000, **{key:0 for key,_ in MATERIALS}}
        self.balance['powder'] = 100
        self.target = None
        self.frame = 0
        self.confirmations = []
        self.failure = failure
        self.control = TaskControl()
        self.control.wait = lambda seconds:self.control.checkpoint()
        self.journal = Journal(Path(directory)/'run')
        self.guard = BatchEnhancementGuard(Path(directory)/'pending', 'test-device')
        navigator = SimpleNamespace(read=self.read, control=self.control, journal=self.journal,
            directory=self.journal.directory, adb=SimpleNamespace(tap=self.tap))
        self.driver = BatchEnhancementDriver(navigator, self.cards, self.resources, self.guard)
        def selection_graph(expected,reference):
            if [i.selected for i in expected]!=[self.item.selected]:
                raise ValueError('选择图形不符')
            return self.read()
        self.driver.observe_selection_flags=selection_graph

    def read(self):
        self.frame += 1
        def find(label, region):
            return {'center':(1200,670) if label == '强化' else (int(label[1:-2])*10,670)}
        return SimpleNamespace(page='batch_enhancement', source=f'frame-{self.frame}', find=find)

    def cards(self, path, slots):
        return {'issues':[], 'slots':[{'state':'occupied'}]+[{'state':'empty'}]*15,
            'records':[{'index':0, 'equipment':asdict(self.item.equipment),
                        'selected':self.item.selected, 'locked':self.item.locked}]}

    def resources(self, screen):
        reserved = {key:0 for key,_ in MATERIALS}
        remaining = dict(self.balance)
        if self.target is not None:
            reserved['powder'] = 2
            remaining['powder'] -= 2
        return BatchResources(dict(self.balance), remaining, reserved,
            3200 if self.target is not None else 0, self.target, screen.source)

    def tap(self, x, y):
        if x == 1200:
            self.confirmations.append(self.target)
            if self.failure == 'input':
                raise TimeoutError('确认输入结果未知')
            if self.failure == 'timeout':
                return
            self.balance['gold'] -= 3201 if self.failure == 'cost' else 3200
            self.balance['powder'] -= 2
            self.item = replace(self.item, equipment=replace(self.item.equipment,
                enhancement=self.target, stats={**self.item.equipment.stats,
                                               'speed':min(9,3+self.target)}))
            if self.failure == 'selection':
                self.item = replace(self.item, selected=False)
            self.target = None
        elif x in (30,60,90,120,150):
            self.target = x//10
        else:
            self.item = replace(self.item, selected=not self.item.selected)

    def run(self, first=3, gold=20000):
        self.task = WorkflowTask(self.driver, WorkflowOptions(first_target=first), Policy(),
            Limits(gold=gold,powder=20), self.control, self.journal)
        return self.task.run_batch([self.item])


class BatchRuntimeTests(unittest.TestCase):
    def test_native_stages_stop_at_plus9_and_preserve(self):
        for first, stages in ((3,[3,6,9]), (6,[3,6,9])):
            with self.subTest(first=first), TemporaryDirectory() as folder:
                scene = NativeScene(folder)
                result = scene.run(first)
                self.assertEqual(result['state'], 'complete')
                self.assertEqual(result['scope'], 'batch_only')
                self.assertEqual(scene.confirmations, stages)
                self.assertEqual(result['spent']['gold'],3200*len(stages))
                self.assertEqual(result['spent']['powder'],2*len(stages))
                self.assertFalse(result['outcome_unknown'])
                self.assertFalse(result['items'][0]['selected'])
                self.assertEqual(result['items'][0]['equipment']['enhancement'],9)
                self.assertIsNone(scene.guard.read())

    def test_budget_prevents_confirm_and_creates_no_pending_record(self):
        with TemporaryDirectory() as folder:
            scene = NativeScene(folder)
            result = scene.run(gold=100)
            self.assertEqual(result['state'],'failed')
            self.assertFalse(result['outcome_unknown'])
            self.assertEqual(scene.confirmations,[])
            self.assertIsNone(scene.guard.read())

    def test_unknown_input_timeout_or_selection_change_prevents_retry(self):
        for failure in ('input','timeout','selection'):
            with self.subTest(failure=failure), TemporaryDirectory() as folder:
                scene = NativeScene(folder, failure)
                result = scene.run()
                self.assertEqual(result['state'],'failed')
                self.assertTrue(result['outcome_unknown'])
                self.assertEqual(scene.confirmations,[3])
                self.assertEqual(result['steps'],0)
                restarted = BatchEnhancementGuard(Path(folder)/'pending','test-device')
                with self.assertRaises(ValueError):
                    restarted.check_clear()

    def test_actual_mismatch_records_spend_and_retains_pending(self):
        with TemporaryDirectory() as folder:
            scene = NativeScene(folder,'cost')
            result = scene.run()
            self.assertEqual(result['state'],'failed')
            self.assertEqual(result['spent']['gold'],3201)
            self.assertEqual(result['steps'],1)
            self.assertTrue(result['outcome_unknown'])
            self.assertIsNotNone(scene.guard.read())

    def test_settlement_log_failure_retains_pending(self):
        with TemporaryDirectory() as folder:
            scene = NativeScene(folder)
            emit = scene.journal.emit
            def fail_settlement(kind, **data):
                if kind == 'settled':
                    raise OSError('模拟落盘失败')
                return emit(kind, **data)
            scene.journal.emit = fail_settlement
            result = scene.run()
            self.assertEqual(result['state'],'failed')
            self.assertEqual(result['spent']['gold'],3200)
            self.assertIsNotNone(scene.guard.read())
            self.assertEqual(scene.confirmations,[3])

    def test_user_stop_sends_no_input(self):
        with TemporaryDirectory() as folder:
            scene = NativeScene(folder)
            scene.control.stop()
            self.assertEqual(scene.run()['state'],'stopped')
            self.assertEqual(scene.confirmations,[])
            self.assertIsNone(scene.guard.read())
