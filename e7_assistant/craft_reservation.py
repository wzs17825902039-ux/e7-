"""结果页遮挡材料余额时的预算预留；预测值不计作实测消耗。"""
from dataclasses import dataclass, field


@dataclass
class CraftReservation:
    ledger: object
    before: dict
    cost: dict
    committed: int = 0
    observed_gold: int | None = None
    reserved: dict = field(default_factory=dict)
    settled: bool = False
    material_observed: bool = False
    reconciled: bool = False

    def __post_init__(self):
        self.before = dict(self.before)
        self.cost = dict(self.cost)
        if set(self.cost) not in ({'gold','craft_material'},{'craft_material'}) or any(type(v) is not int or v <= 0 for v in self.cost.values()):
            raise ValueError('打造预留需要正整数金币和材料费用')
        if any(type(self.before.get(k)) is not int or self.before[k] < 0 for k in self.cost):
            raise ValueError('打造起始余额未确认')
        self.observed_gold = self.before.get('gold')
        self.reserved = dict.fromkeys(self.cost,0)

    def check_next(self):
        if self.settled:
            raise ValueError('已结算会话不能继续制作')
        if 'gold' in self.cost and self.observed_gold != self.before['gold']-self.reserved['gold']:
            raise ValueError('上一批制作结果未确认，禁止继续制作')
        if self.ledger.steps + self.committed >= self.ledger.limits.max_steps:
            raise ValueError('达到任务操作次数上限')
        cumulative = {k:self.reserved[k]+self.cost[k] for k in self.cost}
        if 'gold' in self.cost:
            self.ledger.check(cumulative,self.before)
        else:
            if cumulative['craft_material']>self.before['craft_material']:
                raise ValueError('打造材料不足')
            if self.ledger.spent['craft_material']+cumulative['craft_material']>self.ledger.limits.craft_material:
                raise ValueError('craft_material超过本任务剩余预算')
        return cumulative

    def mark_commit(self):
        """调用者必须先持久化确认意图，再预留并只发送一次确认。"""
        self.reserved = self.check_next()
        self.committed += 1

    def observe_gold(self,gold):
        if 'gold' not in self.cost:
            raise ValueError('当前打造不识别金币')
        if type(gold) is not int or gold < 0:
            raise ValueError('金币余额未确认')
        expected = self.before['gold']-self.reserved['gold']
        self.observed_gold=gold
        if gold != expected:
            raise ValueError(f'金币实际余额与累计制作费用不符：实测{gold}，预期{expected}')
        self.observed_gold = gold

    def settle(self,after):
        if self.settled:
            raise ValueError('禁止重复结算打造会话')
        if not self.committed:
            if any(after.get(k)!=self.before[k] for k in self.cost):
                raise ValueError('未确认制作但资源发生变化')
            self.settled=True
            self.reconciled=True
            return {}
        # Ledger负责记录实测差额，包括不匹配时的差额；只允许尝试结算一次。
        self.settled=True
        self.material_observed=type(after.get('craft_material')) is int
        previous_steps=self.ledger.steps
        try:
            result=self.ledger.settle(self.before,after,self.reserved)
            self.reconciled=True
            return result
        finally:
            if self.ledger.steps != previous_steps:
                self.ledger.steps=previous_steps+self.committed

    def evidence(self):
        return {'confirmed_attempts':self.committed,'reserved_cost':dict(self.reserved),
                'observed_gold':self.observed_gold,'material_balance_observed':self.material_observed,
                'reconciled':self.reconciled,
                'notice':'预留成本不是材料实测扣款；须回到制作页结算'}
