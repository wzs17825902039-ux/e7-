"""离线比较RGB与G通道对实际光效/滚动的稳定性；不连接游戏或自动修改标定。"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.inventory_scan import rows,same_row
from e7_assistant.inventory_tracking import inspect_tracking


def main():
    pairs=[]
    for run in ('9441ea60','dfd6852c','fbed2f6c','ceaaee14'):
        directory=ROOT/'runs'/f'inventory-traversal-{run}'
        for before in sorted(directory.glob('page-*.json')):
            after=directory/before.name.replace('page-','after-')
            if after.exists():
                pairs.append((f'{run}/{before.stem}',
                              json.loads(before.read_text(encoding='utf8')),
                              json.loads(after.read_text(encoding='utf8'))))
    report=[]
    for mode,sigma in (('rgb',1.2),('green',1.2)):
        cache={}
        def read(source):
            if source not in cache:
                with Image.open(source) as image:
                    pixels=np.maximum(np.asarray(image.convert('RGB')).astype(np.float32)-60,0)
                    if mode=='green':
                        pixels=np.repeat(pixels[:,:,1:2],3,axis=2)
                cache[source]=cv2.GaussianBlur(pixels,(0,0),sigma)
            return cache[source]
        records=[]
        with patch('e7_assistant.inventory_tracking._read',side_effect=read):
            for name,before,after in pairs:
                old,new=rows(before),rows(after)
                positives=[inspect_tracking(a,b) for i in (0,1)
                           for a,b in zip(old[i+1],new[i])]
                offsets=[offset for offset in (0,1)
                         if all(same_row(old[offset+i],new[i]) for i in range(3-offset))]
                # 错位行的每列也比较，报告误匹配数量而不假设每张卡片唯一。
                negatives=[inspect_tracking(a,b) for a,b in zip(old[0],new[0])]
                records.append({'sample':name,'min_positive_score':min(p['score'] for p in positives),
                                'positive_failures':sum(not p['matched'] for p in positives),
                                'wrong_row_card_matches':sum(p['matched'] for p in negatives),
                                'accepted_row_offsets':offsets})
        report.append({'mode':mode,'sigma':sigma,'samples':records})
    target=ROOT/'runs/tracking-calibration.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
