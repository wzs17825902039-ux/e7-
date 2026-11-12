"""汇总实际遍历证据，严格区分位置覆盖与装备字段识别。不会连接模拟器。"""
import argparse
import json
from pathlib import Path


def audit(directory):
    directory=Path(directory)
    result=json.loads((directory/'result.json').read_text(encoding='utf8'))
    events=[json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf8').splitlines() if line]
    pages={event['page']:event for event in events if event['kind']=='traversal_page'}
    positions={}
    unknown=[]
    conflicts=[]
    fields=('level','rarity','enhancement','selected')
    level_scope=None
    for number,event in sorted(pages.items()):
        report=json.loads((directory/f'page-{number:04d}.json').read_text(encoding='utf8'))
        if report['source']!=event['image']:
            raise ValueError('页面观测与遍历日志原图不一致')
        scope=report.get('level_scope','verified')
        if level_scope is not None and level_scope!=scope:
            raise ValueError('页面等级识别口径不一致')
        level_scope=scope
        required=tuple(key for key in fields if key!='level') if scope=='ignored' else fields
        base=event['evidence']['relative_row']
        for card in report['cards']:
            position=(base+card['row'],card['column'])
            old=positions.get(position)
            if old:
                changed={key:[old[key],card[key]] for key in fields
                         if old[key] is not None and card[key] is not None and old[key]!=card[key]}
                if changed:
                    conflicts.append({'position':position,'page':number,'fields':changed})
            if not card['known'] or any(card[key] is None for key in required):
                unknown.append({'position':position,'page':number,
                                'missing_fields':[key for key in required if card[key] is None],
                                'image':report['source']})
            positions[position]=card
    evidence=result['evidence']
    scope_complete=(result['state']=='end_observed' and evidence['top_verified'] and evidence['end_verified'])
    expected=evidence['covered_full_rows']*7
    if evidence.get('last_row_partial'):
        tail=[key for key in positions if key[0]==evidence['covered_rows']-1]
        expected+=len(tail)
    contiguous=(len(positions)==expected and all((row,col) in positions
                for row in range(evidence['covered_full_rows']) for col in range(7)))
    elapsed=None
    if events:
        from datetime import datetime
        elapsed=round((datetime.fromisoformat(events[-1]['time'])-datetime.fromisoformat(events[0]['time'])).total_seconds(),3)
    required_verified=bool(scope_complete and contiguous and positions and not unknown and not conflicts)
    unread_levels=sum(card['level'] is None for card in positions.values())
    summary={'state':result['state'],'top_to_end_verified':scope_complete,
             'level_scope':level_scope,'unread_level_count':unread_levels,
             'position_count':len(positions),'position_coverage_consistent':contiguous,
             'known_at_last_observation':sum(bool(card['known']) for card in positions.values()),
             'unknown_observation_count':len(unknown),'unknown_observations':unknown,
             'positive_field_conflicts':conflicts,'page_count':len(pages),'elapsed_seconds':elapsed,
             'selection_inputs':result['selection_inputs'],'resource_confirmations':result['resource_confirmations'],
             'required_fields_verified':required_verified,
             'all_fields_verified':required_verified and unread_levels==0,
             'scope':'当前原生批量选择列表；不等同于总背包全部装备'}
    (directory/'audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    print(json.dumps(audit(args.directory),ensure_ascii=False,indent=2))
