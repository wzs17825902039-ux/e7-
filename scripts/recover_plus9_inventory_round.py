"""恢复指定已提交的 +9 结果，再继续原背包轮次；不重发旧确认。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from e7_assistant.adb import Adb
from e7_assistant.live_workflow import LiveWorkflowTask
from e7_assistant.rules import Equipment, Policy
from e7_assistant.tasks import Journal, TaskControl, Limits
from e7_assistant.workflow import BatchItem, WorkflowOptions, verify_batch
from e7_assistant.workflow_navigation import WorkflowNavigator


def main():
    original = ROOT/'runs/full-inventory-resume-1e8def8a'
    old = json.loads((original/'result.json').read_text(encoding='utf8'))
    directory = ROOT/'runs'/('plus9-inventory-recovery-'+uuid.uuid4().hex[:8])
    journal = Journal(directory)
    control = TaskControl(.2)
    adb = Adb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe',
              '127.0.0.1:16384', control)
    nav = WorkflowNavigator(adb, directory, control, journal)
    options = WorkflowOptions(source_index=0, slot='helmet', craft_count=10, first_target=3,
                              initial_disposal='extract', rounds=1, scan_pages=150, action_interval=.2)
    policy = Policy(**json.loads((ROOT/'config/policy.json').read_text(encoding='utf8')))
    task = LiveWorkflowTask(nav, options, policy,
                            Limits(gold=10000000, craft_material=10000, max_steps=300), control, journal)
    if '--after-sale' in sys.argv:
        from e7_assistant.batch_sale import BatchSaleDriver
        from e7_assistant.batch_sale_vision import SaleConfirmation
        pending=task.disposal_guard.read()
        if not pending or pending['operation_id'] not in {'107971d32276411ea93f2e63c614de0b','f16d35f5c69540ce9b6e26a92526114e'}:
            raise ValueError('指定已提交出售记录不存在，不操作')
        previous=json.loads((Path(pending['run_directory'])/'result.json').read_text(encoding='utf8'))
        baseline=pending['before']
        items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked'])
               for i in baseline['items']]
        screen=nav.read()
        sale=BatchSaleDriver(task.driver,guard=task.disposal_guard)
        rejected=set(baseline['rejected'])
        protected={i.token for i in items}-rejected
        reference=(ROOT/'runs/plus9-inventory-recovery-03e78fc4/workflow-0054.png'
                   if protected else pending['confirmation']['image'])
        if protected and screen.page in {'inventory','inventory_batch_selection','inventory_batch_selection_empty'}:
            from e7_assistant.batch_sale_vision import verify_sale_survivors
            from e7_assistant.workflow_screen import inspect_screen
            from e7_assistant.initial_cleanup import inspect_inventory
            for name in ('workflow-0002.png','workflow-0003.png'):
                saved=inspect_screen(ROOT/'runs/plus9-inventory-recovery-4968419f'/name)
                verify_sale_survivors(saved,reference,items,rejected)
            screen=nav.navigate('inventory')
            for current in (screen,nav.read()):
                inventory=inspect_inventory(current,track_gold=False)
                if (inventory.count,inventory.capacity)!=(baseline['inventory_count']-len(rejected),baseline['capacity']):
                    raise ValueError('出售后当前背包减量不符')
            if task.disposal_guard.read()!=pending:
                raise ValueError('出售记录变化')
            journal.emit('batch_sale_settled',operation_id=pending['operation_id'],disposed=sorted(rejected),
                         recovery_evidence='saved survivors twice and current inventory count twice')
            task.disposal_guard.settle(pending['operation_id'])
        else:
            sale.settle_result(items,rejected,protected,baseline['resources'],reference,
                               SaleConfirmation(**pending['confirmation']),baseline['inventory_count'],
                               baseline['capacity'],pending['operation_id'],screen.page)
        task.ledger.spent.update(previous['spent'])
        task.ledger.steps=previous['steps']
        task.untracked_enhancements=previous['untracked_enhancements']
        if '--settle-only' in sys.argv:
            nav.navigate('inventory')
            result={'state':'recovered','scope':'sale_receipt_only','disposed':sorted(rejected),
                    'protected':sorted(protected),'outcome_unknown':False,'last_image':nav.last_image}
            (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(result,ensure_ascii=False))
            return
        finish(task,{'state':'complete'},nav,directory,journal,original,
               completed_batches=previous['batches']+1)
        return
    if '--after-selection' in sys.argv:
        settled = ROOT/'runs/plus9-inventory-recovery-1cf5281d'
        previous = json.loads((settled/'result.json').read_text(encoding='utf8'))
        task.enhancement_guard.check_clear()
        task.disposal_guard.check_clear()
        selection = json.loads((original/'selection-0001.json').read_text(encoding='utf8'))
        nav.batch_inventory_context = selection['inventory_context']
        expected = [BatchItem(i['token'], Equipment(**i['equipment']), i['selected'], i['locked'])
                    for i in previous['items']]
        _, stable, resources = task.driver.observe(expected)
        if resources.has_preview:
            raise ValueError('已有预览，不继续')
        if any(asdict(a.equipment)!=asdict(b.equipment) or a.locked!=b.locked
               for a,b in zip(expected,stable)):
            raise ValueError('取消选择后的装备内容发生变化')
        task.ledger.spent.update(previous['spent'])
        task.ledger.steps = previous['steps']
        task.untracked_enhancements = previous['untracked_enhancements']
        result = task.run_batch(stable)
        finish(task, result, nav, directory, journal, original)
        return
    pending = task.enhancement_guard.read()
    if (not pending or pending['operation_id'] != '8495355a529b4ce0aa608da6251c7dc2'
            or Path(pending['run_directory']) != original or pending['confirmation']['target'] != 9):
        raise ValueError('指定 +9 未结算记录不存在或已变化，不操作')
    (directory/'original-pending.json').write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding='utf8')
    selection = json.loads((original/'selection-0001.json').read_text(encoding='utf8'))
    nav.batch_inventory_context = selection['inventory_context']
    before = [BatchItem(i['token'], Equipment(**i['equipment']), i['selected'], i['locked'])
              for i in pending['before']['items']]
    _, current, resources = task.driver.observe(before)
    verify_batch(before, current, 9)
    if resources.has_preview:
        raise ValueError('仍有强化预览，不结算也不重发')
    screen, stable, stable_resources = task.driver.observe(before)
    task.driver.unchanged(current, stable)
    task.driver.same_resources(resources, stable_resources)
    if task.enhancement_guard.read() != pending:
        raise ValueError('原确认记录发生变化')
    journal.emit('authorized_result_recovered', original=str(original), target=9,
                 image=screen.source, items=[asdict(i) for i in stable])
    task.enhancement_guard.settle(pending['operation_id'])
    task.ledger.spent.update(old['spent'])
    task.ledger.steps = old['steps']+1
    task.untracked_enhancements = old['untracked_enhancements']+1
    result = task.run_batch(stable, verified_recovery=(before, 9))
    finish(task, result, nav, directory, journal, original)


def finish(task, result, nav, directory, journal, original,completed_batches=1):
    if result['state'] == 'complete':
        task.completed_batches = completed_batches
        try:
            task.enhance_inventory_batches()
            journal.emit('round_finished', round=1, recovered_from=str(original))
        except Exception as exc:
            result['state'] = 'failed'
            journal.emit('failed', message=str(exc), outcome_unknown=task.uncertain)
    result.update(scope='recovered_inventory_round', batches=task.completed_batches,
                  steps=task.ledger.steps, spent=dict(task.ledger.spent),
                  untracked_enhancements=task.untracked_enhancements,
                  outcome_unknown=task.uncertain, last_image=nav.last_image)
    (directory/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    journal.emit('finished', **result)
    print(json.dumps({'directory':str(directory), 'state':result['state']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
