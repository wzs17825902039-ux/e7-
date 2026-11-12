"""Windows发行入口；默认打开UI；显式实机验收参数使用原生界面连接并启动任务。"""
import json
from pathlib import Path
import sys
import traceback


def main():
    if len(sys.argv)==4 and sys.argv[1]=='--live-ui-test':
        from e7_assistant.desktop_acceptance import run
        return run(sys.argv[2],sys.argv[3])
    if len(sys.argv)==4 and sys.argv[1]=='--inspect-image':
        from e7_assistant.vision import inspect_image
        report=inspect_image(sys.argv[2])
        Path(sys.argv[3]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0
    if len(sys.argv)==3 and sys.argv[1]=='--diagnose':
        from e7_assistant.client_diagnostics import diagnose
        report = diagnose()
        Path(sys.argv[2]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return int(not report['ok'])
    if len(sys.argv)==3 and sys.argv[1] in ('--ui-smoke-test','--legacy-ui-smoke-test'):
        from e7_assistant.desktop import launch
        return launch(smoke_output=sys.argv[2])
    if len(sys.argv)==3 and sys.argv[1]=='--ui-form-test':
        from e7_assistant.desktop import launch
        return launch(smoke_output=sys.argv[2],verify_forms=True)
    from e7_assistant.desktop import launch
    launch()
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        from e7_assistant.runtime_paths import default_workspace
        directory=default_workspace()
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,f'{exc}\n\n详情已保存到：{directory}/startup-error.log',
                                        '打铁助手启动失败',0x10)
        raise SystemExit(1)
