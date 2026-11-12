"""离线截图基准：模型预热后清空输入缓存，比较完整与按品质读取。无ADB。"""
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.batch_vision import inspect_batch
from e7_assistant.local_ocr import _engine
from e7_assistant.workflow_screen import inspect_batch_controls


def main():
    started=perf_counter()
    engine=_engine()
    initialization=perf_counter()-started
    results=[]
    for filename,slots in (
            ('docs/assets/batch-live-2026-11-10/07-plus9-speed8.png',
             {i:'helmet' if i<13 else 'ring' for i in range(16)}),
            ('runs/after-current-commit-175808.png',
             {i:'helmet' if i<2 else 'boots' if i<7 else 'ring' for i in range(16)})):
        source=ROOT/filename
        # 先完成一次未计时推理，排除首次模型执行/内存分配对full模式的偏置。
        inspect_batch_controls(source)
        inspect_batch(source,slots,ignore_levels=True,require_score=False,ignore_purple_main=True)
        baseline=None
        for mode in ('full','mixed'):
            with engine.lock:
                engine.cache.clear()
                engine.bytes=0
            start=perf_counter()
            screen=inspect_batch_controls(source)
            controls_seconds=perf_counter()-start
            report=inspect_batch(source,slots,ignore_levels=True,require_score=False,ignore_purple_main=True,
                                 purple_speed_only=mode=='mixed')
            seconds=perf_counter()-start
            diffs=[]
            if mode=='full':
                baseline=report
            elif baseline and not baseline['issues']:
                if len(report['records'])!=len(baseline['records']):diffs.append('card_count')
                for actual,truth in zip(report['records'],baseline['records']):
                    a,b=actual['equipment'],truth['equipment']
                    fields=('rarity','enhancement','slot','level')
                    expected_stats=({'speed':b['stats']['speed']}
                                    if a['observation_scope']=='purple_speed' else b['stats'])
                    if (any(a[k]!=b[k] for k in fields) or a['stats']!=expected_stats
                            or actual['selected']!=truth['selected'] or actual['locked']!=truth['locked']):
                        diffs.append(actual['index'])
            result={'frame':filename,'mode':mode,'seconds':round(seconds,4),
                    'controls_seconds':round(controls_seconds,4),'cards':len(report['records']),
                    'speed_only_cards':sum(r['equipment']['observation_scope']=='purple_speed' for r in report['records']),
                    'issues':report['issues'],'differences_from_full':diffs,
                    'passed':screen.page=='batch_enhancement' and not report['issues'] and not diffs
                             and len(report['records'])==16 and baseline is not None and not baseline['issues']}
            results.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
    output={'scope':'offline_only_no_device','model_initialization_seconds':round(initialization,4),
            'cache':'cleared before every mode; untimed full inference warms the model first','results':results,
            'notice':'No capture, input, UI wait or game animation time included. Full mode is a consistency baseline, not independent truth.'}
    (ROOT/'runs/mixed-batch-offline-benchmark-2026-11-11.json').write_text(
        json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    return int(not all(r['passed'] for r in results))


if __name__=='__main__':raise SystemExit(main())
