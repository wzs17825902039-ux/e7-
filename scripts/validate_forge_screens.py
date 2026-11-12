"""用三张真实流程图核对十连选中、弹窗费用/部位和结果页暗底金币。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from e7_assistant.forge_loop import LiveForgeLoop,number
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.workflow_screen import inspect_screen


def main():
    directory=ROOT/'runs/forge-screen-validation'
    directory.mkdir(parents=True,exist_ok=True)
    screens=[]
    for name in ('04-part-count-resources.png','05-craft-confirmation.png','06-craft-repeat.png'):
        path=directory/name
        with Image.open(ROOT/'docs/assets/user-workflow-2026-11-09'/name) as image:
            image.resize((1280,720)).save(path)
        screens.append(inspect_screen(path))
    loop=LiveForgeLoop(None,WorkflowOptions(slot='helmet',craft_count=10),None,None,None)
    preview=loop.preview(screens[0])
    assert preview.resources=={'gold':346687724,'craft_material':275843},preview
    assert preview.cost=={'gold':210000,'craft_material':400},preview
    loop.verify_confirmation(screens[1],preview)
    gold=int(number(screens[2],'gold',(665,15,805,55),contrast=True).replace(',',''))
    assert gold==346477724,gold
    result={'scope':'用户三张截图缩放到1280×720的离线验证，不等同原生分辨率或实机循环',
            'preview':asdict(preview),'confirmation_verified':True,'result_gold':gold,
            'material_result_hidden':True}
    (ROOT/'runs/forge-screen-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
