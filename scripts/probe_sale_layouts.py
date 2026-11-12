"""原生批量整理产物布局取样；输入门禁位于SelectionOnlyAdb，永不确认出售。"""
from dataclasses import asdict
import json

from e7_assistant.batch_sale_vision import inspect_organized,origin


def preview_layouts(nav,items,journal):
    equipment=[i for i,item in enumerate(items) if item.equipment.slot not in {'ring','necklace'} and item.locked is False]
    jewelry=[i for i,item in enumerate(items) if item.equipment.slot in {'ring','necklace'} and item.locked is False]
    if not equipment or not jewelry:
        raise ValueError('本批缺少确认未锁的装备或饰品，未打开出售预览')
    reference=nav.read()
    if reference.page!='batch_enhancement':
        raise ValueError('布局取样必须从已核对的批量强化页开始')
    screen=nav.transition('organize_batch')
    results=[]

    def organized(current):
        for attempt in range(3):
            try:
                return current,inspect_organized(current,reference.source,len(items))
            except ValueError:
                if attempt==2:
                    raise
                nav.control.wait(.2)
                current=nav.read()

    def click(current,action,point):
        journal.emit('sale_layout_preview_intent',action=action,page=current.page,
                     x=point[0],y=point[1],image=current.source)
        nav.adb.tap(*point)
        nav.control.wait(.3)
        return nav.read()

    def cancel(current):
        word=current.find('取消',(400,490,650,570),.95)
        current=click(current,'cancel_sale',tuple(round(v) for v in word['center']))
        for _ in range(5):
            if current.page=='batch_organize':
                break
            if current.page not in {'sale_confirmation','unknown'}:
                break
            nav.control.wait(.2)
            current=nav.read()
        return current

    try:
        for name,targets in (('equipment',{equipment[0]}),('jewelry',{jewelry[0]}),
                             ('mixed',{equipment[0],jewelry[0]})):
            screen,state=organized(screen)
            for index in range(len(items)):
                target=index in targets
                if state.selected[index] is target:
                    continue
                dx,dy=origin(index)
                screen=click(screen,'toggle',(62+dx,185+dy))
                screen,fresh=organized(screen)
                expected=list(state.selected);expected[index]=target
                if fresh.selected!=tuple(expected):
                    raise ValueError('布局取样勾选未恰好改变一件，不重试输入')
                state=fresh
            if {i for i,value in enumerate(state.selected) if value}!=targets:
                raise ValueError('出售预览选择集合不一致')
            word=screen.find('出售',(210,60,370,130),.95)
            screen=click(screen,'open_sale',tuple(round(v) for v in word['center']))
            for _ in range(5):
                if screen.page=='sale_confirmation':
                    break
                if screen.page not in {'batch_organize','unknown'}:
                    break
                nav.control.wait(.2)
                screen=nav.read()
            if screen.page!='sale_confirmation':
                raise ValueError('出售预览未出现已知弹窗，未发送确认')
            screen.find('出售',(400,140,880,220),.95)
            record={'layout':name,'indices':sorted(targets),
                    'slots':[items[i].equipment.slot for i in sorted(targets)],
                    'screen':asdict(screen)}
            (nav.directory/f'sale-layout-{name}.json').write_text(
                json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
            results.append(record)
            screen=cancel(screen)
            if screen.page!='batch_organize':
                raise ValueError('出售预览取消后未回到整理页')
        return results
    finally:
        # 成功和异常都仅取消；门禁没有右侧确认按钮的输入许可。
        current=nav.read()
        if current.page=='sale_confirmation':
            current=cancel(current)
        if current.page=='batch_organize':
            nav.transition('cancel_batch_organize')
