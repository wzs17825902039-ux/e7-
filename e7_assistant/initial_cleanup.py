"""打造后按游戏现有预设整理；不用于强化后的淘汰出售。"""
from dataclasses import asdict, dataclass
import hashlib
import re


@dataclass(frozen=True)
class CleanupInventory:
    count: int
    capacity: int
    selected: int | None
    gold: int | None
    image: str


def _field(screen, region, pattern, label):
    words = [word for word in screen.words
             if region[0] <= word['center'][0] < region[2]
             and region[1] <= word['center'][1] < region[3]]
    if label=='快速选择数量' and (len(words)!=1 or words[0]['confidence']<.95):
        from .local_ocr import read_local_regions
        if any(w['confidence']>=.95 for w in words):
            raise ValueError(f'{label}包含多个候选，不能用局部读数覆盖')
        values,details=read_local_regions(screen.source,{'selected':region})
        evidence=details['selected'];value=values['selected']
        votes=[c for c in evidence.get('candidates',[]) if c['confidence']>=.95]
        # 方括号及邻近刷新图标会被读成多余括号；数字仍须多候选一致。
        numeric_votes=[re.fullmatch(r'[\[\]]*([0-9]+)[\[\]]*',c['text']) for c in votes]
        if (len(numeric_votes)>=2 and all(numeric_votes)
                and len({m[1] for m in numeric_votes})==1):
            value=numeric_votes[0][1]
            match=re.fullmatch(pattern,value)
            if match:
                return match
        match=re.fullmatch(pattern,value)
        if (evidence.get('accepted') and match and len(votes)>=2
                and all(c['text']==value for c in votes)
                and all(w['confidence']<.95 or w['text']==value for w in words)):
            return match
    # 低置信度冲突也不能忽略；字段必须完整、唯一。
    if len(words)==1 and label=='金币' and .9<=words[0]['confidence']<.95:
        from .local_ocr import read_local_regions
        values,details=read_local_regions(screen.source,{'gold':region})
        evidence=details['gold'];value=words[0]['text']
        raw=[c for c in evidence.get('candidates',[]) if c['variant']=='raw' and c['confidence']>=.95 and c['text']==value]
        conflicts=[c for c in evidence.get('candidates',[]) if c['confidence']>=.95 and c['text']!=value]
        if evidence.get('accepted') and evidence.get('confidence',0)>=.95 and values['gold']==value and raw and not conflicts:
            match=re.fullmatch(pattern,value)
            if match:return match
    if len(words) != 1 or words[0]['confidence'] < .95:
        raise ValueError(f'{label}未唯一可靠读取')
    match = re.fullmatch(pattern, words[0]['text'])
    if not match:
        raise ValueError(f'{label}格式无效')
    return match


def inspect_inventory(screen,track_gold=True):
    if screen.page not in {'inventory', 'inventory_manage', 'inventory_organize'}:
        raise ValueError('整理数量只能在无遮挡背包页面读取')
    count = _field(screen, (1000, 80, 1125, 130), r'([0-9]+)/([0-9]+)', '背包数量')
    gold = (_field(screen, (650, 15, 800, 55),
                  r'(0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)', '金币') if track_gold else None)
    selected = None
    if screen.page == 'inventory_organize':
        # 方括号是计数装饰，允许OCR漏掉任一侧；不替换任何数字。
        selected = int(_field(screen, (700, 80, 790, 130),
                              r'\[?([0-9]+)\]?', '快速选择数量')[1])
    current, capacity = int(count[1]), int(count[2])
    if capacity <= 0 or selected is not None and selected > current:
        raise ValueError('背包容量或选择数量不合理')
    return CleanupInventory(current, capacity, selected, int(gold[1].replace(',', '')) if gold else None, screen.source)


@dataclass(frozen=True)
class CleanupConfirmation:
    action: str
    image: str
    digest: str


def inspect_confirmation(screen, action):
    from PIL import Image
    if action not in {'extract', 'sell'}:
        raise ValueError('初次清理只允许萃取或出售')
    label = '萃取' if action == 'extract' else '出售'
    page = 'extract_confirmation' if action == 'extract' else 'sale_confirmation'
    if screen.page != page:
        raise ValueError('处置确认弹窗与所选方式不一致')
    # 产物超过一行时弹窗向上下扩展，标题和按钮随之移动。
    screen.find(label + '装备', (400, 80, 880, 220), .95)
    screen.find(label, (650, 490, 850, 630), .95)
    screen.find('取消', (400, 490, 650, 630), .95)
    # 不使用被遮挡的底层数量；保留中央弹窗（含产物）的像素指纹。
    with Image.open(screen.source) as image:
        if image.size != (screen.width, screen.height):
            raise ValueError('确认截图尺寸不一致')
        # 标题已由文字确认；其上沿有轻微闪光，产物和确认按钮才需要稳定。
        box = tuple(round(v * (screen.width/1280 if i % 2 == 0 else screen.height/720))
                    for i, v in enumerate((400, 230, 880, 630)))
        digest = hashlib.sha256(image.convert('RGB').crop(box).tobytes()).hexdigest()
    return CleanupConfirmation(action, screen.source, digest)


def verify_cleanup(before, after, action):
    if action not in {'extract', 'sell'} or not before.selected:
        raise ValueError('缺少有效处置方式或选择数量')
    removed = before.count - after.count
    if before.capacity != after.capacity or not 0 < removed <= before.selected:
        raise ValueError('实际背包减少数量与选择不符，结果需复核')
    if after.selected not in (None, 0):
        raise ValueError('处置后仍有选中装备，结果需复核')
    if action == 'sell' and removed != before.selected:
        raise ValueError('出售件数与确认前选择数量不一致')
    if action == 'extract' and after.gold != before.gold:
        raise ValueError('萃取期间金币变化，需复核')
    if action == 'sell' and before.gold is not None and after.gold is not None and after.gold <= before.gold:
        raise ValueError('未观察到出售金币收入')
    return {'action': action, 'selected': before.selected, 'removed': removed,
            'not_removed': before.selected - removed, 'image': after.image}


class InitialCleanupDriver:
    def __init__(self, navigator, inventory_reader=inspect_inventory,
                 confirmation_reader=inspect_confirmation, guard=None):
        from .disposal_guard import DisposalGuard
        self.navigator = navigator
        self.inventory_reader = (lambda screen:inspect_inventory(screen,track_gold=False)) if inventory_reader is inspect_inventory else inventory_reader
        self.confirmation_reader = confirmation_reader
        self.guard = guard if guard is not None else DisposalGuard(
            navigator.directory.parent / 'disposal-pending', navigator.adb.serial)
        self.pending = False

    def _emit(self, kind, **data):
        if self.navigator.journal:
            self.navigator.journal.emit(kind, **data)

    def _click(self, screen, label, region):
        word = screen.find(label, region, .95)
        self.navigator.control.checkpoint()
        self.navigator.adb.tap(*(round(v) for v in word['center']))

    def initial_cleanup(self, action='extract'):
        if action not in {'extract', 'sell'}:
            raise ValueError('初次清理只允许萃取或出售')
        if self.pending:
            raise ValueError('上次处置结果未知，禁止再次执行清理')
        self.guard.check_clear()
        nav = self.navigator
        nav.navigate('inventory')
        nav.transition('manage')
        screen = nav.transition('organize')
        before = self.inventory_reader(screen)
        if before.selected != 0:
            raise ValueError('已有用户勾选，未清空或覆盖')
        self._emit('cleanup_quick_select_intent', image=screen.source)
        self._click(screen, '快速选择', (130, 75, 280, 135))
        nav.control.wait(.4)
        screen = nav.read()
        selected = self.inventory_reader(screen)
        if (before.count, before.capacity, before.gold) != (selected.count, selected.capacity, selected.gold):
            raise ValueError('快速选择期间背包数量、容量或金币变化')
        self._emit('cleanup_selection_observed', **asdict(selected))
        if selected.selected == 0:
            return {'action': action, 'selected': 0, 'removed': 0, 'not_removed': 0,
                    'image': screen.source}
        # 第二次读取仅核对，不再次点击快速选择或更改预设。
        screen = nav.read()
        fresh = self.inventory_reader(screen)
        if (fresh.count, fresh.capacity, fresh.gold, fresh.selected) != (
                selected.count, selected.capacity, selected.gold, selected.selected):
            raise ValueError('处置入口前选择数量或资源发生变化')
        label = '萃取' if action == 'extract' else '出售'
        self._click(screen, label, (350, 75, 650, 135))
        confirmation = None
        for _ in range(6):
            nav.control.wait(.4)
            screen = nav.read()
            if screen.page == 'inventory_organize' or screen.page == 'unknown':
                continue
            confirmation = self.confirmation_reader(screen, action)
            break
        if confirmation is None:
            raise TimeoutError('处置弹窗未确认，未重复点击入口')
        screen = nav.read()
        fresh_confirmation = self.confirmation_reader(screen, action)
        if confirmation.digest != fresh_confirmation.digest:
            raise ValueError('确认弹窗或产物发生变化，未确认')
        operation_id = self.guard.begin(action, asdict(selected), asdict(confirmation), nav.directory)
        self.pending = True  # 持久化后输入失败、日志失败或停止也不得自动重试。
        self._emit('cleanup_commit_intent', operation_id=operation_id,
                   pending_record=str(self.guard.path), action=action, selected=selected.selected,
                   inventory=selected.count, image=screen.source, digest=confirmation.digest)
        self._click(screen, label, (650, 490, 850, 630))
        for _ in range(8):
            nav.control.wait(.5)
            screen = nav.read()
            if screen.page in {'unknown', 'extract_confirmation', 'sale_confirmation'}:
                continue
            after = self.inventory_reader(screen)
            self._emit('cleanup_result_observed', **asdict(after))
            if (after.count,after.capacity,after.selected,after.gold)==(
                    selected.count,selected.capacity,selected.selected,selected.gold):
                continue  # 弹窗已关闭但服务器尚未回包；只等待，不重复确认。
            result = verify_cleanup(selected, after, action)
            stable = self.inventory_reader(nav.read())
            if (stable.count, stable.capacity, stable.selected, stable.gold) != (
                    after.count, after.capacity, after.selected, after.gold):
                raise ValueError('处置结果未稳定，禁止重复确认')
            self._emit('cleanup_settled', operation_id=operation_id, **result)
            self.guard.settle(operation_id)
            self.pending = False
            return result
        raise TimeoutError('处置结果未知，禁止重复确认或改为其他处置方式')
