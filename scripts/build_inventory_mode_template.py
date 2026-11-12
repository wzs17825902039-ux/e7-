"""从已核对的实机零勾选截图生成页签模板及来源记录，不发送输入。"""
import hashlib
import json
from pathlib import Path
from PIL import Image


root = Path(__file__).resolve().parents[1]
source = root/'docs/assets/inventory-mode-2026-11-09/01-zero-selection.png'
destination = root/'e7_assistant/assets/inventory-mode'
destination.mkdir(parents=True,exist_ok=True)
box = (146,94,226,141)
with Image.open(source) as image:
    assert image.size == (1280,720)
    image.convert('RGB').crop(box).save(destination/'all-tab.png')
(destination/'provenance.json').write_text(json.dumps({
    'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'box':box,'scope':'批量选择空详情布局的全部装备分类页签，非装备唯一ID',
    'input_performed':False},ensure_ascii=False,indent=2),encoding='utf-8')
print(str(destination/'all-tab.png'))
