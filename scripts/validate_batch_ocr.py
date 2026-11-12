"""三张真实批量截图回归；拒识与错误分开统计，不进行任何游戏操作。"""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from e7_assistant.batch_vision import inspect_batch


def main():
    truth = json.loads((ROOT / 'examples/batch-ocr-truth.json').read_text(encoding='utf8'))
    pages = []
    for filename, enhanced, selected in [('17-batch-target.png', False, range(16)),
                                         ('18-batch-result.png', True, range(16)),
                                         ('19-deselect-rejected.png', True, [11,15])]:
        source = ROOT / 'docs/assets/user-workflow-2026-11-09' / filename
        started = time.monotonic()
        report = inspect_batch(source, 'helmet', engine='rapidocr')
        actual = {r['index']: r for r in report['records']}
        errors, matches, rejected, main_rejected = [], 0, 0, 0
        # 逐格目视抄录图18主属性，图19仅取消选中，主属性相同。
        after_main = [1188,1404,1188,1404,1188,1404,1188,1188,
                      1188,1188,1296,1296,1296,1296,1296,1296]
        for index, (rarity, score, stats) in enumerate(truth['initial']):
            enhancement = 0
            if enhanced:
                enhancement, score, values = truth['after'][index]
                stats = dict(zip(stats, values, strict=True))
            expected = {'rarity': rarity, 'game_score': score, 'stats': stats,
                        'enhancement': enhancement, 'level':85, 'selected':index in selected}
            if index not in actual:
                rejected += 1
                main_rejected += 1
                continue
            observed = {**actual[index]['equipment'], 'selected':actual[index]['selected']}
            mismatch = {key: {'expected':value, 'actual':observed[key]}
                        for key,value in expected.items() if value != observed[key]}
            matches += len(expected) - len(mismatch)
            expected_main = {'stat':'hp_flat','value':after_main[index] if enhanced else 540}
            if actual[index].get('main') is None:
                main_rejected += 1
            elif actual[index]['main'] != expected_main:
                mismatch['main'] = {'expected':expected_main,'actual':actual[index]['main']}
            else:
                matches += 1
            if mismatch:
                errors.append({'index':index, 'mismatches':mismatch})
        report.pop('items')
        pages.append({'file':filename, 'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                      'seconds':round(time.monotonic()-started,2), 'cards':16,
                      'accepted':len(actual), 'rejected':rejected, 'matched_fields':matches,
                      'main_accepted':16-main_rejected, 'main_rejected':main_rejected,
                      'wrong_cards':len(errors), 'errors':errors, 'recognition':report})
    output = {'scope':'3张同一批头盔截图，不代表其他装备或分辨率', 'pages':pages,
              'accepted':sum(p['accepted'] for p in pages),
              'rejected':sum(p['rejected'] for p in pages),
              'wrong_cards':sum(p['wrong_cards'] for p in pages), 'total':48}
    output['main_accepted'] = sum(p['main_accepted'] for p in pages)
    output['main_rejected'] = sum(p['main_rejected'] for p in pages)
    target = ROOT / 'runs/batch-ocr-validation.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in output.items() if k!='pages'},ensure_ascii=False))
    for p in pages:
        print(p['file'], 'accepted', p['accepted'], 'rejected',p['rejected'],'errors',p['errors'])
    return 1 if output['wrong_cards'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
