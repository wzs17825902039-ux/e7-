"""为已测试的单件头盔采集闭锁样本；一次点击，不解锁、不重试。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
import numpy as np
from e7_assistant.adb import Adb
from e7_assistant.batch_vision import inspect_batch
from e7_assistant.batch_resources import inspect_resources
from e7_assistant.tasks import TaskControl,Journal
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    directory=ROOT/'runs'/('batch-lock-sample-'+uuid.uuid4().hex[:8])
    journal=Journal(directory)
    control=TaskControl(.8)
    nav=WorkflowNavigator(Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',
        '127.0.0.1:16384',control),directory,control,journal)
    expected=json.loads((ROOT/'runs/stage-probe-97b569bb/result.json').read_text(encoding='utf-8'))
    before=nav.read()
    report=inspect_batch(before.source,{0:'helmet'})
    if report['issues'] or len(report['records'])!=1:
        raise ValueError('测试装备未唯一确认')
    record=report['records'][0]
    for key in ('rarity','level','enhancement','slot','stats','game_score'):
        if record['equipment'][key]!=expected['items'][0]['equipment'][key]:
            raise ValueError('当前装备与已测试装备不符')
    resources=inspect_resources(before)
    if resources.gold_cost or any(resources.reserved.values()):
        raise ValueError('仍有材料登记，不执行锁测试')
    box=(211,133,252,164)
    with Image.open(before.source) as a,Image.open(expected['image']) as b:
        error=float(np.abs(np.asarray(a.crop(box)).astype(float)-np.asarray(b.crop(box)).astype(float)).mean())
    if error>3:
        raise ValueError('锁按钮与已目视确认开锁样本不同，不点击')
    journal.emit('single_lock_sample_intent',image=before.source,box=box,pixel_error=error)
    nav.adb.tap(231,148)
    control.wait(.5)
    after=nav.read()
    journal.emit('single_lock_sample_observed',image=after.source)
    print(json.dumps({'directory':str(directory),'before':before.source,'after':after.source,
                      'resources':asdict(resources)},ensure_ascii=False))


if __name__=='__main__':
    main()
