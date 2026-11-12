"""新界面桥接的离线集成检查；底层游戏入口均替换，不连接设备。"""
from contextlib import ExitStack
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from e7_assistant.desktop_api import DesktopApi
from e7_assistant.settings import Settings
from e7_assistant.tasks import TaskControl


class DesktopDispatchTests(unittest.TestCase):
    def test_each_ui_task_uses_only_its_requested_driver_and_saves_the_actual_result(self):
        routes={
            'workflow':'workflow', 'inventory':'workflow',
            'recover_sale':'recovery', 'recover_enhancement':'recovery',
            'recover_craft':'craft', 'legendary':'legendary',
            'preview_legendary':'preview', 'recover_legendary':'legendary_recovery',
        }
        targets={
            'craft':'e7_assistant.craft_recovery.settle_full_craft',
            'legendary':'e7_assistant.legendary_crafting.run_legendary',
            'preview':'e7_assistant.legendary_crafting.preview_legendary',
            'legendary_recovery':'e7_assistant.legendary_crafting.settle_legendary',
        }
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            settings=Settings(adb_path='offline-only',serial='offline-only')
            settings.workflow.update(legendary_set='speed',rounds=2,slot='ring')
            settings.policy['custom_targets']=[{'name':'离线组合','sets':['counter'],'stats':['hp_pct']}]
            api=DesktopApi(root)
            for task,expected in routes.items():
                with self.subTest(task=task),ExitStack() as stack:
                    navigator=stack.enter_context(patch('e7_assistant.workflow_navigation.WorkflowNavigator'))
                    workflow=stack.enter_context(patch('e7_assistant.live_workflow.LiveWorkflowTask'))
                    workflow.return_value.run.return_value={'state':'complete','driver':'workflow'}
                    workflow.return_value.resume_pending_batch.return_value={'state':'complete','driver':'recovery'}
                    calls={'workflow':workflow.return_value.run,'recovery':workflow.return_value.resume_pending_batch}
                    for name,target in targets.items():
                        calls[name]=stack.enter_context(patch(target,return_value={'state':'complete','driver':name}))
                    adb=Mock(name='offline-device')
                    control=TaskControl()
                    result=api._execute(task,settings,control,adb)
                    self.assertEqual(result,{'state':'complete','driver':expected})
                    self.assertEqual(sum(call.call_count for call in calls.values()),1)
                    calls[expected].assert_called_once()
                    adb.assert_not_called()
                    self.assertEqual(adb.method_calls,[])
                    actual_adb,directory,actual_control,journal=navigator.call_args.args
                    self.assertIs(actual_adb,adb)
                    self.assertIs(actual_control,control)
                    self.assertEqual(directory.parent,root/'runs')
                    self.assertEqual(json.loads((directory/'result.json').read_text(encoding='utf8')),result)
                    if expected in {'workflow','recovery','craft'}:
                        args=workflow.call_args.args
                        self.assertEqual(asdict(args[2]),settings.policy)
                        self.assertEqual(args[1].slot,'ring')
                        self.assertEqual(args[1].rounds,2)
                        if expected=='workflow':
                            calls[expected].assert_called_once_with(inventory_only=task=='inventory')
                        elif expected=='recovery':
                            calls[expected].assert_called_once_with('sale' if task=='recover_sale' else 'enhancement')
                        else:calls[expected].assert_called_once_with(workflow.return_value)
                    else:
                        workflow.assert_not_called()
                        self.assertEqual(calls[expected].call_args.args[1].legendary_set,'speed')

    def test_real_journal_events_reach_ui_statistics_and_logs_without_interrupting_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            from e7_assistant.tasks import Journal
            api=DesktopApi(temporary)
            journal=Journal(Path(temporary)/'runs'/'events',api._event)
            events=[
                ('workflow_stage',{'stage':'batch_evaluate'}),
                ('batch_entry_read_retry',{'attempt':2,'max_attempts':3}),
                ('custom_target_match',{'names':['输出组合'],'score':34.5,'action':'continue'}),
                ('enhancement_statistics',{'speed14':1,'speed15':2,'speed16plus':3,'total14plus':6}),
                ('workflow_batch_finished',{'batch':4}),
                ('round_finished',{'round':2}),
                ('legendary_craft_settled',{'completed':1}),
            ]
            for kind,data in events:journal.emit(kind,**data)
            state=api.snapshot()
            self.assertEqual(state['statistics']['total14plus'],6)
            self.assertEqual(state['last_match']['names'],['输出组合'])
            self.assertEqual(state['last_match']['score'],34.5)
            self.assertTrue(any('第 2 轮已完成'==entry['message'] for entry in state['logs']))
            self.assertEqual(len(journal.path.read_text(encoding='utf8').splitlines()),len(events))


if __name__=='__main__':unittest.main()
