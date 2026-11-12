from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock,patch

from e7_assistant.adb import Adb
from e7_assistant.desktop_acceptance import Acceptance,assess,prepare
from e7_assistant.settings import Settings,save_settings
from e7_assistant.desktop_api import DesktopApi
from e7_assistant.tasks import TaskControl


class DesktopAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.workspace=Path(self.temp.name)
        self.settings=Settings(adb_path='fake-adb',serial='fake-device')
        save_settings(self.workspace/'config/ui.json',self.settings)

    def tearDown(self):
        self.temp.cleanup()

    def config(self,**values):
        return {'workspace':str(self.workspace),**values}

    def test_prepare_preserves_policy_and_only_prefills_without_connecting_or_writing(self):
        before=(self.workspace/'config/ui.json').read_bytes()
        with patch('e7_assistant.desktop_api.Adb') as adb:
            api,task,timeout=prepare(self.config(inventory_only=True,workflow={'action_interval':.3}))
        adb.assert_not_called()
        self.assertEqual(task,'inventory')
        self.assertEqual(timeout,1800)
        self.assertEqual(api.bootstrap()['settings']['policy'],self.settings.policy)
        self.assertEqual(api.bootstrap()['settings']['workflow']['action_interval'],.3)
        self.assertEqual(before,(self.workspace/'config/ui.json').read_bytes())

    def test_incompatible_legacy_modes_and_multiple_tasks_are_rejected(self):
        for options in ({'capture_only':True},{'recovery_result':'x'},
                        {'inventory_only':True,'legendary_craft':True},{'timeout_seconds':0}):
            with self.subTest(options=options),self.assertRaises(ValueError):prepare(self.config(**options))

    def test_all_recovery_flags_map_to_explicit_modern_buttons(self):
        for flag,task in [('settle_submitted_sale','recover_sale'),
                          ('settle_submitted_enhancement','recover_enhancement'),
                          ('settle_full_craft','recover_craft'),('legendary_recover','recover_legendary')]:
            self.assertEqual(prepare(self.config(**{flag:True}))[1],task)

    def test_completion_requires_requested_rounds_and_no_unknown_or_pending(self):
        self.settings.workflow['rounds']=2
        self.assertEqual(assess('workflow',self.settings,{'state':'complete','rounds':2},[]),[])
        for result,pending in [({'state':'complete','rounds':1},[]),
                               ({'state':'complete','rounds':2,'outcome_unknown':True},[]),
                               ({'state':'complete','rounds':2},[{'type':'sale'}]),
                               ({'state':'budget_reached','rounds':2},[])]:
            self.assertTrue(assess('workflow',self.settings,result,pending))

    def test_preview_and_legendary_counts_are_verified(self):
        self.assertEqual(assess('preview_legendary',self.settings,{'state':'preview_ready'},[]),[])
        self.assertTrue(assess('legendary',self.settings,{'state':'complete','completed':0},[]))
        self.settings.workflow['legendary_count']=None
        self.assertEqual(assess('legendary',self.settings,{'state':'complete','completed':2,'remaining_charges':0},[]),[])
        self.assertTrue(assess('legendary',self.settings,{'state':'complete','completed':2,'remaining_charges':1},[]))

    def test_failed_fast_connection_produces_failure_and_never_reclicks_start(self):
        api=DesktopApi(self.workspace)
        api._state['result']={'state':'failed','message':'offline'}
        window=MagicMock()
        window.evaluate_js.return_value=True
        check=Acceptance(self.workspace/'acceptance.json','inventory',10)
        with patch('e7_assistant.desktop_acceptance.time.sleep'):
            check(window,api)
            calls=window.evaluate_js.call_count
            check(window,api)  # reload/loaded事件不得再次开始。
        self.assertEqual(window.evaluate_js.call_count,calls)
        self.assertEqual(sum('.start-button' in str(call) for call in window.evaluate_js.call_args_list),1)
        report=json.loads(check.output.read_text(encoding='utf8'))
        self.assertTrue(report['done'])
        self.assertFalse(report['acceptance_passed'])
        self.assertEqual(report['engine'],'WebView2')

    def test_desktop_connection_always_selects_isolated_port(self):
        api=DesktopApi(self.workspace)
        with patch('e7_assistant.desktop_api.Adb') as adb:
            adb.return_value.devices.return_value='fake-device device\n'
            api._connect(self.settings,TaskControl())
        self.assertEqual(adb.call_args.kwargs['server_port'],5039)

    def test_timeout_requests_stop_and_never_reports_acceptance_passed(self):
        api=DesktopApi(self.workspace)
        api._state['busy']=True
        api._control=TaskControl()
        window=MagicMock()
        window.evaluate_js.side_effect=lambda script: '' if '.alert' in script else True
        check=Acceptance(self.workspace/'timeout.json','workflow',1)
        with patch('e7_assistant.desktop_acceptance.time.sleep'),\
             patch('e7_assistant.desktop_acceptance.time.monotonic',side_effect=[0,0,2]):
            check(window,api)
        self.assertTrue(api._control.stopped.is_set())
        report=json.loads(check.output.read_text(encoding='utf8'))
        self.assertFalse(report['acceptance_passed'])
        self.assertEqual(report['stage'],'stop_requested')
        self.assertEqual(sum('.start-button' in str(call) for call in window.evaluate_js.call_args_list),1)

    def test_adb_port_overrides_environment_without_mutating_parent_environment(self):
        with patch.dict('os.environ',{'ANDROID_ADB_SERVER_PORT':'5037','ADB_SERVER_SOCKET':'tcp:localhost:5038'}),\
             patch('e7_assistant.adb.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'',b'')) as run:
            Adb('fake-adb','fake-device',server_port=5039).devices()
            import os
            self.assertEqual(os.environ['ANDROID_ADB_SERVER_PORT'],'5037')
            self.assertIn('ADB_SERVER_SOCKET',os.environ)
        self.assertEqual(run.call_args.args[0][:3],['fake-adb','-P','5039'])
        self.assertEqual(run.call_args.kwargs['env']['ANDROID_ADB_SERVER_PORT'],'5039')
        self.assertNotIn('ADB_SERVER_SOCKET',run.call_args.kwargs['env'])

    def test_bad_server_port_is_rejected_before_subprocess(self):
        with patch('e7_assistant.adb.subprocess.run') as run:
            for port in (True,0,65536,'5039'):
                with self.assertRaises(ValueError):Adb(server_port=port)
        run.assert_not_called()


if __name__=='__main__':unittest.main()
