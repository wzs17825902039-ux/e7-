"""双击打开固定发行入口；无EXE时使用现代源码界面。"""
import os
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parent
CLIENT = ROOT / 'dist' / '第七史诗打铁助手.exe'
if CLIENT.is_file():
    subprocess.Popen([str(CLIENT)], cwd=ROOT)
    raise SystemExit

LOCAL_PYTHON = ROOT / '.venv' / 'Scripts' / 'pythonw.exe'
if LOCAL_PYTHON.is_file() and Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
    subprocess.Popen([str(LOCAL_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT)
    raise SystemExit
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from e7_assistant.desktop import launch
    launch(workspace=ROOT)
except Exception as exc:
    import ctypes
    ctypes.windll.user32.MessageBoxW(None,str(exc),'打铁助手启动失败',0x10)
