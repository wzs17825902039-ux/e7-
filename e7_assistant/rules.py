"""只评估观测，不执行游戏动作；未核实的预测不在此猜测。"""

from dataclasses import dataclass, field
import math


WEIGHTS = {
    "speed": 2, "crit": 1.5, "cdmg": 1.125, "atk_pct": 1,
    "hp_pct": 1, "def_pct": 1, "effectiveness": 1, "resistance": 1,
}
FLATS = {"atk_flat", "hp_flat", "def_flat"}
FLAT_WEIGHTS = {'atk_flat':3.46/39,'def_flat':4.99/31,'hp_flat':3.09/174}
FLAT_USES = {'atk_flat':'atk_pct','def_flat':'def_pct','hp_flat':'hp_pct'}
TEMPLATES = {
    "crit_dps": {"atk_pct", "hp_pct", "def_pct", "crit", "cdmg", "speed"},
    "slow_dps": {"atk_pct", "hp_pct", "def_pct", "crit", "cdmg"},
    "hp_dps": {"hp_pct", "def_pct", "crit", "cdmg"},
    "def_dps": {"def_pct", "hp_pct", "crit", "cdmg"},
    "bulk_resistance": {"hp_pct", "def_pct", "resistance"},
    "utility": {"hp_pct", "def_pct", "effectiveness", "speed"},
}
SLOTS = {"weapon", "helmet", "armor", "necklace", "ring", "boots"}
RIGHT_MAIN_STATS = {
    'necklace': ('atk_pct','hp_pct','def_pct','crit','cdmg','atk_flat','hp_flat','def_flat'),
    'ring': ('atk_pct','hp_pct','def_pct','effectiveness','resistance','atk_flat','hp_flat','def_flat'),
    'boots': ('atk_pct','hp_pct','def_pct','speed','atk_flat','hp_flat','def_flat'),
}


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}必须是数值")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name}必须是非负有限数值")


@dataclass
class Equipment:
    equipment_id: str
    rarity: str
    level: int | None
    enhancement: int
    slot: str
    stats: dict[str, float]
    main_stat_usable: bool
    recognition_ok: bool
    game_score: float | None = None
    reforged_speed: int | None = None
    reforged_speed_source: str | None = None
    preferred_use: str | None = None
    user_target: bool = False
    observation_scope: str = 'full'
    main_stat: str | None = None
    last_speed_increased: bool | None = None
    enhancement_bonus: bool = False
    early_speed_increased: bool | None = None
    red_speed_misses: int | None = None
    gear_set: str | None = None

    def __post_init__(self):
        from .custom_targets import SET_LABELS
        if self.gear_set is not None and self.gear_set not in SET_LABELS:
            raise ValueError('未知装备套装')
        if self.red_speed_misses is not None and (type(self.red_speed_misses) is not int or self.rarity!='red' or not 0<=self.red_speed_misses<=5):
            raise ValueError('红装累计未加速次数必须为0～5整数或未知')
        if self.early_speed_increased is not None and (type(self.early_speed_increased) is not bool or self.rarity!='red'):
            raise ValueError('前两档速度增长标记仅允许已确认红装的布尔值或未知')
        if type(self.enhancement_bonus) is not bool or self.enhancement_bonus and self.rarity!='red':
            raise ValueError('强化加成标记仅允许用于已确认红装')
        if self.last_speed_increased is not None and type(self.last_speed_increased) is not bool:
            raise ValueError('本次速度增长标记必须为布尔值或未知')
        if self.observation_scope not in ('full','purple_speed'):
            raise ValueError('未知装备识别范围')
        if self.observation_scope == 'purple_speed' and (self.rarity!='purple' or set(self.stats)!={'speed'}):
            raise ValueError('速度专读仅允许紫装的速度字段')
        if not isinstance(self.equipment_id, str) or not self.equipment_id.strip():
            raise ValueError("缺少装备ID")
        if self.rarity not in {"purple", "red", "blue"} or self.slot not in SLOTS:
            raise ValueError("未知品质或部位")
        if self.main_stat is not None and self.main_stat not in WEIGHTS.keys() | FLATS:
            raise ValueError('未知主属性')
        if self.level is not None and (type(self.level) is not int or self.level < 1):
            raise ValueError("装备等级无效")
        if type(self.enhancement) is not int or not 0 <= self.enhancement <= 15:
            raise ValueError("强化等级必须为0～15的整数")
        for key in ("main_stat_usable", "recognition_ok", "user_target"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key}必须为布尔值")
        if not isinstance(self.stats, dict) or len(self.stats) > 4:
            raise ValueError("副属性必须为最多4项的对象")
        for key, value in self.stats.items():
            if key not in WEIGHTS.keys() | FLATS:
                raise ValueError(f"未知副属性：{key}")
            number(value, key)
            if key == "speed" and type(value) is not int:
                raise ValueError("速度副属性必须为整数")
        if self.game_score is not None:
            number(self.game_score, "游戏分数")
        if self.reforged_speed is not None:
            number(self.reforged_speed, "重铸后速度")
            if type(self.reforged_speed) is not int:
                raise ValueError("重铸后速度必须为整数")
            if self.reforged_speed_source not in {"actual", "game_preview"}:
                raise ValueError("重铸后速度需要actual或game_preview来源")
        elif self.reforged_speed_source is not None:
            raise ValueError("重铸来源缺少对应速度值")
        if self.preferred_use is not None and self.preferred_use not in TEMPLATES:
            raise ValueError("未知用途模板")


@dataclass
class Policy:
    initial_speed_min: int = 2
    purple_plus6_speed_min: int = 8
    purple_plus9_speed_min: int = 12
    retain_speed_min: int = 16
    priority_speed_min: int = 20
    allow_draft_quality_rules: bool = False
    game_score_formula_confirmed: bool = False
    game_score_gates: dict[str, float] = field(default_factory=dict)
    right_main_stats: dict[str, list[str]] = field(default_factory=dict)
    ignore_equipment_level: bool = True
    sell_failed_purple: bool = False
    red_profile_enabled: bool = False
    discard_flat_right_without_speed: bool = False
    sell_failed_red: bool = False
    red_left_gates: dict[str,float] = field(default_factory=lambda:{'0':20,'3':26,'6':34,'9':40,'12':46,'15':52})
    red_right_gates: dict[str,float] = field(default_factory=lambda:{'0':18,'3':24,'6':32,'9':38,'12':44,'15':50})
    red_lock_score_margin: float = 3
    red_raw_speed_keep_min: int = 14
    custom_targets_enabled: bool = False
    custom_targets: list[dict] = field(default_factory=list)
    custom_left_gates: dict[str,float] = field(default_factory=dict)
    custom_right_gates: dict[str,float] = field(default_factory=dict)

    def __post_init__(self):
        from .custom_targets import validate_targets
        validate_targets(self.custom_targets_enabled,self.custom_targets)
        for gates in (self.custom_left_gates,self.custom_right_gates):
            if not isinstance(gates,dict) or gates and set(gates)!={'0','3','6','9','12','15'}:
                raise ValueError('自定义分数门槛需要完整的0、3、6、9、12、15档')
            for value in gates.values():
                number(value,'自定义分数门槛')
            if gates and list(gates[key] for key in ('0','3','6','9','12','15'))!=sorted(gates.values()):
                raise ValueError('自定义分数门槛应随强化阶段递增或相同')
        if type(self.red_raw_speed_keep_min) is not int or not 14<=self.red_raw_speed_keep_min<=16:
            raise ValueError('红装未重铸速度保留线必须为14～16整数')
        number(self.red_lock_score_margin,'红装上锁加权分增量')
        for key in ("initial_speed_min", "purple_plus6_speed_min", "purple_plus9_speed_min", "retain_speed_min", "priority_speed_min"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f"{key}必须为正整数")
        if self.retain_speed_min > self.priority_speed_min:
            raise ValueError("可选保留速度不能高于优先速度")
        for key in ("allow_draft_quality_rules", "game_score_formula_confirmed", "ignore_equipment_level", "sell_failed_purple",
                    "red_profile_enabled","sell_failed_red","discard_flat_right_without_speed"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key}必须为布尔值")
        for gates in (self.red_left_gates,self.red_right_gates):
            if not isinstance(gates,dict) or set(gates)!={'0','3','6','9','12','15'}:
                raise ValueError('红装阶段门槛必须覆盖0/3/6/9/12/15')
            for value in gates.values():
                number(value,'红装加权分门槛')
        if not isinstance(self.game_score_gates, dict):
            raise ValueError("游戏分数门槛必须为对象")
        if self.game_score_gates and not self.game_score_formula_confirmed:
            raise ValueError("先核对游戏分数口径，再启用阶段门槛")
        for key, value in self.game_score_gates.items():
            if key not in {"0", "3", "6", "9", "12", "15"}:
                raise ValueError("游戏分数门槛键必须为强化节点")
            number(value, "分数门槛")
        if not isinstance(self.right_main_stats,dict):
            raise ValueError('右三件主属性配置必须为对象')
        for slot,stats in self.right_main_stats.items():
            if (slot not in RIGHT_MAIN_STATS or not isinstance(stats,list)
                    or any(not isinstance(stat,str) or stat not in RIGHT_MAIN_STATS[slot] for stat in stats)
                    or len(stats)!=len(set(stats))):
                raise ValueError('右三件主属性配置包含无效部位、属性或重复值')


@dataclass
class Decision:
    equipment_id: str
    action: str
    reasons: list[str]
    routes: list[str]
    game_score: float | None
    weighted_score: float | None
    effective_scores: dict[str, float]
    target_level: int | None = None
    rule_version: str = "0.1"
    discard_allowed: bool = False


def evaluate(item: Equipment, policy: Policy | None = None) -> Decision:
    policy = policy or Policy()
    weights=WEIGHTS|FLAT_WEIGHTS
    total = sum(item.stats.get(k, 0) * w for k, w in weights.items())
    templates = {item.preferred_use: TEMPLATES[item.preferred_use]} if item.preferred_use else TEMPLATES
    effective = {
        name: sum(value*weights[k] for k,value in item.stats.items()
                  if k in keys or FLAT_USES.get(k) in keys)
        for name, keys in templates.items()
    }
    from .custom_targets import match_targets, needs_set_check
    custom_matches=match_targets(item,policy)
    if custom_matches:
        effective={'custom:'+name:total for name in custom_matches}

    def result(action, reasons, routes=(), *, discard_allowed=False, target_level=None):
        if custom_matches:
            reasons=[f'命中自定义搭配「{"、".join(custom_matches)}」：全部副词条加权分{total:.3f}']+reasons
        target = (target_level if target_level is not None else
                  min(15, (item.enhancement // 3 + 1) * 3)) if action == "continue" else None
        complete = item.observation_scope == 'full'
        return Decision(item.equipment_id, action, reasons, list(routes), item.game_score,
                        round(total, 3) if complete else None,
                        {k: round(v, 3) for k, v in effective.items()} if complete else {}, target,
                        discard_allowed=discard_allowed)

    if not item.recognition_ok:
        return result("review", ["装备识别结果未确认"])
    if not policy.ignore_equipment_level and item.level != 85:
        return result("review", ["当前规则仅支持普通85级装备"])
    if item.rarity == "blue":
        return result("stop", ["蓝装不自动投入；不处置装备"])
    expected_count = 3 if item.rarity == "purple" and item.enhancement < 12 else 4
    if (item.observation_scope=='full' and len(item.stats) != expected_count) or any(v <= 0 for v in item.stats.values()):
        return result("review", ["副属性数量或数值与品质/强化阶段不符，需重新识别"])
    speed = item.stats.get("speed", 0)
    if not custom_matches and needs_set_check(item,policy) and not (
            item.rarity=='red' and 12<=item.enhancement<15 and speed>=12):
        return result('store',['副词条满足自定义组合，但套装尚未可靠识别，暂存不出售'])
    if item.rarity=='purple' and item.slot=='boots':
        return result('stop',['紫装鞋子不进入强化路线；本规则不自动处置'])
    if item.rarity=='purple' and item.enhancement==15 and speed<=12:
        return result('stop',['紫装+15副速度不超过12，明确淘汰，本批结束后统一出售'],
                      discard_allowed=policy.sell_failed_purple)
    if (item.rarity=='red' and policy.discard_flat_right_without_speed and item.slot in RIGHT_MAIN_STATS
            and item.main_stat in FLATS and speed<=0):
        return result('stop',['右三件固定主属性且没有速度副词条，不强化'],
                      discard_allowed=policy.sell_failed_purple if item.rarity=='purple' else policy.sell_failed_red)
    if item.rarity == "purple" and speed < policy.initial_speed_min:
        return result("stop", ["紫装无速度或速度低于初始门槛，不继续强化"],
                      discard_allowed=policy.sell_failed_purple)
    if item.rarity=='purple' and 3<=item.enhancement<15 and item.last_speed_increased is False:
        return result('stop',['紫装本次强化未增加速度，从+3起停止投入并淘汰'],
                      discard_allowed=policy.sell_failed_purple)
    if item.rarity=='purple' and 6<=item.enhancement<9 and speed<policy.purple_plus6_speed_min:
        return result('stop',[f'紫装+6至+8速度低于{policy.purple_plus6_speed_min}，前两次强化追速不足，停止投入'],
                      discard_allowed=policy.sell_failed_purple)
    if (policy.sell_failed_purple and item.rarity=='purple' and item.enhancement>=9 and speed<policy.purple_plus9_speed_min
            and not (item.reforged_speed is not None and item.reforged_speed>=policy.retain_speed_min)):
        return result('stop',['紫装+9及以后速度低于12，且没有已确认的速度保留依据'],
                      discard_allowed=policy.sell_failed_purple)
    main_stat_usable=item.main_stat_usable
    if item.rarity=='red' and item.slot in RIGHT_MAIN_STATS and item.main_stat is not None:
        # 批量入口只登记主属性事实；可用性须按本次任务的策略重新计算。
        main_stat_usable=item.main_stat in policy.right_main_stats.get(item.slot,[])
    if not main_stat_usable and item.rarity!='purple':
        return result("store", ["主属性用途尚未匹配"])

    if item.rarity=='red' and 12<=item.enhancement<15 and speed>=12:
        return result('continue',['红装+12节点副速度达到12速，继续到+15；不受累计未加速或有效分限制'],
                      ['speed_plus12'],target_level=15)

    if item.rarity=='red' and (policy.red_profile_enabled or custom_matches):
        if speed>0 and item.enhancement<6:
            return result('continue',['带速度副词条的红装先强化到+6，再判断追速或有效用途；+3未加速度不止损'],
                          ['speed_potential'],target_level=3 if item.enhancement<3 else 6)
        stage=item.enhancement//3*3
        if stage==6 and speed>0 and item.early_speed_increased is True and item.red_speed_misses is None:
            return result('continue',['红装前两次强化至少一次增加速度，继续到+9；不受旧+6十速门槛限制'],
                          ['speed_early_hit'],target_level=9)
        gates=policy.red_left_gates if item.slot in {'weapon','helmet','armor'} else policy.red_right_gates
        if custom_matches:
            gates=(policy.custom_left_gates if item.slot in {'weapon','helmet','armor'} else policy.custom_right_gates) or gates
        matches=[name for name,score in effective.items()
                 if score>=gates[str(stage)] and (custom_matches or sum(k in templates[name] or FLAT_USES.get(k) in templates[name]
                                                    for k in item.stats)>=3)]
        speed_gate={0:policy.initial_speed_min,3:policy.initial_speed_min,6:10,9:10,12:15}
        speed_route=speed>=speed_gate.get(stage,policy.retain_speed_min)
        misses=item.red_speed_misses
        if stage==6 and misses is None and item.early_speed_increased is False:
            misses=2
        if stage in (6,9,12) and speed>0:
            speed_route=(misses is not None and misses<2) or speed>=policy.red_raw_speed_keep_min
        if item.enhancement==15:
            if speed>=policy.red_raw_speed_keep_min:
                return result('keep_candidate',[f'红装未重铸副速度达到{policy.red_raw_speed_keep_min}速保留线，确认上锁'],['speed_raw'])
            retained=item.reforged_speed if item.reforged_speed is not None else speed
            if retained>=policy.retain_speed_min:
                return result('keep_candidate',['红装速度达到保留线；确认上锁，不执行重铸'],['speed_optional'])
            concentrated=max((v for k,v in item.stats.items() if k in WEIGHTS and k!='speed'),default=0)>=25
            lock_matches=[name for name in matches if effective[name]>=gates['15']+policy.red_lock_score_margin]
            if lock_matches or concentrated:
                return result('keep_candidate',['红装有效用途分达到成品线，或单条非速度百分比达到25'],
                              ['red_quality:'+name for name in lock_matches] or ['red_concentrated'])
            if matches:
                return result('store',[f'红装达到成品保留线，但未达到加权上锁线{gates["15"]+policy.red_lock_score_margin:g}，暂存不出售'])
            if speed>=15 and item.reforged_speed is None:
                return result('store',['当前15速成品等待重铸预览核对，不自动出售'])
        elif speed_route or matches or item.user_target:
            reason=('红装当前副速度已达到未重铸保留线，继续到成品，不按低分淘汰'
                    if stage in (9,12) and speed>=policy.red_raw_speed_keep_min else
                    f'红装累计{misses}次未加速，不足2次，继续竞速逐档判断'
                    if stage in (6,9,12) and speed_route and misses is not None and misses<2 else
                    '红装累计至少2次未加速，转同用途有效加权分继续'
                    if stage in (6,9,12) and misses is not None and misses>=2 else
                    '红装优先追速；速度不达标时以高有效用途分继续')
            return result('continue',[reason],
                          (['speed_potential'] if speed_route else ['red_quality:'+name for name in matches])
                          +(['user_target'] if item.user_target else []))
        if stage in (6,9,12) and speed>0 and misses is None:
            return result('store',['缺少完整强化历史，累计未加速次数未知；有效分未通过时暂存，不猜测竞速资格或自动出售'])
        if custom_matches:
            return result('stop',[f'自定义总分{total:.3f}未达到+{stage}门槛{gates[str(stage)]:g}，且不满足追速条件'],
                          discard_allowed=policy.sell_failed_red)
        return result('stop',[f'红装未满足追速或同用途投入条件；副属性总分{total:.3f}，'
                              f'最高同用途有效分{max(effective.values(),default=0):.3f}，'
                              f'+{stage}阶段门槛{gates[str(stage)]:g}，用途须至少3条有效副词条'],
                      discard_allowed=policy.sell_failed_red)

    has_speed_route = item.slot != "boots" and speed >= policy.initial_speed_min
    if item.enhancement == 15:
        if has_speed_route and item.reforged_speed is None:
            # 当前实测值本身已达标即可保护；不据此声称重铸后的精确速度。
            if speed >= policy.priority_speed_min:
                return result("keep_candidate", ["当前副速度已达到优先保留线；确认上锁，重铸结果仍未知"], ["speed_priority"])
            if speed >= policy.retain_speed_min:
                return result("keep_candidate", ["当前副速度已达到可选保留线；确认上锁，未预测重铸增量"], ["speed_optional"])
        if has_speed_route and item.reforged_speed is not None:
            value = item.reforged_speed
            if value >= policy.priority_speed_min:
                return result("keep_candidate", ["重铸后达到优先速度档；保留后需确认上锁，不自动重铸"], ["speed_priority"])
            if value >= policy.retain_speed_min:
                return result("keep_candidate", ["重铸后达到可选速度档，需结合库存"], ["speed_optional"])
        if item.user_target:
            return result("store", ["指定用途已到+15，等待核对角色目标"], ["user_target"])
        # 当前只计算85级实际属性分；不能伪称已通过重铸后90分线。
        return result("store", ["等待用途或重铸结果核对；当前分数不能代替重铸后分数"])

    reasons = []
    routes = []
    if has_speed_route:
        if item.reforged_speed is not None and item.reforged_speed >= policy.priority_speed_min:
            routes.append("speed_priority")
            reasons.append("可信来源的重铸速度已达优先档")
        elif item.rarity == "purple" and item.enhancement >= 9 and speed < policy.purple_plus9_speed_min:
            reasons.append("紫装+9起速度低于12，20速机会低；+12不增长原有速度")
            if item.reforged_speed is not None and item.reforged_speed >= policy.retain_speed_min:
                routes.append("speed_optional")
                reasons.append("已有可选保留档重铸速度依据")
        else:
            routes.append("speed_potential")
            reasons.append("带速候选继续逐阶段观察，尚未证明最终可达20速")
    if item.user_target and item.rarity != 'purple':
        routes.append("user_target")
        reasons.append("用户明确指定继续此装备用途")

    # 非速度评分只有显式启用试验规则后才参与继续判断。
    if policy.allow_draft_quality_rules and item.rarity != 'purple':
        matches = [name for name, score in effective.items()
                   if score >= 20 and sum(item.stats.get(k, 0) > 0 for k in templates[name]) >= 3]
        quality = total >= 28 and bool(matches)
        gate = policy.game_score_gates.get(str(item.enhancement))
        if quality and gate is not None:
            if item.game_score is None:
                reasons.append("综合用途缺少当前游戏分数，不能核对配置门槛")
                quality = False
            elif item.game_score < gate:
                reasons.append("综合用途未达到配置的游戏分数门槛")
                quality = False
        if quality:
            routes.extend("quality:" + name for name in matches)
            reasons.append("达到显式启用的试验性用途投入线；未使用G止损线")

    if routes:
        return result("continue", reasons, routes)
    if item.stats.keys() & FLATS:
        return result("review", reasons + ["固定属性价值尚未换算，不能按缺失分淘汰"])
    if has_speed_route:
        return result("store", reasons + ["需评估16～19速潜力或其他用途，不直接判废"])
    return result("review", reasons + ["没有已启用的可执行用途规则，等待指定用途或门槛"])
