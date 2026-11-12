"""已有+9/+10装备的定点只读入口取样；不代表顺序遍历或完整尾批。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from e7_assistant.batch_entry import verify_entry
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.batch_vision import inspect_batch
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator
from scripts.probe_batch_selection import SelectionOnlyAdb,gold


def main():
    folder=ROOT/'runs'/('unfinished-targeted-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2)
    adb=SelectionOnlyAdb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',
                         '127.0.0.1:16384',control,entry_count=2)
    journal=Journal(folder,adb.event)
    nav=WorkflowNavigator(adb,folder,control,journal)
    selector=BatchSelectionDriver(nav)
    result={'state':'failed','scope':'targeted_entry_only','resource_confirmations':0,
            'directory':str(folder)}
    initial=None
    registered=[]
    try:
        nav.navigate('inventory_batch_selection')
        current=selector._begin(16)
        before_gold=gold(selector.screen)
        initial=current
        for stage in (9,10):
            fresh=selector.observe_unchanged(current)
            candidates=[c for c in fresh['cards'] if c['known'] and c['eligible']
                        and c['rarity']=='purple' and c['enhancement']==stage and not c['selected']]
            if not candidates:
                raise ValueError(f'当前可见区域没有已确认的+{stage}紫装；不滚动猜测位置')
            candidate=candidates[0]
            target=(candidate['row'],candidate['column'])
            journal.emit('batch_selection_intent',row=target[0],column=target[1],
                         image=fresh['source'],count=fresh['selected_count'])
            adb.tap(*candidate['center'])
            control.wait(.3)
            current=selector._observe_click(fresh,target)
            detail=selector.detail_reader(selector.screen,candidate)
            registered.append({**detail,'equipment':asdict(detail['equipment'])})
            (folder/f'detail-{stage}.json').write_text(
                json.dumps(registered[-1],ensure_ascii=False,indent=2),encoding='utf8')
        fresh=selector.observe_unchanged(current)
        # 定点取样不伪造scan_complete，不调用生产尾批完整遍历入口。
        word=selector.screen.find('批量强化(2)',(1000,630,1250,710))
        journal.emit('batch_entry_intent',count=2,image=fresh['source'])
        adb.tap(*(round(v) for v in word['center']))
        for _ in range(8):
            control.wait(.4)
            screen=nav.read()
            if screen.page=='batch_enhancement':
                break
            if screen.page not in ('unknown','inventory_batch_selection'):
                raise ValueError('定点入口出现非预期页面')
        else:
            raise TimeoutError('批量入口超时，不重复点击')
        report=inspect_batch(screen.source,{i:r['equipment']['slot'] for i,r in enumerate(registered)})
        items=verify_entry({'selected_count':2,'registered':registered},report)
        (folder/'batch.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=asdict),encoding='utf8')
        result.update(state='entry_verified',items=[asdict(item) for item in items],image=screen.source)
    except Exception as exc:
        result['error']=str(exc)
    finally:
        if initial is not None:
            try:
                nav.navigate('inventory')
                nav.navigate('inventory_batch_selection')
                after=selector._begin(16)
                after_gold=gold(selector.screen)
                if initial['inventory_context']!=after['inventory_context'] or before_gold!=after_gold:
                    raise ValueError('取样前后上下文或金币发生变化')
                result.update(cleanup_verified=True,gold_before=before_gold,gold_after=after_gold,
                              inventory_context=after['inventory_context'])
                nav.navigate('inventory')
            except Exception as exc:
                result.update(cleanup_verified=False,cleanup_error=str(exc))
        result.update(last_image=nav.last_image,inputs=adb.selection_inputs,navigation=adb.navigation_taps)
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='entry_verified' or not result.get('cleanup_verified'))


if __name__=='__main__':
    raise SystemExit(main())
