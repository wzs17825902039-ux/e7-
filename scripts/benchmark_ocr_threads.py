"""离线测试线程配置；每帧清空输入缓存，不把同图缓存当成新画面速度。"""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from e7_assistant.local_ocr import CachedOCREngine
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.purple_speed_vision import inspect_purple_speed_batch
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.workflow import BatchItem
from e7_assistant.rules import Equipment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threads', type=int, nargs='+', default=[2, 1, 4])
    parser.add_argument('--output', default='runs/ocr-thread-benchmark.json')
    args = parser.parse_args()
    from rapidocr_onnxruntime import RapidOCR
    assets = ROOT/'docs/assets/batch-selection-2026-11-10'
    initial = json.loads((assets/'purple-speed-truth.json').read_text(encoding='utf8'))
    final = json.loads((ROOT/'runs/authorized-round-recovery-26c1843a/result.json').read_text(encoding='utf8'))['items']
    original = [BatchItem(str(i), Equipment(**r['equipment']), r['selected'], r['locked'])
                for i, r in enumerate(initial)]
    def fields(record):
        return {'speed': record['equipment']['stats']['speed'],
                'enhancement': record['equipment']['enhancement'],
                'selected': record['selected'], 'locked': record['locked']}
    results = []
    for threads in args.threads:
        loading = perf_counter()
        raw = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=threads)
        initialization_seconds = perf_counter()-loading
        for filename, truth in [('round-stage3-zero.png', initial), ('final-red-badge.png', final)]:
            engine = CachedOCREngine(raw)
            driver = BatchEnhancementDriver(None, purple_speed_only=True)
            items = driver.normalize_items(original)
            result = {'threads': threads, 'frame': filename,
                      'model_initialization_seconds': initialization_seconds}
            start = perf_counter()
            try:
                with patch('e7_assistant.local_ocr._engine', return_value=engine):
                    screen = inspect_screen(assets/filename)
                    report = inspect_purple_speed_batch(screen, items, driver.speed_rows, {})
                diffs = [{'index': i, 'actual': fields(a), 'expected': fields(b)}
                         for i, (a, b) in enumerate(zip(report['records'], truth)) if fields(a) != fields(b)]
                result.update(page=screen.page, diffs=diffs,
                              passed=screen.page == 'batch_enhancement' and len(report['records']) == len(truth) and not diffs)
            except Exception as exc:
                result.update(passed=False, error=str(exc))
            result['seconds'] = perf_counter()-start
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    output = ROOT/args.output
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    return int(not all(r['passed'] for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
