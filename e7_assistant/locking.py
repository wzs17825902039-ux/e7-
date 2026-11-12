"""只从明确未锁状态上锁，不自动解锁，不盲目重试切换按钮。"""
from dataclasses import asdict

from .workflow import verify_lock_update


def ensure_locks(items,targets,observe,tap_lock,control,journal):
    if len({item.token for item in items})!=len(items):
        raise ValueError('装备卡片标识重复，不能唯一定位锁按钮')
    if not targets <= {item.token for item in items}:
        raise ValueError('上锁目标不在本批次')
    current=items
    for token in sorted(targets):
        control.checkpoint()
        fresh=observe()
        if [asdict(item) for item in fresh]!=[asdict(item) for item in current]:
            raise ValueError('上锁前装备或锁状态发生变化')
        item=next(item for item in fresh if item.token==token)
        if item.locked is True:
            current=fresh
            continue
        if item.locked is not False:
            raise ValueError('锁状态未确认，不点击切换按钮')
        control.checkpoint()
        journal.emit('equipment_lock_intent',token=token,equipment_id=item.equipment.equipment_id)
        tap_lock(token)
        after=observe()  # 状态未变或无法确认时异常停止，绝不第二次点击。
        verify_lock_update(fresh,after,{token})
        current=after
        journal.emit('equipment_lock_verified',token=token)
    return current
