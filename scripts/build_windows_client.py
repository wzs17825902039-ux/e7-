"""用项目环境生成独立Windows exe；不打包个人配置、游戏截图或日志。"""
from pathlib import Path
import subprocess
import sys
import shutil

root=Path(__file__).resolve().parents[1]
npm=shutil.which('npm.cmd') or shutil.which('npm')
if not npm:
    raise SystemExit('构建现代客户端需要 Node.js / npm；请先安装前端依赖 npm ci')
subprocess.run([npm,'run','build'],check=True,cwd=root/'frontend')
subprocess.run([sys.executable,str(root/'scripts/build_client_branding.py')],check=True,cwd=root)
command=[sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed',
         '--name','第七史诗打铁助手','--icon',str(root/'e7_assistant/assets/branding/client.ico'),
         '--distpath',str(root/'dist'),'--workpath',str(root/'build/windows-client'),
         '--specpath',str(root/'build'),
         '--add-data',str(root/'e7_assistant/assets')+';e7_assistant/assets',
         '--add-data',str(root/'e7_assistant/windows_ocr.ps1')+';e7_assistant',
         '--add-data',str(root/'examples/live-armor-replay.json')+';examples',
         '--collect-all','rapidocr_onnxruntime','--collect-all','onnxruntime',
         '--collect-all','cv2',str(root/'客户端.py')]
subprocess.run(command,check=True,cwd=root)
