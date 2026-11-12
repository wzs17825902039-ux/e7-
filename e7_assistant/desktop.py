"""React + WebView2 Windows 客户端；不在窗口打开时自动连接或操作游戏。"""
import json
from pathlib import Path
import threading
import time

from .desktop_api import DesktopApi
from .runtime_paths import resource_root


def launch(workspace=None,smoke_output=None,verify_forms=False,api=None,on_loaded=None):
    import webview
    from .desktop_instance import desktop_instance
    instance=desktop_instance()
    if not instance.acquire():
        if smoke_output or on_loaded:
            raise RuntimeError('已有助手窗口；请先关闭旧窗口，再进行指定版本的验收，避免启动多个客户端')
        return 0
    try:
        return _launch(webview,workspace,smoke_output,verify_forms,api,on_loaded)
    finally:
        instance.close()


def _launch(webview,workspace,smoke_output,verify_forms,api,on_loaded):
    temporary=None
    if verify_forms:
        import tempfile
        from .settings import Settings,save_settings
        temporary=tempfile.TemporaryDirectory(prefix='e7-web-forms-')
        workspace=Path(temporary.name)
        sample=Settings()
        sample.policy['custom_targets']=[{'name':'离线校验原组合','sets':['speed'],'stats':['crit']}]
        save_settings(workspace/'config/ui.json',sample)
    api=api or DesktopApi(workspace)
    index=resource_root()/'e7_assistant/assets/web/index.html'
    if not index.is_file():
        raise RuntimeError('前端资源尚未生成，请先在 frontend 目录执行 npm run build')
    window=webview.create_window('第七史诗 · 打铁助手',str(index),js_api=api,
                                width=1380,height=900,min_size=(1100,740),background_color='#111318')
    def closing():
        if api.snapshot()['busy']:
            api.stop()
            return False
        return True
    window.events.closing+=closing

    def smoke():
        output=Path(smoke_output)
        output.parent.mkdir(parents=True,exist_ok=True)
        report={'gui_ready':False,'engine':'WebView2','live_input':False,'pages':[],'settings_categories':[],
                'help_popup':False,'errors':[]}
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if window.evaluate_js("Boolean(document.querySelector('.app .sidebar'))"):
                    break
                time.sleep(.2)
            else:raise RuntimeError('前端未在45秒内完成本地初始化')
            def capture(name):
                time.sleep(.25)
                # GDI截图无法读取GPU合成的WebView内容，直接导出WebView2的渲染表面。
                from System import Action
                from System.IO import FileStream,FileMode
                from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
                stream=FileStream(str(output.with_name(name+'.png').resolve()),FileMode.Create)
                tasks=[]
                try:
                    window.native.webview.Invoke(Action(lambda:tasks.append(
                        window.native.webview.CoreWebView2.CapturePreviewAsync(
                            CoreWebView2CapturePreviewImageFormat.Png,stream))))
                    tasks[0].GetAwaiter().GetResult()
                finally:
                    stream.Dispose()
            for title in ('任务','设置','运行记录'):
                window.evaluate_js("Array.from(document.querySelectorAll('.sidebar nav button')).find(b=>b.textContent.trim()==="+json.dumps(title)+").click()")
                time.sleep(.2)
                report['pages'].append({'title':title,'heading':title,'width':window.width,'height':window.height})
                capture('web-'+title)
                if title=='设置':
                    for label in ('强化与上锁','主属性筛选','套装与词条','打造与速度','资源预算','设备连接','高级与恢复'):
                        window.evaluate_js("Array.from(document.querySelectorAll('.settings-nav button')).find(b=>b.textContent.trim().startsWith("+json.dumps(label)+")).click()")
                        time.sleep(.15)
                        report['settings_categories'].append({'title':label,'content':window.evaluate_js("document.querySelector('.settings-content').innerText")})
                        capture('web-settings-'+label)
            window.evaluate_js("document.querySelector('button[aria-label=\"帮助\"]').click()")
            time.sleep(.2)
            report['help_popup']=bool(window.evaluate_js("Boolean(document.querySelector('[role=dialog]'))"))
            capture('web-help')
            window.evaluate_js("document.querySelector('button[aria-label=\"关闭\"]').click()")
            window.resize(1100,740)
            time.sleep(.3)
            window.evaluate_js("document.querySelector('.sidebar nav button').click()")
            time.sleep(.2)
            report['compact_layout']=window.evaluate_js("""(()=>{
                const footer=document.querySelector('.controlbar').getBoundingClientRect();
                return {no_horizontal_overflow:document.documentElement.scrollWidth<=innerWidth,
                        controls_visible:footer.bottom<=innerHeight+1&&footer.top>=0};
            })()""")
            capture('web-compact')
            if verify_forms:
                def click_text(selector,text):
                    window.evaluate_js("Array.from(document.querySelectorAll("+json.dumps(selector)+")).find(b=>b.textContent.trim().startsWith("+json.dumps(text)+")).click()")
                    time.sleep(.2)
                click_text('.sidebar nav button','设置')
                click_text('.settings-nav button','套装与词条')
                click_text('button','添加组合')
                click_text('[role=dialog] button','确认组合')
                report['form_validation']=bool(window.evaluate_js("document.querySelector('.error-toast')?.textContent.includes('组合名称')"))
                window.evaluate_js("""(()=>{const input=document.querySelector('[role=dialog] input');
                    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'离线新增组合');
                    input.dispatchEvent(new Event('input',{bubbles:true}));})()""")
                time.sleep(.2)
                click_text('[role=dialog] .selectable button','反击')
                click_text('[role=dialog] .selectable button','生命%')
                click_text('[role=dialog] button','确认组合')
                click_text('.settings-heading button','保存修改')
                deadline=time.monotonic()+5
                while not (workspace/'config/backups').exists() and time.monotonic()<deadline:
                    time.sleep(.1)
                reloaded=DesktopApi(workspace).bootstrap()['settings']['policy']
                expected=[{'name':'离线校验原组合','sets':['speed'],'stats':['crit']},
                          {'name':'离线新增组合','sets':['counter'],'stats':['hp_pct']}]
                report['form_persistence']=reloaded['custom_targets']==expected and not reloaded['custom_targets_enabled']
                report['form_backup']=any(entry['rules']==expected[:1] for entry in api.preset_backups())
                capture('web-form-saved')
            report['gui_ready']=len(report['pages'])==3 and len(report['settings_categories'])==7 and report['help_popup']
            if verify_forms:
                report['gui_ready']=report['gui_ready'] and all(report.get(key) for key in ('form_validation','form_persistence','form_backup'))
        except Exception as exc:
            report['errors'].append(str(exc))
        finally:
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            window.destroy()
    if smoke_output:
        window.events.loaded+=lambda:threading.Thread(target=smoke,daemon=True).start()
    if on_loaded:
        window.events.loaded+=lambda:threading.Thread(target=on_loaded,args=(window,api),daemon=True).start()
    webview.start(gui='edgechromium',debug=False)
    if temporary:temporary.cleanup()
    return 0
