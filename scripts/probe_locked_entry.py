"""定点核对列表末尾的已锁未满级装备；临时选装/入口/读取，禁止资源与锁输入。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from e7_assistant.batch_entry import verify_entry
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.batch_vision import inspect_batch
from e7_assistant.inventory_tail_vision import inspect_tail
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator
from scripts.probe_batch_selection import SelectionOnlyAdb,gold


def main():
    folder=ROOT/'runs'/('locked-entry-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2)
    adb=SelectionOnlyAdb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',
                         '127.0.0.1:16384',control,entry_count=1)
    journal=Journal(folder,adb.event)
    nav=WorkflowNavigator(adb,folder,control,journal)
    selector=BatchSelectionDriver(nav)
    result={'state':'failed','scope':'targeted_locked_entry_only','resource_confirmations':0,
            'directory':str(folder)}
    try:
        nav.navigate('inventory_batch_selection')
        selector._begin(16,navigation_only=True)
        before=nav.read()
        result['gold_before']=gold(before)
        for move in range(30):
            screen=nav.read()
            selector._navigation_snapshot(screen)  # 每次手势前独立确认仍为零选择页。
            tail=inspect_tail(screen)
            if tail.get('end_verified'):
                break
            journal.emit('targeted_tail_scroll',move=move+1,image=screen.source)
            adb.swipe(500,550,500,180,300)
            control.wait(.3)
        else:
            raise ValueError('未独立确认列表底端，停止定点取样')
        current=selector.observe()
        (folder/'tail.json').write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf8')
        candidates=[c for c in current['cards'] if c['known'] and c['eligible']
                    and c['rarity']=='red' and 0<c['enhancement']<15 and not c['selected']]
        if len(candidates)!=1:
            raise ValueError('当前末尾未唯一确认一件未满级红装')
        candidate=candidates[0]
        target=(candidate['row'],candidate['column'])
        fresh=selector.observe_unchanged(current)
        journal.emit('batch_selection_intent',row=target[0],column=target[1],image=fresh['source'],count=0)
        adb.tap(*candidate['center'])
        control.wait(.3)
        selected=selector._observe_click(fresh,target)
        detail=selector.detail_reader(selector.screen,candidate)
        registered={**detail,'equipment':asdict(detail['equipment'])}
        (folder/'detail.json').write_text(json.dumps(registered,ensure_ascii=False,indent=2),encoding='utf8')
        fresh=selector.observe_unchanged(selected)
        word=selector.screen.find('批量强化(1)',(1000,630,1250,710))
        journal.emit('batch_entry_intent',count=1,image=fresh['source'])
        adb.tap(*(round(v) for v in word['center']))
        for _ in range(8):
            control.wait(.4)
            screen=nav.read()
            if screen.page=='batch_enhancement':
                break
            if screen.page not in ('unknown','inventory_batch_selection'):
                raise ValueError('定点入口出现非预期页面')
        else:
            raise TimeoutError('定点入口超时，未重复点击')
        report=inspect_batch(screen.source,{0:detail['equipment'].slot},entry_details={0:registered},ignore_levels=True)
        (folder/'entry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=asdict),encoding='utf8')
        items=verify_entry({'selected_count':1,'registered':[registered]},report)
        if items[0].locked is not True:
            raise ValueError('定点装备未确认已上锁')
        nav.batch_ignore_equipment_level=True
        driver=BatchEnhancementDriver(nav,track_resources=False)
        observed,again,_=driver.observe(items)
        driver.unchanged(items,again)
        result.update(state='locked_entry_verified',item=asdict(items[0]),
                      entry_image=screen.source,subsequent_read_image=observed.source,
                      level_source=report['records'][0]['level_source'],ignore_equipment_level=True)
    except Exception as exc:
        result['error']=str(exc)
    finally:
        try:
            nav.navigate('inventory')
            after=nav.read()
            result['gold_after']=gold(after)
            result['cleanup_verified']=after.page=='inventory' and result.get('gold_before')==result['gold_after']
            result['cleanup_image']=after.source
        except Exception as exc:
            result['cleanup_error']=str(exc)
        result.update(inputs=adb.selection_inputs,last_image=nav.last_image)
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='locked_entry_verified' or not result.get('cleanup_verified'))


if __name__=='__main__':
    raise SystemExit(main())
