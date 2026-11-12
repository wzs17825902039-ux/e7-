"""实机覆盖取样；可选临时勾选核对详情，不强化或处置装备。"""
import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from e7_assistant.adb import Adb
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_scan import InventoryTraversal,scroll_distance
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator


class NavigationOnlyAdb(Adb):
    """取样脚本只能执行已写入日志的导航点击，防止误调用选装或确认。"""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.intent=None
        self.navigation_taps=[]

    def event(self,event):
        self.intent=event if event['kind']=='navigation_intent' else None

    def tap(self,x,y):
        actions={'menu','forge','inventory','manage','batch_select','close_manage','cancel_inventory',
                 'cancel_batch_organize','back_batch','close_craft_result','cancel_full','cancel_extract',
                 'back_inventory','dismiss_date','dismiss_attendance','dismiss_friendship','organize_batch'}
        intent=self.intent
        self.intent=None
        if (not intent or intent.get('action') not in actions
                or (intent.get('x'),intent.get('y'))!=(x,y)):
            raise ValueError('只读遍历禁止未登记的导航或装备点击')
        super().tap(x,y)
        self.navigation_taps.append({'action':intent['action'],'point':(x,y)})


class DetailProbeAdb(NavigationOnlyAdb):
    """只额外允许详情核对的成对临时勾选；资源与锁按钮始终禁止。"""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.detail_inputs=[]

    def event(self,event):
        self.intent=event if event['kind'] in {
            'navigation_intent','inventory_detail_probe_intent','inventory_detail_probe_restore_intent'} else None

    def tap(self,x,y):
        intent=self.intent
        if intent and intent['kind'].startswith('inventory_detail_probe_'):
            self.intent=None
            if (intent.get('x'),intent.get('y'))!=(x,y) or not (145<=x<=825 and 180<=y<=555):
                raise ValueError('详情取样禁止未登记坐标或资源确认')
            Adb.tap(self,x,y)
            self.detail_inputs.append({'kind':intent['kind'],'point':(x,y)})
            return
        super().tap(x,y)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-pages',type=int,default=10)
    parser.add_argument('--distance',type=int,help='固定校准距离60～160像素；不填则使用生产行位置校准')
    parser.add_argument('--duration',type=int,choices=(600,1000,1200),default=600,
                        help='只读滚动手势时长，用于核对惯性超滚；默认沿用生产600毫秒')
    parser.add_argument('--detail-recovery',action='store_true',help='允许临时勾选读取遮挡等级的原生详情，随后恢复勾选')
    args=parser.parse_args()
    if not 1<=args.max_pages<=200:
        parser.error('页数范围为1～200')
    if args.distance is not None and not 60<=args.distance<=160:
        parser.error('滚动距离范围为60～160')
    directory=ROOT/'runs'/('inventory-traversal-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2)
    adb_type=DetailProbeAdb if args.detail_recovery else NavigationOnlyAdb
    adb=adb_type(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    journal=Journal(directory,adb.event)
    navigator=WorkflowNavigator(adb,directory,control,journal)
    selector=BatchSelectionDriver(navigator,recover_detail_levels=args.detail_recovery)
    traversal=InventoryTraversal()
    result={'directory':str(directory),'state':'failed','selection_inputs':0,'resource_confirmations':0}
    try:
        navigator.navigate('inventory_batch_selection')
        current,anchor=selector.rewind_to_top(selector._begin(16,navigation_only=True),args.max_pages)
        traversal.start(current,anchor)
        for page in range(1,args.max_pages+1):
            (directory/f'page-{page:04d}.json').write_text(
                json.dumps(current,ensure_ascii=False,indent=2),encoding='utf8')
            unknown=[(c['row'],c['column']) for c in current['cards'] if not c['known']]
            journal.emit('traversal_page',page=page,unknown=unknown,image=current['source'],
                         evidence=traversal.evidence())
            if current['selected_count']!=0 or any(c['selected'] is not False for c in current['cards']):
                raise ValueError('只读遍历发现勾选，不继续滚动')
            if traversal.end_verified:
                result['state']='end_observed'
                break
            if page==args.max_pages:
                result['state']='page_limit'
                break
            fresh=selector.selection_reference(current)
            alternate=current if len(fresh['cards'])==len(current['cards']) else None
            traversal.observe_end(fresh)
            distance=args.distance if args.distance is not None else scroll_distance(fresh)
            journal.emit('traversal_scroll_intent',distance=distance,
                         mode='fixed' if args.distance is not None else 'row_position',image=fresh['source'])
            adb.swipe(500,510,500,510-distance,args.duration)
            control.wait(.5)
            after,offset=selector.observe_scrolled(fresh,traversal,alternate)
            (directory/f'after-{page:04d}.json').write_text(
                json.dumps(after,ensure_ascii=False,indent=2),encoding='utf8')
            current=after
    except Exception as exc:
        result['error']=str(exc)
        journal.emit('traversal_failed',message=str(exc),image=navigator.last_image)
    result.update(evidence=traversal.evidence(),last_image=navigator.last_image,
                  navigation_taps=adb.navigation_taps,
                  selection_inputs=len(getattr(adb,'detail_inputs',[])),
                  detail_inputs=getattr(adb,'detail_inputs',[]))
    if args.detail_recovery:
        try:
            navigator.navigate('inventory')
            result['cleanup_verified']=navigator.read().page=='inventory'
            result['cleanup_image']=navigator.last_image
        except Exception as exc:
            result['cleanup_error']=str(exc)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return int(result['state']=='failed')


if __name__=='__main__':
    raise SystemExit(main())
