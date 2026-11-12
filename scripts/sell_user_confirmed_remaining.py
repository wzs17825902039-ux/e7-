"""仅出售用户截图确认的四件；新批入口核对后精确匹配，不强化其他装备。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.batch_entry import BatchEntryDriver
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.disposal_guard import BatchEnhancementGuard,DisposalGuard
from e7_assistant.inventory_sort import ensure_ascending
from e7_assistant.rules import Policy
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator


def key(item):
    e=item.equipment if hasattr(item,'equipment') else item['equipment']
    e=asdict(e) if hasattr(e,'equipment_id') else e
    return (e['rarity'],e['slot'],e['enhancement'],e['main_stat'],e['game_score'],tuple(sorted(e['stats'].items())))


def main():
    directory=ROOT/'runs'/('user-confirmed-sale-'+uuid.uuid4().hex[:8])
    journal=Journal(directory);control=TaskControl(.2);serial='127.0.0.1:16384'
    BatchEnhancementGuard(ROOT/'runs/enhancement-pending',serial).check_clear()
    DisposalGuard(ROOT/'runs/disposal-pending',serial).check_clear()
    old=json.loads((ROOT/'runs/current-result-recovery-5c000646/result.json').read_text(encoding='utf8'))
    targets=[i for i in old['items'] if i['token'] in {'4','6','7','10'}]
    if len(targets)!=4:raise ValueError('用户确认的四件记录不完整')
    policy=Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    adb=Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',serial,control)
    nav=WorkflowNavigator(adb,directory,control,journal)
    nav.navigate('inventory');ensure_ascending(nav);nav.navigate('inventory_batch_selection')
    selector=BatchSelectionDriver(nav,policy=policy)
    selection=selector.collect_pages(limit=16,max_pages=3,start_at_top=True)
    _,items=BatchEntryDriver(selector).enter(selection)
    rejected=set()
    for target in targets:
        matches=[item for item in items if key(item)==key(target) and item.locked is False]
        if len(matches)!=1:raise ValueError('确认装备未在本批唯一匹配，未出售')
        rejected.add(matches[0].token)
    if len(rejected)!=4:raise ValueError('四件装备身份重复')
    journal.emit('user_confirmed_disposal',tokens=sorted(rejected),original_tokens=['4','6','7','10'],action='sell')
    driver=BatchEnhancementDriver(nav,track_resources=False,ignore_equipment_level=True)
    start=time.perf_counter();deselected=driver.select_active(items,set())
    elapsed=time.perf_counter()-start
    journal.emit('selection_speed_measured',count=len(items),seconds=elapsed,includes_full_verification=True)
    result=driver.dispose_batch(deselected,rejected,{i.token for i in items}-rejected,action='sell')
    result.update(state='complete',selection_seconds=elapsed,selection_count=len(items),last_image=nav.last_image)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),**result},ensure_ascii=False))


if __name__=='__main__':main()
