"""发行客户端的离线自检；不连接ADB、不执行游戏输入。"""
from pathlib import Path
import tempfile

from .runtime_paths import resource_root


def diagnose():
    checks = []
    def check(name, operation):
        try:
            detail = operation()
            checks.append({'name':name,'ok':True,'detail':detail})
        except Exception as exc:
            checks.append({'name':name,'ok':False,'error':str(exc)})
    def templates():
        from PIL import Image
        files = sorted((resource_root()/'e7_assistant/assets').rglob('*.png'))
        if len(files) < 10:
            raise RuntimeError('识别模板未完整打包')
        for path in files:
            with Image.open(path) as image:
                image.verify()
        return {'image_files':len(files)}
    def rules():
        from .rules import Equipment,Policy,evaluate
        item = Equipment('self-test','purple',85,0,'helmet',
                         {'hp_pct':5,'crit':5,'atk_pct':7},True,True,25)
        decision = evaluate(item,Policy(sell_failed_purple=True))
        if decision.action != 'stop' or not decision.discard_allowed:
            raise RuntimeError('默认规则自检不符')
        return '无速度紫装停止投入并标记明确淘汰；处置驱动仍须核验未锁'
    def locks():
        from .lock_vision import _batch_templates
        values=_batch_templates()
        if set(values)!={'locked','unlocked'} or any(value.shape!=(41,53,3) for value in values.values()):
            raise RuntimeError('批量锁状态模板未完整打包')
        return '批量开闭锁双模板已加载'
    def ocr():
        from PIL import Image,ImageDraw,ImageFont
        from .local_ocr import read_local_regions
        image = Image.new('RGB',(140,80),(40,40,40))
        ImageDraw.Draw(image).text((12,8),'85',font=ImageFont.load_default(size=48),fill='white')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'digits.png'
            image.save(path)
            values,_ = read_local_regions(path,{'level_test':(0,0,140,80)})
        if values.get('level_test') != '85':
            raise RuntimeError(f'OCR数字自检未读出85：{values}')
        return '内置模型已加载，合成数字85识别通过；不代表游戏准确率'
    def cv():
        import cv2
        import numpy as np
        a = np.arange(100,dtype=np.uint8).reshape(10,10)
        if cv2.matchTemplate(a,a,cv2.TM_CCOEFF_NORMED)[0,0] < .99:
            raise RuntimeError('模板匹配运行异常')
        return cv2.__version__
    def windows_ocr():
        path = resource_root()/'e7_assistant/windows_ocr.ps1'
        if not path.is_file():
            raise RuntimeError('Windows OCR脚本未打包')
        return '脚本资源存在；语言组件是否可用需本机截图验证'
    check('识别模板',templates)
    check('批量锁模板',locks)
    check('装备规则',rules)
    check('OpenCV',cv)
    check('RapidOCR与内置模型',ocr)
    check('Windows OCR资源',windows_ocr)
    return {'ok':all(c['ok'] for c in checks),'checks':checks,'live_input':False}
