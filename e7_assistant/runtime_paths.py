"""分离只读程序资源与冻结客户端的可写用户数据。"""
import os
from pathlib import Path
import sys


def resource_root():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))


def default_workspace():
    if getattr(sys,'frozen',False):
        base = Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))
        return base/'E7ForgeAssistant'
    return Path(__file__).resolve().parents[1]
