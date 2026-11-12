"""显式实机验收：点击现代客户端自身按钮；导入本模块不会连接设备。"""
import json
from pathlib import Path
import threading
import time

from .desktop_api import DesktopApi
from .settings import Settings

TASK_FLAGS = {
    'inventory_only':'inventory', 'legendary_preview':'preview_legendary',
    'legendary_craft':'legendary', 'legendary_recover':'recover_legendary',
    'settle_submitted_sale':'recover_sale',
    'settle_submitted_enhancement':'recover_enhancement', 'settle_full_craft':'recover_craft',
}
BUTTONS = {
    'workflow':'打造并强化','inventory':'仅强化背包','legendary':'传说定向制作',
    'preview_legendary':'预览当前传说制作选项',
    'recover_sale':'核验出售并继续背包','recover_enhancement':'核验强化并继续背包',
    'recover_craft':'核验满包打造','recover_legendary':'核验传说制作',
}


def prepare(config):
    if any(flag in config and type(config[flag]) is not bool for flag in TASK_FLAGS):
        raise ValueError('验收任务开关必须为布尔值')
    if config.get('capture_only') or config.get('recovery_result'):
        raise ValueError('现代客户端验收不支持旧截图/未提交批次参数，请使用明确的任务入口')
    selected=[task for flag,task in TASK_FLAGS.items() if config.get(flag)]
    if len(selected)>1:
        raise ValueError('一次验收只能选择一种任务')
    task=selected[0] if selected else 'workflow'
    timeout=config.get('timeout_seconds',1800)
    if type(timeout) not in (int,float) or not 1<=timeout<=7200:
        raise ValueError('验收超时必须为1～7200秒')
    workspace=Path(config['workspace']).resolve()
    api=DesktopApi(workspace)
    if api.bootstrap()['load_error']:
        raise ValueError('工作区配置损坏，不能用验收配置覆盖')
    settings=api.bootstrap()['settings']
    for key in ('adb_path','serial'):
        if key in config:settings[key]=config[key]
    for key in ('policy','workflow','limits'):
        if key in config:settings[key].update(config[key])
    # 只预填窗口；仍由实际“开始”按钮校验、保存和连接。
    api._settings=Settings(**settings).validate()
    return api,task,float(timeout)


def assess(task,settings,result,pending):
    errors=[]
    if not isinstance(result,dict):return ['任务没有返回可核对结果']
    expected='preview_ready' if task=='preview_legendary' else 'complete'
    if result.get('state')!=expected:errors.append('任务未达到预期终态：'+str(result.get('state')))
    if result.get('outcome_unknown'):errors.append('仍有结果未知的提交')
    if pending:errors.append('仍存在待核验记录')
    if task=='workflow' and result.get('rounds',0)!=settings.workflow['rounds']:
        errors.append('实际完成轮数与要求不符')
    if task=='legendary':
        if settings.workflow['legendary_count'] is None:
            if result.get('remaining_charges')!=0:errors.append('传说制作次数尚未耗尽')
        elif result.get('completed',0)!=settings.workflow['legendary_count']:
            errors.append('实际制作件数与要求不符')
    return errors


class Acceptance:
    def __init__(self,output,task,timeout):
        self.output=Path(output).resolve()
        self.task=task
        self.timeout=timeout
        self.passed=False
        self._started=threading.Lock()

    def write(self,api,done=False,errors=None):
        import sys
        state=api.snapshot()
        data={'stage':('stop_requested' if state['busy'] else 'finished') if done else 'running','busy':state['busy'],
              'done':done,'engine':'WebView2','task':self.task,'live_input':True,
              'client_entry':'real_exe_webview_ui' if getattr(sys,'frozen',False) else 'real_source_webview_ui',
              'status':state['status'],'statistics':state['statistics'],
              'task_result':state['result'],'pending':api.pending(),'errors':errors or [],
              'acceptance_passed':self.passed if done else False}
        path=self.output if done else self.output.with_name(self.output.stem+'-progress.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        temporary.replace(path)

    def __call__(self,window,api):
        if not self._started.acquire(blocking=False):return
        errors=[]
        def click(selector,text):
            clicked=window.evaluate_js("(()=>{const b=Array.from(document.querySelectorAll("+
                json.dumps(selector)+")).find(b=>b.textContent.trim().startsWith("+
                json.dumps(text)+"));if(!b||b.disabled)return false;b.click();return true;})()")
            if not clicked:raise ValueError('客户端按钮不可用：'+text)
            time.sleep(.2)
        try:
            deadline=time.monotonic()+45
            while not window.evaluate_js("Boolean(document.querySelector('.app .sidebar'))"):
                if time.monotonic()>deadline:raise TimeoutError('客户端初始化超时')
                time.sleep(.2)
            if self.task in ('workflow','inventory','legendary'):
                click('.task-option',BUTTONS[self.task])
                click('.start-button','开始任务')
            else:
                click('.sidebar nav button','设置')
                click('.settings-nav button','高级与恢复')
                click('.settings-content button',BUTTONS[self.task])
            deadline=time.monotonic()+self.timeout
            last_write=0
            while True:
                state=api.snapshot()
                # 即使连接极快地失败，也须读取终态，不能无限等待 busy=true。
                if not state['busy'] and state['result'] is not None:break
                alert=window.evaluate_js("document.querySelector('.alert')?.textContent||''")
                if not state['busy'] and alert:raise ValueError(str(alert))
                if time.monotonic()>deadline:
                    api.stop()
                    raise TimeoutError('实机验收超时，已请求停止；不得自动重启或重复提交')
                if time.monotonic()-last_write>2:
                    self.write(api);last_write=time.monotonic()
                time.sleep(.2)
            errors=assess(self.task,api._settings,state['result'],api.pending())
            self.passed=not errors
        except Exception as exc:
            errors.append(str(exc))
        finally:
            self.write(api,True,errors)
            # 结束后保留同一客户端供人工复核；超时也不强杀尚在结算的任务。


def run(config_path,output_path):
    from .desktop import launch
    config=json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    api,task,timeout=prepare(config)
    acceptance=Acceptance(output_path,task,timeout)
    launch(api=api,on_loaded=acceptance)
    return int(not acceptance.passed)
