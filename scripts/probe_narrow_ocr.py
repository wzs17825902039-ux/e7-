"""离线比较较窄数字推理张量；只使用已核对的+3实际结果。"""
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.local_ocr import CachedOCREngine
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.batch_vision import inspect_batch


def main():
    from rapidocr_onnxruntime import RapidOCR
    source=ROOT/'runs/verified-batch-round-7d9c6b20/workflow-0064.png'
    baseline=json.loads((ROOT/'runs/verified-round-stage3-diagnostic.json').read_text(encoding='utf8'))
    def fields(report):
        return [{key:item[key] for key in ('equipment','selected','locked','main')}
                for item in report['records']]
    results=[]
    for width in (96,64):
        raw=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        raw.text_rec.rec_image_shape=[3,48,width]
        raw.text_rec.rec_batch_num=16
        engine=CachedOCREngine(raw)
        with patch('e7_assistant.local_ocr._engine',return_value=engine):
            start=perf_counter()
            screen=inspect_screen(source)
            report=inspect_batch(source,{i:'helmet' for i in range(16)})
            seconds=perf_counter()-start
        results.append({'width':width,'seconds':seconds,'page':screen.page,'issues':report['issues'],
                        'same_fields':fields(report)==fields(baseline)})
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    (ROOT/'runs/narrow-ocr-probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
