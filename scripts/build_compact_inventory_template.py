"""标定单行短列表的空背景；第一格有装备，永不作为空格模板。"""
import hashlib
import json
from pathlib import Path
from PIL import Image

root=Path(__file__).resolve().parents[1]
source=root/'runs/workflow-2b455956177c/workflow-0074.png'
destination=root/'e7_assistant/assets/inventory-tail'
with Image.open(source) as image:
    image.crop((146,145,816,710)).save(destination/'compact-background.png')
(destination/'compact-provenance.json').write_text(json.dumps({
    'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'box':[146,145,816,710],'annotation':'只有第一行第0格有装备，其他区域为空；第一格不用于空背景比较',
    'input_performed':False},ensure_ascii=False,indent=2),encoding='utf8')
