"""只读核对本次单件强化、锁取样及资源结算日志，不连接模拟器。"""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from e7_assistant.batch_resources import inspect_resources
from e7_assistant.disposal_guard import BatchEnhancementGuard
from e7_assistant.lock_vision import inspect_batch_lock,verify_batch_lock_pixels
from e7_assistant.workflow_screen import inspect_screen


def main():
    prepare=ROOT/'runs/stage-probe-4eb865b9/preview.json'
    run=ROOT/'runs/stage-probe-97b569bb'
    preview=json.loads(prepare.read_text(encoding='utf-8'))
    result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    events=[json.loads(line) for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    confirms=[event for event in events if event['kind']=='batch_enhance_commit_intent']
    assert len(confirms)==1 and preview['target']==3
    assert preview['cost']['gold']==17600 and preview['cost']['powder']==2 and preview['cost']['lesser_stone']==1
    actual={key:preview['resources'][key]-result['resources'][key] for key in preview['cost']}
    assert actual==preview['cost']
    assert all(result['spent'][key]==value for key,value in actual.items())
    assert len(result['items'])==1 and result['items'][0]['equipment']['enhancement']==3
    assert result['items'][0]['equipment']['stats']=={'atk_pct':14,'speed':3,'resistance':7,'hp_pct':6}
    BatchEnhancementGuard(ROOT/'runs/enhancement-pending','127.0.0.1:16384').check_clear()
    lock_run=ROOT/'runs/batch-lock-sample-687424b0'
    lock_events=[json.loads(line) for line in (lock_run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert sum(event['kind']=='single_lock_sample_intent' for event in lock_events)==1
    before=lock_run/'workflow-0001.png'
    after=ROOT/'runs/lock-stable-8b6c84f7.png'
    with Image.open(before) as a,Image.open(after) as b:
        assert inspect_batch_lock(a,'batch_enhancement',0,True)['locked'] is False
        assert inspect_batch_lock(b,'batch_enhancement',0,True)['locked'] is True
        verify_batch_lock_pixels(a,b,1,0)
    locked_resources=inspect_resources(inspect_screen(after))
    assert locked_resources.available==result['resources']
    assert locked_resources.gold_cost==0 and not any(locked_resources.reserved.values())
    report={'scope':'single_item_plus3_live_test_and_lock_sample','live_input_in_this_validator':False,
        'enhancement_confirmations':len(confirms),'actual_cost':actual,
        'enhancement':3,'locked':True,'lock_confirmations':1,'lock_changed_resources':False,
        'enhancement_pending':False,'full_workflow_complete':False,
        'sources':[str(prepare.relative_to(ROOT)),str((run/'result.json').relative_to(ROOT)),
                   str((lock_run/'events.jsonl').relative_to(ROOT)),str(after.relative_to(ROOT))]}
    (ROOT/'runs/live-batch-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
