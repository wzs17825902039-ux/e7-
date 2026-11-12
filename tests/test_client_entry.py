"""所有新旧启动入口统一到现代界面；不打开窗口或连接游戏。"""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


class ClientEntryTests(unittest.TestCase):
    def test_compatibility_imports_forward_to_modern_client(self):
        from e7_assistant import ui,desktop,client_live_test,desktop_acceptance
        self.assertIs(ui.launch,desktop.launch)
        self.assertIs(client_live_test.run,desktop_acceptance.run)

    def test_module_gui_uses_modern_client(self):
        from e7_assistant.__main__ import main
        with patch.object(sys,'argv',['e7_assistant','gui']),patch('e7_assistant.desktop.launch') as launch:
            self.assertEqual(main(),0)
        launch.assert_called_once_with()

    def test_exe_smoke_aliases_use_modern_client(self):
        path=Path(__file__).resolve().parents[1]/'客户端.py'
        spec=importlib.util.spec_from_file_location('client_entry',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for flag in ('--ui-smoke-test','--legacy-ui-smoke-test'):
            with self.subTest(flag=flag),patch.object(sys,'argv',['client.exe',flag,'offline.json']),\
                 patch('e7_assistant.desktop.launch',return_value=0) as launch:
                self.assertEqual(module.main(),0)
                launch.assert_called_once_with(smoke_output='offline.json')
