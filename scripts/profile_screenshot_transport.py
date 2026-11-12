"""只读对比MuMu PNG及原始帧传输，不改变模拟器设置。"""
import json
from pathlib import Path
import struct
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb

a=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384')
result=[]
for args in (['exec-out','screencap','-p'],['exec-out','screencap']):
    for _ in range(3):
        start=time.perf_counter();data=a._run(args,device=True)
        result.append(dict(args=args,seconds=time.perf_counter()-start,bytes=len(data),
                           header=list(struct.unpack('<4I',data[:16])) if args[-1]!='-p' else []))
print(json.dumps(result,indent=2))
(ROOT/'runs/screenshot-transport-profile.json').write_text(json.dumps(result,indent=2),encoding='utf8')
