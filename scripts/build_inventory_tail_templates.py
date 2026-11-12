"""用已标注普通背包尾行的空背景与滚动条底端建立模板，无游戏输入。"""
import hashlib
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
source = ROOT/'docs/assets/inventory-tail-2026-11-10/reference-background.png'
destination = ROOT/'e7_assistant/assets/inventory-tail'
destination.mkdir(parents=True,exist_ok=True)
boxes = {'bottom-cap':(818,698,830,712)}
boxes.update({f'empty-{col}':(146+99*col,600,min(229+99*col,816),710)
              for col in range(1,7)})
with Image.open(source) as image:
    assert image.size == (1280,720)
    for name,box in boxes.items():
        image.convert('RGB').crop(box).save(destination/(name+'.png'))
(destination/'provenance.json').write_text(json.dumps({
    'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'boxes':boxes,'annotation':'普通背包底部最后一行仅第0列有装备，第1至6列为空；滚动条底端可见',
    'scope':'固定1280×720实例背景样本；独立验证使用后续批量选择页截图',
    'input_performed':False},ensure_ascii=False,indent=2),encoding='utf-8')
print(str(destination))
