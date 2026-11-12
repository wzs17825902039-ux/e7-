"""保存流程截图页面识别证据，不连接游戏。"""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from e7_assistant.workflow_screen import inspect_screen

EXPECTED = ('home_menu','forge','rejected','forge','craft_confirmation','craft_result',
            'inventory_full','forge','inventory','inventory_manage','inventory_organize',
            'inventory_organize','extract_confirmation','inventory_manage',
            'inventory_batch_selection','inventory_batch_selection','batch_enhancement',
            'batch_enhancement','batch_enhancement','batch_enhancement','batch_enhancement','batch_organize')


def main():
    output = ROOT/'runs/workflow-screens.json'
    reports = []
    sources = [p for p in sorted((ROOT/'docs/assets/user-workflow-2026-11-09').glob('*.png'))
               if int(p.name[:2])<=22]
    for source, expected in zip(sources,EXPECTED,strict=True):
        try:
            result = asdict(inspect_screen(source))
        except ValueError as exc:
            result = {'source':str(source),'page':'rejected','error':str(exc)}
        result.update(expected=expected,matched=result['page']==expected,
                      sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        reports.append(result)
        print(source.name,result['page'],flush=True)
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if all(r['matched'] for r in reports) else 1


if __name__=='__main__':
    raise SystemExit(main())
