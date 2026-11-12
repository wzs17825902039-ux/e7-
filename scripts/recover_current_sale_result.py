"""只恢复已提交的12件混合出售，绝不重复出售确认。"""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_sale import BatchSaleDriver
from e7_assistant.batch_sale_vision import inspect_sale_confirmation,verify_sale_survivors
from e7_assistant.batch_resources import inspect_resources
from e7_assistant.initial_cleanup import inspect_inventory
from e7_assistant.disposal_guard import BatchEnhancementGuard,DisposalGuard
from e7_assistant.rules import Equipment
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow import BatchItem
from e7_assistant.workflow_navigation import WorkflowNavigator
from e7_assistant.workflow_screen import inspect_screen


def main():
    directory=ROOT/'runs'/('current-sale-recovery-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2);serial='127.0.0.1:16384'
    guard=DisposalGuard(ROOT/'runs/disposal-pending',serial)
    pending=guard.read()
    if (not pending or Path(pending['run_directory'])!=ROOT/'runs/current-batch-finish-42648246'
            or pending['confirmation']['count']!=12):
        raise ValueError('未找到指定出售记录，不操作')
    BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial).check_clear()
    (directory/'original-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf8')
    old=pending['before']
    items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in old['items']]
    rejected=set(old['rejected']);protected={i.token for i in items}-rejected
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    enhancement=BatchEnhancementDriver(nav,track_resources=False,ignore_equipment_level=True)
    sale=BatchSaleDriver(enhancement,guard=guard)
    confirmation=inspect_sale_confirmation(inspect_screen(pending['confirmation']['image']))
    old_confirmation=pending['confirmation']
    if (confirmation.count!=old_confirmation['count'] or confirmation.gold!=old_confirmation['gold']
            or confirmation.digest!=old_confirmation['digest']
            or (confirmation.powder,confirmation.jewelry_powder)!=(old_confirmation['jewelry_powder'],old_confirmation['powder'])):
        raise ValueError('原出售弹窗的类型修正证据不符')
    journal.emit('sale_receipt_category_corrected',original=old_confirmation,
                 powder=confirmation.powder,jewelry_powder=confirmation.jewelry_powder,
                 reason='同一原始弹窗重新识别；混合布局中间为饰品粉，右侧为装备粉')
    screen=nav.read()
    if screen.page=='inventory':
        # 上次只在最后背包金币置信度处停止；重新逐项验证保存的结果证据，
        # 并以两张当前背包截图验证减量和余额，不重建或重发出售。
        expected=dict(old['resources']);expected['gold']+=confirmation.gold
        expected['powder']+=confirmation.powder;expected['jewelry_powder']+=confirmation.jewelry_powder
        for name in ('workflow-0002.png','workflow-0003.png'):
            saved=inspect_screen(ROOT/'runs/current-sale-recovery-a8919377'/name)
            verify_sale_survivors(saved,ROOT/'runs/current-batch-finish-42648246/workflow-0002.png',items,rejected)
            if inspect_resources(saved).available!=expected:raise ValueError('原出售结果资源证据不符')
        for current in (screen,nav.read()):
            inventory=inspect_inventory(current)
            if (inventory.count,inventory.capacity,inventory.gold)!=(old['inventory_count']-len(rejected),old['capacity'],expected['gold']):
                raise ValueError('当前背包数量或金币不符')
        if guard.read()!=pending:raise ValueError('原出售记录变化')
        journal.emit('batch_sale_settled',operation_id=pending['operation_id'],disposed=sorted(rejected),resources_after=expected)
        guard.settle(pending['operation_id'])
        result={'state':'complete','disposed':sorted(rejected),'protected':sorted(protected),'last_image':nav.last_image}
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'directory':str(directory),'state':'complete'},ensure_ascii=False));return
    result=sale.settle_result(items,rejected,protected,old['resources'],
        ROOT/'runs/current-batch-finish-42648246/workflow-0002.png',
        confirmation,old['inventory_count'],old['capacity'],
        pending['operation_id'],screen.page)
    result.update(state='complete',last_image=nav.last_image)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),'state':result['state'],'disposed':result['disposed']},ensure_ascii=False))


if __name__=='__main__':main()
