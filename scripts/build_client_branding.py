"""生成客户端自有几何工坊标记，不使用游戏素材。"""
from pathlib import Path
from PIL import Image,ImageDraw

root=Path(__file__).resolve().parents[1]
folder=root/'e7_assistant/assets/branding'
folder.mkdir(parents=True,exist_ok=True)
image=Image.new('RGBA',(256,256),'#101827')
draw=ImageDraw.Draw(image)
draw.rounded_rectangle((10,10,246,246),radius=54,fill='#141e2d',outline='#34405a',width=3)
draw.polygon([(46,114),(210,114),(188,145),(155,151),(155,177),(185,194),
              (185,206),(72,206),(72,194),(103,177),(103,151),(64,144)],fill='#e8b66d')
draw.line([(121,63),(176,102)],fill='#edf0f7',width=14)
draw.polygon([(77,57),(105,33),(147,65),(119,91)],fill='#e8b66d')
image.save(folder/'client.png')
image.save(folder/'client.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(folder)
