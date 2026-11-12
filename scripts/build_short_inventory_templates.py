"""从真实客户端截图标定短列表空背景，不发送游戏输入。"""
import hashlib
import json
from pathlib import Path
from PIL import Image

root=Path(__file__).resolve().parents[1]
source=root/'runs/recovery-e63d8d54ac5c/workflow-0033.png'
destination=root/'e7_assistant/assets/inventory-tail'
boxes={'short-bottom':(146,544,816,710)}
boxes.update({f'short-empty-{col}':(146+99*col,419,min(229+99*col,816),534)
              for col in range(1,7)})
with Image.open(source) as image:
    for name,box in boxes.items():image.crop(box).save(destination/(name+'.png'))
(destination/'short-provenance.json').write_text(json.dumps({
    'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'boxes':boxes,'annotation':'顶部短列表第三行仅第0格有装备，其余为空，下方无装备，无滚动条',
    'scope':'仅支持第三行收尾且顶部两行完整的1280x720短列表'},ensure_ascii=False,indent=2),encoding='utf8')
