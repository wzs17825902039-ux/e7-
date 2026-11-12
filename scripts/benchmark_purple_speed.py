"""同一16件实机截图比较专读字段；错误结果不得算作提速通过。"""
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.purple_speed_vision import inspect_purple_speed_batch
from e7_assistant.workflow import BatchItem
from e7_assistant.rules import Equipment


def main():
    source=ROOT/'docs/assets/batch-selection-2026-11-10/round-stage3-zero.png'
    baseline=json.loads((ROOT/'runs/verified-round-stage3-diagnostic.json').read_text(encoding='utf8'))
    expected=[BatchItem(str(i),Equipment(**record['equipment']),record['selected'],record['locked'])
              for i,record in enumerate(baseline['records'])]
    results=[]
    for mode,reader in (('cold',inspect_screen),('warm',inspect_screen)):
        driver=BatchEnhancementDriver(None,purple_speed_only=True)
        items=driver.normalize_items(expected)
        start=perf_counter()
        screen=reader(source)
        report=inspect_purple_speed_batch(screen,items,driver.speed_rows,{})
        seconds=perf_counter()-start
        diffs=[]
        def fields(record):
            return {'enhancement':record['equipment']['enhancement'],
                    'speed':record['equipment']['stats']['speed'],
                    'selected':record['selected'],'locked':record['locked']}
        for index,(actual,truth) in enumerate(zip(report['records'],baseline['records'])):
            if fields(actual)!=fields(truth):
                diffs.append({'index':index,'actual':fields(actual),'expected':fields(truth)})
        result={'mode':mode,'seconds':seconds,'same_required_fields':not diffs,'diffs':diffs}
        results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    (ROOT/'runs/purple-speed-benchmark-final.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
