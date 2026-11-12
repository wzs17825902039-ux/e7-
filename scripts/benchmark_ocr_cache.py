"""对同一组真实截图比较原推理与精确输入缓存，不连接游戏。"""
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from e7_assistant.local_ocr import CachedOCREngine
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.batch_vision import inspect_batch


def main():
    from rapidocr_onnxruntime import RapidOCR
    raw = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    paths = [ROOT/'runs/batch-selection-probe-16c46965'/name
             for name in ('workflow-0058.png', 'workflow-0060.png')]
    result, reports = {}, {}
    # 相同模型实例；先独立热身，避免把模型加载计入优化收益。
    raw(str(paths[0]), use_cls=False)
    for name, entries in (('uncached', 0), ('cached', 512)):
        engine = CachedOCREngine(raw, max_entries=entries)
        observations, times = [], []
        with patch('e7_assistant.local_ocr._engine', return_value=engine):
            for path in paths:
                start = perf_counter()
                screen = inspect_screen(path)
                batch = inspect_batch(path, {i: 'helmet' for i in range(16)})
                times.append(perf_counter()-start)
                observations.append({'page': screen.page, 'words': screen.words, 'batch': batch})
        reports[name] = json.dumps(observations, ensure_ascii=False, sort_keys=True,
                                  default=lambda value: asdict(value) if is_dataclass(value) else str(value))
        result[name] = {'seconds': sum(times), 'per_frame_seconds': times,
                        'hits': engine.hits, 'misses': engine.misses,
                        'cached_input_bytes': engine.bytes}
    result['identical_results'] = reports['uncached'] == reports['cached']
    result['speedup'] = result['uncached']['seconds']/result['cached']['seconds']
    target = ROOT/'runs/ocr-cache-benchmark.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))
    return int(not result['identical_results'])


if __name__ == '__main__': raise SystemExit(main())
