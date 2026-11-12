"""实机16件选装和批量入口核对；禁止强化、出售、萃取和锁操作。"""
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import re
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from e7_assistant.adb import Adb
from e7_assistant.batch_entry import BatchEntryDriver
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.equipment_protection import EquipmentProtection
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator
from scripts.probe_inventory_traversal import NavigationOnlyAdb


class SelectionOnlyAdb(NavigationOnlyAdb):
    def __init__(self,*args,allow_preview=False,allow_sale_layouts=False,entry_count=16,**kwargs):
        super().__init__(*args,**kwargs)
        self.selection_inputs=[]
        self.allow_preview=allow_preview
        self.allow_sale_layouts=allow_sale_layouts
        if type(entry_count) is not int or not 1<=entry_count<=16:
            raise ValueError('入口取样数量必须为1～16')
        self.entry_count=entry_count

    def event(self,event):
        allowed={'navigation_intent','batch_selection_intent','batch_entry_intent',
                 'batch_unsupported_deselect_intent','batch_protected_equivalence_deselect_intent',
                 'inventory_detail_probe_intent','inventory_detail_probe_restore_intent'}
        if self.allow_preview:
            allowed.add('batch_stage_preview_intent')
        if self.allow_sale_layouts:
            allowed.add('sale_layout_preview_intent')
        self.intent=event if event['kind'] in allowed else None

    def tap(self,x,y):
        intent=self.intent
        if intent and intent['kind']!='navigation_intent':
            self.intent=None
            if intent['kind']=='sale_layout_preview_intent':
                action=intent.get('action')
                valid=(intent.get('x'),intent.get('y'))==(x,y) and (
                    action=='toggle' and intent.get('page')=='batch_organize'
                    and any((x,y)==(62+round(col*316.667*1280/1661),185+round(row*167.333*720/933))
                            for row in range(4) for col in range(4))
                    or action=='open_sale' and intent.get('page')=='batch_organize'
                    and 210<=x<370 and 60<=y<130
                    or action=='cancel_sale' and intent.get('page')=='sale_confirmation'
                    and 400<=x<650 and 490<=y<570)
            elif intent['kind']=='batch_stage_preview_intent':
                valid=(intent.get('target')==3 and (intent.get('x'),intent.get('y'))==(x,y)
                       and 15<=x<=200 and 645<=y<=700)
            elif intent['kind']=='batch_entry_intent':
                valid=intent.get('count')==self.entry_count and 1000<=x<1250 and 630<=y<710
            elif intent['kind'].startswith('inventory_detail_probe_'):
                valid=(intent.get('x'),intent.get('y'))==(x,y) and 145<=x<=825 and 180<=y<=555
            else:
                valid=145<=x<=825 and 180<=y<=555
            if not valid:
                raise ValueError('选装取样禁止未登记坐标或资源确认')
            Adb.tap(self,x,y)
            self.selection_inputs.append({'kind':intent['kind'],'point':(x,y)})
            return
        super().tap(x,y)


def gold(screen):
    values=[int(w['text'].replace(',','')) for w in screen.words
            if w['confidence']>=.9 and 650<=w['center'][0]<810 and 10<=w['center'][1]<60
            and re.fullmatch(r'\d{1,3}(?:,\d{3})+',w['text'])]
    if len(values)!=1:
        raise ValueError('选装前后金币未唯一确认')
    return values[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-stage3',action='store_true',help='只预览+3所需材料，不确认强化')
    parser.add_argument('--sale-layouts',action='store_true',help='采集装备、饰品及混合出售弹窗，全部取消')
    args=parser.parse_args()
    if args.sale_layouts and args.preview_stage3:
        parser.error('出售弹窗与强化预览不可同时取样')
    directory=ROOT/'runs'/('batch-selection-probe-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2)
    adb=SelectionOnlyAdb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',
                         '127.0.0.1:16384',control,allow_preview=args.preview_stage3,
                         allow_sale_layouts=args.sale_layouts)
    journal=Journal(directory,adb.event)
    nav=WorkflowNavigator(adb,directory,control,journal)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    # 使用独立测试目录，不修改客户端已有暂存记录。
    protection=EquipmentProtection(directory/'protection',adb.serial,policy)
    selector=BatchSelectionDriver(nav,policy=policy,protection=protection)
    result={'state':'failed','resource_confirmations':0,'directory':str(directory)}
    before=None
    try:
        nav.navigate('inventory_batch_selection')
        initial=selector._begin(16)
        before_gold=gold(selector.screen)
        before=initial
        selection=selector.collect_pages(limit=16,max_pages=200,start_at_top=True)
        (directory/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf8')
        if selection['selected_count']!=16:
            raise ValueError('本次取样没有达到16件，不改变入口核验要求')
        report,items=BatchEntryDriver(selector).enter(selection)
        (directory/'context.json').write_text(json.dumps([asdict(i) for i in items],ensure_ascii=False,indent=2),encoding='utf8')
        result.update(state='entry_verified',entry_verified=True,count=len(items),entry_image=report['source'])
        if args.sale_layouts:
            from scripts.probe_sale_layouts import preview_layouts
            result['sale_layouts']=preview_layouts(nav,items,journal)
            result['state']='sale_layouts_cancelled'
        if args.preview_stage3:
            preview=BatchEnhancementDriver(nav).prepare_enhancement(items,3)
            (directory/'preview.json').write_text(json.dumps(asdict(preview),ensure_ascii=False,indent=2),encoding='utf8')
            result.update(state='preview_verified',target=3,cost=preview.cost,preview_image=preview.image)
    except Exception as exc:
        result['error']=str(exc)
        result['state']='failed'
    finally:
        # 起点必须确认原本无选择；只清除此取样建立的勾选，不执行清空按钮。
        if before is not None:
            try:
                nav.navigate('inventory')
                nav.navigate('inventory_batch_selection')
                after=selector._begin(16)
                after_gold=gold(selector.screen)
                if before['inventory_context']!=after['inventory_context'] or before_gold!=after_gold:
                    raise ValueError('取样前后背包上下文或金币变化')
                result.update(cleanup_verified=True,gold_before=before_gold,gold_after=after_gold,
                              inventory_context=after['inventory_context'])
                nav.navigate('inventory')
            except Exception as exc:
                result.update(cleanup_verified=False,cleanup_error=str(exc))
        result.update(last_image=nav.last_image,inputs=adb.selection_inputs,navigation=adb.navigation_taps)
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False))
    expected='sale_layouts_cancelled' if args.sale_layouts else 'preview_verified' if args.preview_stage3 else 'entry_verified'
    return int(result['state']!=expected or not result.get('cleanup_verified'))


if __name__=='__main__':
    raise SystemExit(main())
