"""显式启用的红装搭配筛选；匹配组合后使用全部副属性加权分。"""

SET_GROUPS = (
    ('crit', 'hit', 'speed'),
    ('attack', 'health', 'defense', 'protection'),
    ('resistance', 'destruction', 'lifesteal', 'counter'),
    ('immunity', 'rage', 'unity'),
    ('injury', 'revenge', 'penetration', 'torrent'),
)
SET_LABELS = dict(zip((key for group in SET_GROUPS for key in group), (
    '暴击', '命中', '速度', '攻击', '生命', '防御', '守护',
    '抗性', '破灭', '吸血', '反击', '免疫', '愤怒', '夹攻',
    '伤口', '复仇', '穿透', '激流')))


def validate_targets(enabled, rules):
    from .rules import WEIGHTS, FLATS
    if type(enabled) is not bool or not isinstance(rules, list) or len(rules)>32:
        raise ValueError('自定义搭配开关必须为布尔值，组合最多32组')
    names=set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule)!={'name','sets','stats'}:
            raise ValueError('每组搭配需要名称、套装和副词条')
        name=rule['name']
        if not isinstance(name,str) or not name.strip() or len(name)>40 or name in names:
            raise ValueError('搭配名称需唯一且为1～40字符')
        names.add(name)
        for key,allowed,maximum in (('sets',SET_LABELS,19),('stats',WEIGHTS.keys()|FLATS,4)):
            values=rule[key]
            if (not isinstance(values,list) or len(values)>maximum
                    or any(not isinstance(value,str) or value not in allowed for value in values)
                    or len(values)!=len(set(values))):
                raise ValueError('套装或副词条选择无效；每组副词条最多4项')
        if not rule['stats']:
            raise ValueError('每组至少选择一个副词条；套装留空表示任意套装')
    if enabled and not rules:
        raise ValueError('启用自定义搭配前请至少添加一组规则')


def match_targets(item, policy):
    if not policy.custom_targets_enabled or item.rarity!='red':
        return []
    return [rule['name'] for rule in policy.custom_targets
            if all(item.stats.get(key,0)>0 for key in rule['stats'])
            and (not rule['sets'] or item.gear_set in rule['sets'])]


def needs_set_check(item, policy):
    return (policy.custom_targets_enabled and item.rarity=='red' and item.gear_set is None
            and any(rule['sets'] and all(item.stats.get(key,0)>0 for key in rule['stats'])
                    for rule in policy.custom_targets))
