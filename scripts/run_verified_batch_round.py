"""执行用户已授权的一批16件；按现行规则逐阶段强化、暂存和上锁。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from e7_assistant.adb import Adb
from e7_assistant.batch_entry import BatchEntryDriver
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.disposal_guard import BatchEnhancementGuard,CraftSessionGuard,DisposalGuard
from e7_assistant.equipment_protection import EquipmentProtection
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl,Limits
from e7_assistant.workflow import WorkflowTask,WorkflowOptions
from e7_assistant.workflow_navigation import WorkflowNavigator

BASIS=ROOT/'runs/batch-selection-probe-16c46965'


def verify_authorized_selection(approved,current):
    if (approved['selected_count']!=16 or current['selected_count']!=16
            or len(approved['registered'])!=16 or len(current['registered'])!=16):
        raise ValueError('本次授权仅限已核验的16件装备')
    for old,new in zip(approved['registered'],current['registered']):
        if (old['fingerprint'],tuple(old['main']))!=(new['fingerprint'],tuple(new['main'])):
            raise ValueError('当前装备或顺序与授权批次不符，未启动强化')


class AuthorizedRoundDriver(BatchEnhancementDriver):
    def __init__(self,*args,approved_cost,**kwargs):
        super().__init__(*args,**kwargs)
        self.approved_cost=approved_cost
        self.first=True

    def prepare_enhancement(self,items,target):
        preview=super().prepare_enhancement(items,target)
        if self.first:
            if target!=3 or not self.resource_untracked and preview.cost!=self.approved_cost:
                raise ValueError('本批首节点费用与已核验预览不一致，未确认强化')
            self.first=False
        return preview

    def dispose_batch(self,*args,**kwargs):
        raise ValueError('本轮不允许出售或萃取，装备暂存')


def main():
    approved=json.loads((BASIS/'selection.json').read_text(encoding='utf8'))
    approved_preview=json.loads((BASIS/'preview.json').read_text(encoding='utf8'))
    directory=ROOT/'runs'/('verified-batch-round-'+uuid.uuid4().hex[:8])
    control=TaskControl(.2)
    journal=Journal(directory)
    serial='127.0.0.1:16384'
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    guard=BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial)
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    result={'state':'failed','scope':'one_authorized_batch','directory':str(directory),
            'basis':str(BASIS),'outcome_unknown':False}
    task=None
    try:
        for pending in (guard,CraftSessionGuard(ROOT/'runs/craft-pending',serial),
                        DisposalGuard(ROOT/'runs/disposal-pending',serial)):
            pending.check_clear()
        nav.navigate('inventory_batch_selection')
        protection=EquipmentProtection(ROOT/'runs/equipment-protection',serial,policy)
        selector=BatchSelectionDriver(nav,policy=policy,protection=protection)
        selection=selector.collect_pages(limit=16,max_pages=200,start_at_top=True)
        verify_authorized_selection(approved,selection)
        (directory/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf8')
        report,items=BatchEntryDriver(selector).enter(selection)
        # 仅这一批，最多五次属性节点确认；各类预算不超过本批已读持有量。
        holdings=approved_preview['resources']
        limits=Limits(gold=holdings['gold'],powder=holdings['powder'],
                      lesser_stone=holdings['lesser_stone'],greater_stone=holdings['greater_stone'],
                      epic_stone=holdings['epic_stone'],max_steps=5)
        journal.emit('authorized_batch',basis=str(BASIS),limits=asdict(limits),
                     count=16,policy=asdict(policy),first_preview_cost=approved_preview['cost'])
        driver=AuthorizedRoundDriver(nav,guard=guard,approved_cost=approved_preview['cost'],
                                     track_resources=False,purple_speed_only=True)
        task=WorkflowTask(driver,WorkflowOptions(first_target=3),policy,limits,control,journal)
        result.update(task.run_batch(items))
        (directory/'batch-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        if not result['outcome_unknown']:
            guard.check_clear()
            nav.navigate('inventory')
            result['returned_inventory']=True
    except Exception as exc:
        result.update(error=str(exc),outcome_unknown=bool(task and task.uncertain))
    finally:
        if nav.last_image and not result['outcome_unknown'] and not result.get('returned_inventory'):
            try:
                nav.navigate('inventory')
                result['returned_inventory']=True
            except Exception as exc:
                result.update(returned_inventory=False,cleanup_error=str(exc))
        result['last_image']=nav.last_image
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False))
    return int(result['state']!='complete' or result['outcome_unknown'])


if __name__=='__main__':raise SystemExit(main())
