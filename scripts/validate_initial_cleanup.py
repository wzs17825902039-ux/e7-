"""只读取用户截图；不连接模拟器、不发送输入。"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from e7_assistant.initial_cleanup import inspect_confirmation, inspect_inventory, verify_cleanup
from e7_assistant.workflow_screen import inspect_screen


def main():
    root = Path(__file__).resolve().parents[1]
    assets = root/'docs/assets/user-workflow-2026-11-09'
    names = ['11-quick-select.png','12-disposal-options.png',
             '13-extract-confirmation.png','14-batch-menu.png']
    screens = [inspect_screen(assets/name) for name in names]
    before, selected, after = [inspect_inventory(screens[i]) for i in (0,1,3)]
    confirmation = inspect_confirmation(screens[2],'extract')
    assert (before.count,before.selected) == (1205,0)
    assert (selected.count,selected.selected) == (1205,143)
    assert (after.count,after.capacity,after.gold) == (1062,1200,343327724)
    result = verify_cleanup(selected,after,'extract')
    assert result['removed'] == 143
    report = {'scope':'用户图11至14离线回归；不证明实机驱动已执行或其他预设适配',
              'inputs':[{'file':name,'sha256':hashlib.sha256((assets/name).read_bytes()).hexdigest()}
                        for name in names],
              'before':asdict(before),'selected':asdict(selected),
              'confirmation':asdict(confirmation),'after':asdict(after),'result':result,
              'notice':'确认弹窗遮挡后的背景数量不参与判断；实际件数由无遮挡结果页差额取得',
              'live_input':False}
    destination = root/'runs/initial-cleanup-validation.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'result':result,'report':str(destination)},ensure_ascii=False))


if __name__ == '__main__':
    main()
