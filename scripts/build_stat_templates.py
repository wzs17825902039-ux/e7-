"""从用户批量截图的已目视确认位置生成图标模板。"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'docs/assets/user-workflow-2026-11-09/17-batch-target.png'
positions = {'atk': (0, 0), 'crit': (0, 1), 'speed': (0, 2),
             'resistance': (1, 0), 'def': (1, 1), 'hp': (1, 2),
             'cdmg': (1, 3), 'effectiveness': (3, 0)}
with Image.open(source) as image:
    for name, (index, row) in positions.items():
        y, x = divmod(index, 4)
        dx, dy = round(x * 316.667), round(y * 167.333)
        image.crop((144+dx, 212+dy+row*28, 174+dx, 237+dy+row*28)).save(
            ROOT / 'e7_assistant/assets/stat-icons' / (name+'.png'))
