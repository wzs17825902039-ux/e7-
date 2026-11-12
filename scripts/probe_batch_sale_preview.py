"""单件整理/出售弹窗取样：只预览并取消，输入门禁不允许最终出售或强化。"""
import argparse
from dataclasses import asdict
import json
import re
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.initial_cleanup import inspect_inventory
from e7_assistant.rules import Equipment
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow import BatchItem
from e7_assistant.workflow_navigation import WorkflowNavigator
from scripts.probe_inventory_traversal import NavigationOnlyAdb
from e7_assistant.forge_loop import number
from e7_assistant.batch_sale_vision import inspect_organized,inspect_sale_confirmation


class SalePreviewAdb(NavigationOnlyAdb):
    PREVIEW_ACTIONS={
        'auto_select':({'batch_organize'},(10,60,160,130)),
        'select_single':({'batch_organize'},(30,140,100,220)),
        'open_sale':({'batch_organize'},(210,60,370,130)),
        'cancel_sale':({'sale_confirmation','unknown'},(350,450,650,600)),
    }

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.preview_taps=[]

    def event(self,event):
        if event['kind']=='sale_preview_intent':
            self.intent=event
        else:
            super().event(event)

    def tap(self,x,y):
        intent=self.intent
        if not intent or intent['kind']!='sale_preview_intent':
            return super().tap(x,y)
        self.intent=None
        rule=self.PREVIEW_ACTIONS.get(intent.get('action'))
        if (rule is None or intent.get('page') not in rule[0]
                or (intent.get('x'),intent.get('y'))!=(x,y)
                or not(rule[1][0]<=x<rule[1][2] and rule[1][1]<=y<rule[1][3])):
            raise ValueError('出售预览禁止未授权位置、最终出售及强化确认')
        Adb.tap(self,x,y)
        self.preview_taps.append({'action':intent['action'],'point':(x,y)})


def count_selected(screen):
    if screen.page!='batch_organize':
        raise ValueError('未确认批量整理页')
    value=number(screen,'selected_count',(742,75,793,112),r'\[[0-9]{1,2}\]')
    return int(re.fullmatch(r'\[([0-9]{1,2})\]',value)[1])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',type=Path,required=True)
    args=parser.parse_args()
    entries=json.loads(args.context.read_text(encoding='utf8'))
    items=[BatchItem(row['token'],Equipment(**row['equipment']),row['selected'],row['locked']) for row in entries]
    if len(items)!=1 or items[0].equipment.enhancement!=0 or items[0].locked is not False:
        raise ValueError('仅允许本次登记的一件未强化、确认未锁装备进行弹窗预览')
    directory=ROOT/'runs'/('sale-preview-'+uuid.uuid4().hex[:8])
    control=TaskControl(.8)
    adb=SalePreviewAdb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    journal=Journal(directory,adb.event)
    nav=WorkflowNavigator(adb,directory,control,journal)
    driver=BatchEnhancementDriver(nav)
    result={'state':'failed','directory':str(directory),'resource_confirmations':0}
    normal_reference=None

    def capture(screen,label):
        (directory/(label+'.json')).write_text(json.dumps(asdict(screen),ensure_ascii=False,indent=2),encoding='utf8')
        if screen.page=='batch_organize' and normal_reference is not None:
            proof=inspect_organized(screen,normal_reference,len(items))
            (directory/(label+'-proof.json')).write_text(json.dumps(asdict(proof),ensure_ascii=False,indent=2),encoding='utf8')
        elif screen.page=='sale_confirmation':
            proof=inspect_sale_confirmation(screen)
            (directory/(label+'-proof.json')).write_text(json.dumps(asdict(proof),ensure_ascii=False,indent=2),encoding='utf8')

    def click(screen,action,label=None):
        pages,region=adb.PREVIEW_ACTIONS[action]
        if screen.page not in pages:
            raise ValueError('预览页面与动作不符')
        point=(62,185) if action=='select_single' else tuple(round(v) for v in screen.find(label,region,.95)['center'])
        journal.emit('sale_preview_intent',action=action,page=screen.page,x=point[0],y=point[1],image=screen.source)
        adb.tap(*point)
        control.wait(.4)
        return nav.read()

    try:
        screen,before,resources=driver.observe(items)
        driver.unchanged(items,before)
        if resources.gold_cost or any(resources.reserved.values()):
            raise ValueError('仍有登记材料，不进入整理预览')
        result['resources_before']=resources.available
        normal_reference=screen.source
        capture(screen,'normal-before')
        screen=nav.transition('organize_batch')
        capture(screen,'organize-before')
        # 整理会继承刚刚核对的单件批量选择；仅允许这一件登记装备。
        if count_selected(screen) not in (0,1):
            raise ValueError('整理选中数量超出单件登记范围，未改动选择')
        screen=click(screen,'auto_select','自动选择')
        capture(screen,'organize-auto')
        count=count_selected(screen)
        if count==0:
            screen=click(screen,'select_single')
            capture(screen,'organize-selected')
        if count_selected(screen)!=1:
            raise ValueError('预览未唯一选中本件装备，不打开弹窗')
        screen=click(screen,'open_sale','出售')
        capture(screen,'sale-dialog')
        # 即使分类器尚不认识实际弹窗，也只能点击中央弹窗左侧的明确取消。
        if not any('出售' in w['text'] and w['confidence']>=.9
                   and 400<=w['center'][0]<880 and 140<=w['center'][1]<250 for w in screen.words):
            raise ValueError('未确认出售弹窗标题，未发送任何确认')
        screen=click(screen,'cancel_sale','取消')
        capture(screen,'sale-cancelled')
        if screen.page!='batch_organize':
            raise ValueError('取消后没有回到批量整理页')
        nav.transition('cancel_batch_organize')
        screen,after,after_resources=driver.observe(items)
        if [(i.token,asdict(i.equipment),i.locked) for i in before]!=[(i.token,asdict(i.equipment),i.locked) for i in after]:
            raise ValueError('预览前后装备属性或锁状态变化')
        driver.same_resources(resources,after_resources)
        capture(screen,'normal-after')
        screen=nav.navigate('inventory')
        inventory=inspect_inventory(screen)
        result.update(state='preview_cancelled',resources_after=after_resources.available,
                      inventory_after=asdict(inventory),equipment_unchanged=True)
    except Exception as exc:
        result['error']=str(exc)
        journal.emit('sale_preview_failed',message=str(exc),image=nav.last_image)
    result.update(last_image=nav.last_image,preview_taps=adb.preview_taps,navigation_taps=adb.navigation_taps)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return int(result['state']=='failed')


if __name__=='__main__':
    raise SystemExit(main())
