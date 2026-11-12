"""原16件已选入口的指定四件出售；通过原图逐块核验，不重复创建队列。"""
from dataclasses import asdict,replace
import json
from pathlib import Path
import sys
import time
import uuid
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_sale_vision import content_proof
from e7_assistant.batch_sale_vision import inspect_sale_confirmation
from e7_assistant.batch_sale import BatchSaleDriver
from e7_assistant.batch_resources import inspect_resources
from e7_assistant.batch_vision import inspect_selection_flags
from e7_assistant.disposal_guard import BatchEnhancementGuard,DisposalGuard
from e7_assistant.lock_vision import inspect_batch_lock
from e7_assistant.rules import Equipment
from e7_assistant.slot_vision import inspect_slots
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow import BatchItem
from e7_assistant.workflow_navigation import WorkflowNavigator
from e7_assistant.workflow_screen import inspect_screen


def main():
    serial='127.0.0.1:16384'
    BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial).check_clear()
    DisposalGuard(ROOT/'runs/disposal-pending',serial).check_clear()
    directory=ROOT/'runs'/('confirmed-four-sale-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2)
    events=[json.loads(line) for line in (ROOT/'runs/user-confirmed-sale-8e17ec33/events.jsonl').read_text(encoding='utf8').splitlines()]
    entry=[event for event in events if event['kind']=='batch_entry_observed'][-1]
    if entry['issues']!=["卡片4：副属性数字未可靠读取：''"]:
        raise ValueError('原入口失败范围不符')
    old=json.loads((ROOT/'runs/current-result-recovery-5c000646/result.json').read_text(encoding='utf8'))['items']
    old_by_token={item['token']:item for item in old}
    target_order=['4','6','7','10']
    records={record['index']:record for record in entry['records']}
    reference=Path(entry['image'])
    old_reference=ROOT/'runs/current-batch-finish-42648246/workflow-0002.png'
    # 这四件的跨位置对应已由本次代理目视对比原始截图与新入口截图确认。
    # 不把跨列重采样导致未通过的严格像素比较伪称通过；后续原位置内容
    # 则仍全部逐块核验。这是本次指定出售恢复，不是通用OCR补值规则。
    for index,token in enumerate(target_order):
        expected=old_by_token[token]
        if index in records:
            observed=records[index]['equipment']
            if any(observed[k]!=expected['equipment'][k] for k in ('rarity','slot','enhancement','stats','game_score')):
                raise ValueError('四件已识别字段与目视确认装备不符')
        records[index]={'index':index,'equipment':expected['equipment'],'main':{'stat':expected['equipment']['main_stat']},
                        'selected':True,'locked':expected['locked']}
    if sorted(records)!=list(range(16)):raise ValueError('未登记的其他装备位置')
    baseline=[BatchItem(str(i),Equipment(**records[i]['equipment']),True,records[i]['locked']) for i in range(16)]
    def graph_reader(path,slots,**kwargs):
        with Image.open(reference) as original,Image.open(path) as current:
            states=inspect_slots(current.convert('RGB').resize((1661,933)))
            if any(s['state']!='occupied' for s in states):raise ValueError('原16件位置或占用变化')
            flags=inspect_selection_flags(path,16)
            observed=[]
            for i,item in enumerate(baseline):
                content_proof(original,current,i,i)
                lock=inspect_batch_lock(current,'batch_enhancement',i,True)['locked']
                if lock is not item.locked:raise ValueError('原16件锁状态变化')
                observed.append({'index':i,'equipment':asdict(item.equipment),'main':records[i].get('main'),
                                 'selected':flags[i],'locked':lock})
        return {'records':observed,'slots':states,'issues':[]}
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    nav.batch_inventory_context=('1037/1200','最大强化')
    driver=BatchEnhancementDriver(nav,batch_reader=graph_reader,track_resources=False,ignore_equipment_level=True)
    if '--confirm-preview' in sys.argv:
        sale=BatchSaleDriver(driver)
        source=ROOT/'runs/confirmed-four-sale-c4343f41/workflow-0004.png'
        resources=inspect_resources(inspect_screen(source))
        deselected=[replace(i,selected=False) for i in baseline]
        rejected={'0','1','2','3'};protected={str(i) for i in range(4,16)}
        first=inspect_sale_confirmation(nav.read());screen=nav.read()
        confirmation=inspect_sale_confirmation(screen)
        if (asdict(first)|{'image':confirmation.image})!=asdict(confirmation):
            raise ValueError('待确认出售预览变化')
        if (confirmation.count,confirmation.gold,confirmation.powder,confirmation.jewelry_powder)!=(4,102100,10,10):
            raise ValueError('指定四件出售收入不符')
        operation=sale.guard.begin('sell',{'items':[asdict(i) for i in deselected],
            'rejected':sorted(rejected),'inventory_count':1037,'capacity':1200,'resources':resources.available},
            asdict(confirmation),directory)
        journal.emit('batch_sale_commit_intent',operation_id=operation,confirmation=asdict(confirmation))
        sale.click(screen,'确认',(650,490,850,570))
        for _ in range(8):
            after=nav.read()
            if after.page in {'batch_enhancement','batch_organize'}:break
            control.wait(.3)
        result=sale.settle_result(deselected,rejected,protected,resources.available,source,confirmation,
                                  1037,1200,operation,after.page)
        result.update(state='complete',last_image=nav.last_image)
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'directory':str(directory),**result},ensure_ascii=False));return
    _,items,_=driver.observe(baseline);driver.unchanged(baseline,items)
    journal.emit('specified_four_graph_verified',original_tokens=target_order,new_tokens=['0','1','2','3'],
                 reference=str(reference),old_reference=str(old_reference),
                 source_of_attributes='agent_visual_comparison_of_four_with_prior_verified_result')
    start=time.perf_counter();deselected=driver.select_active(items,set());elapsed=time.perf_counter()-start
    journal.emit('selection_speed_measured',count=16,seconds=elapsed,verification='complete_graph_identity_and_selection')
    result=driver.dispose_batch(deselected,{'0','1','2','3'},{str(i) for i in range(4,16)},action='sell')
    result.update(state='complete',selection_seconds=elapsed,last_image=nav.last_image)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),**result},ensure_ascii=False))


if __name__=='__main__':main()
