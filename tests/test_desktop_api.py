from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from e7_assistant.desktop_api import DesktopApi,desktop_workspace
from e7_assistant.rules import Policy
from e7_assistant.settings import Settings,load_settings,save_settings
from e7_assistant.tasks import Cancelled


class DesktopApiTests(unittest.TestCase):
    def test_legendary_retry_is_visible_and_failure_reason_is_preserved(self):
        self.api._event({'kind':'legendary_observation_retry','stage':'剩余次数',
                         'attempt':1,'max_attempts':3})
        self.assertIn('正在重读剩余次数',self.api.snapshot()['phase'])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.workspace=Path(self.temp.name)
        self.settings=Settings(adb_path='test-adb.exe',serial='test-device',policy=asdict(Policy()))
        save_settings(self.workspace/'config/ui.json',self.settings)
        self.api=DesktopApi(self.workspace)

    def tearDown(self):
        thread=self.api._thread
        if thread and thread.is_alive():
            self.api.stop();thread.join(3)
        self.temp.cleanup()

    def test_initialization_and_status_never_connect_or_write_settings(self):
        before=(self.workspace/'config/ui.json').read_bytes()
        with patch('e7_assistant.desktop_api.Adb') as adb:
            data=self.api.bootstrap()
            self.api.snapshot();self.api.pending();self.api.preset_backups()
            adb.assert_not_called()
        self.assertEqual(data['settings']['serial'],'test-device')
        self.assertEqual((self.workspace/'config/ui.json').read_bytes(),before)
        self.assertEqual(sum(map(len,data['catalog']['set_groups'])),18)

    def test_presets_are_saved_backed_up_reloaded_and_disabled_when_requested(self):
        value=asdict(self.settings)
        old=[{'name':'手动旧组合','sets':['speed'],'stats':['atk_pct','crit']}]
        value['policy']['custom_targets']=old
        self.assertTrue(self.api.save(value)['ok'])
        value['policy']['custom_targets']=[{'name':'新组合','sets':['counter'],'stats':['hp_pct','def_pct']}]
        self.assertTrue(self.api.save(value)['ok'])
        saved=load_settings(self.workspace/'config/ui.json')
        self.assertEqual(saved.policy['custom_targets'],value['policy']['custom_targets'])
        self.assertFalse(saved.policy['custom_targets_enabled'])
        candidates=self.api.preset_backups()
        self.assertTrue(any(entry['rules']==old for entry in candidates))
        self.assertEqual(DesktopApi(self.workspace).bootstrap()['settings']['policy']['custom_targets'],value['policy']['custom_targets'])

    def test_invalid_settings_do_not_replace_original_or_create_backups(self):
        original=(self.workspace/'config/ui.json').read_bytes()
        value=asdict(self.settings);value['policy']['custom_targets_enabled']=True
        self.assertFalse(self.api.save(value)['ok'])
        self.assertEqual((self.workspace/'config/ui.json').read_bytes(),original)
        self.assertFalse((self.workspace/'config/backups').exists())

    def test_import_validation_rejects_unknown_stats_without_mutating_configuration(self):
        before=(self.workspace/'config/ui.json').read_bytes()
        self.assertTrue(self.api.validate_presets([{'name':'组合','sets':['speed'],'stats':['hp_pct']}])['ok'])
        self.assertFalse(self.api.validate_presets([{'name':'组合','sets':['speed'],'stats':['unknown']}])['ok'])
        self.assertFalse(self.api.validate_presets([None])['ok'])
        self.assertEqual((self.workspace/'config/ui.json').read_bytes(),before)

    def test_corrupt_configuration_is_never_overwritten_with_defaults(self):
        path=self.workspace/'config/ui.json'
        path.write_text('{broken',encoding='utf8')
        api=DesktopApi(self.workspace)
        self.assertIsNotNone(api.bootstrap()['load_error'])
        self.assertFalse(api.save(asdict(self.settings))['ok'])
        self.assertEqual(path.read_text(encoding='utf8'),'{broken')

    def test_start_freezes_device_rules_and_parameters_and_rejects_second_job(self):
        gate=threading.Event();entered=threading.Event();seen=[]
        value=asdict(self.settings)
        def connect(settings,control):
            entered.set();gate.wait(2);return 'original-adb'
        def execute(task,settings,control,adb):
            seen.append((task,settings.serial,settings.workflow['slot'],settings.policy['retain_speed_min'],adb))
            return {'state':'complete'}
        with patch.object(self.api,'_connect',side_effect=connect),patch.object(self.api,'_execute',side_effect=execute):
            self.assertTrue(self.api.start('inventory',value)['ok']);self.assertTrue(entered.wait(1))
            value['serial']='other-device';value['workflow']['slot']='boots';value['policy']['retain_speed_min']=99
            self.assertFalse(self.api.start('workflow',value)['ok'])
            self.assertFalse(self.api.save(value)['ok'])
            gate.set();self.api._thread.join(3)
        self.assertEqual(seen,[('inventory','test-device',self.settings.workflow['slot'],16,'original-adb')])
        self.assertFalse(self.api.snapshot()['busy'])

    def test_stop_during_connection_prevents_game_execution(self):
        gate=threading.Event();entered=threading.Event()
        def connect(settings,control):
            entered.set();gate.wait(2);return object()
        with patch.object(self.api,'_connect',side_effect=connect),patch.object(self.api,'_execute') as execute:
            self.api.start('inventory',asdict(self.settings));self.assertTrue(entered.wait(1))
            self.api.stop();gate.set();self.api._thread.join(3)
            execute.assert_not_called()
        self.assertEqual(self.api.snapshot()['result']['state'],'stopped')

    def test_pause_resume_and_final_state_statistics(self):
        gate=threading.Event();entered=threading.Event()
        def execute(task,settings,control,adb):
            entered.set();gate.wait(2)
            return {'state':'complete','enhancement_statistics':{'speed14':1,'speed15':2,'speed16plus':3,'total14plus':6}}
        with patch.object(self.api,'_connect',return_value=object()),patch.object(self.api,'_execute',side_effect=execute):
            self.api.start('inventory',asdict(self.settings));self.assertTrue(entered.wait(1))
            self.api.pause();self.assertTrue(self.api.snapshot()['paused'])
            self.api.pause();self.assertFalse(self.api.snapshot()['paused'])
            gate.set();self.api._thread.join(3)
        self.assertEqual(self.api.snapshot()['statistics']['total14plus'],6)
        self.assertEqual(self.api.snapshot()['status'],'任务已完成')

    def test_failure_does_not_report_complete(self):
        with patch.object(self.api,'_connect',side_effect=ValueError('设备离线')),patch.object(self.api,'_execute') as execute:
            self.api.start('inventory',asdict(self.settings));self.api._thread.join(3)
            execute.assert_not_called()
        state=self.api.snapshot()
        self.assertEqual(state['result']['state'],'failed')
        self.assertIn('设备离线',state['phase'])

    def test_catalog_and_events_are_copied_and_logs_are_bounded(self):
        self.api._event({'kind':'enhancement_statistics','speed14':1,'speed15':0,'speed16plus':0,'total14plus':1})
        for i in range(260):self.api._event({'kind':'failed','message':str(i)})
        snap=self.api.snapshot();snap['statistics']['speed14']=99
        self.assertEqual(self.api.snapshot()['statistics']['speed14'],1)
        self.assertEqual(len(self.api.snapshot()['logs']),250)
        self.assertEqual(self.api.snapshot(self.api.snapshot()['cursor'])['logs'],[])

    def test_frozen_client_keeps_project_workspace_with_pending_receipts(self):
        project=self.workspace/'project';(project/'e7_assistant').mkdir(parents=True)
        save_settings(project/'config/ui.json',self.settings)
        executable=project/'dist/modern/assistant.exe'
        with patch('e7_assistant.desktop_api.default_workspace',return_value=self.workspace/'local-data'),\
             patch('sys.frozen',True,create=True),patch('sys.executable',str(executable)):
            self.assertEqual(desktop_workspace(),project)


if __name__=='__main__':unittest.main()
