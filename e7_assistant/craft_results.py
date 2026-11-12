"""制作结果驱动的辅助统计；统计拒识不改变制作成功与否。"""


def material_shortage(screen):
    return any(word.get('confidence',0)>=.85 and '不足' in word['text']
               and any(label in word['text'] for label in ('材料','金币','资源'))
               for word in getattr(screen,'words',()))


def record_consumption(ledger,before,after,cost,journal):
    """只记录完整且匹配的实际差额；未知值不补成零或预测消耗。"""
    if not cost or any(type(before.get(key)) is not int or type(after.get(key)) is not int
                       or before[key]-after[key]!=value for key,value in cost.items()):
        journal.emit('craft_statistics_unavailable',message='消耗统计未确认，制作结果照常处理')
        return {}
    actual={key:before[key]-after[key] for key in cost}
    for key,value in actual.items():
        ledger.spent[key]+=value
    return actual
