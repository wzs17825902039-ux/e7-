"""在无Python PATH、无项目工作目录的环境验收实际exe，不发送游戏输入。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--exe',type=Path,default=root/'dist/第七史诗打铁助手.exe')
parser.add_argument('--output',type=Path,default=root/'runs/client-release-check')
args=parser.parse_args()
exe=args.exe.resolve()
output=args.output.resolve()
output.mkdir(parents=True,exist_ok=True)
checks=[]
with tempfile.TemporaryDirectory(prefix='e7-client-release-') as temporary:
    folder=Path(temporary)
    standalone=folder/exe.name
    shutil.copy2(exe,standalone)
    env=dict(os.environ)
    env.pop('PYTHONHOME',None)
    env.pop('PYTHONPATH',None)
    system32=Path(os.environ['SystemRoot'])/'System32'
    env['PATH']=os.pathsep.join(map(str,[system32,system32/'WindowsPowerShell/v1.0']))
    env['LOCALAPPDATA']=str(folder/'user-data')
    def run(arguments):
        process=subprocess.run([str(standalone),*map(str,arguments)],cwd=folder,env=env,
                               capture_output=True,timeout=120)
        if process.returncode:
            raise RuntimeError(f'客户端退出码：{process.returncode}')
    run(['--diagnose',output/'diagnostics.json'])
    diagnostics=json.loads((output/'diagnostics.json').read_text(encoding='utf-8'))
    checks.append({'name':'独立exe运行时和模型自检','ok':diagnostics['ok']})
    run(['--ui-smoke-test',output/'ui.json'])
    ui=json.loads((output/'ui.json').read_text(encoding='utf-8'))
    checks.append({'name':'任务导航和帮助弹窗启动渲染','ok':ui['gui_ready'] and
                   [page['title'] for page in ui['pages']]==['任务','设置','运行记录'] and ui['help_popup']
                   and ui.get('engine')=='WebView2' and len(ui.get('settings_categories',[]))==7
                   and all(ui.get('compact_layout',{}).values()) and not ui['errors']})
    run(['--ui-form-test',output/'forms.json'])
    forms=json.loads((output/'forms.json').read_text(encoding='utf-8'))
    checks.append({'name':'真实WebView表单保存、预设备份与小窗口布局','ok':forms['gui_ready']
                   and all(forms.get('compact_layout',{}).values()) and not forms['errors']})
    run(['--inspect-image',root/'captures/trial-plus9-after.png',output/'image.json'])
    image=json.loads((output/'image.json').read_text(encoding='utf-8'))
    truth=json.loads((root/'examples/live-armor-replay.json').read_text(encoding='utf-8'))[-1]
    fields=['rarity','slot','level','enhancement','game_score','stats']
    mismatches={key:{'expected':truth[key],'actual':image['fields'].get(key)}
                for key in fields if truth[key]!=image['fields'].get(key)}
    checks.append({'name':'打包后Windows OCR实际游戏截图','ok':not mismatches and not image['issues'],
                   'mismatches':mismatches,'issues':image['issues']})
report={'exe':str(exe),'bytes':exe.stat().st_size,
        'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
        'isolated_from_project':True,'python_on_path':False,'live_input':False,
        'checks':checks,'ok':all(c['ok'] for c in checks)}
(output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(int(not report['ok']))
