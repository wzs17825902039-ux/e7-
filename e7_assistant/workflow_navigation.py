"""完整工作流共用的导航驱动；不包含制作、强化或处置确认。"""
from pathlib import Path

from .workflow_screen import inspect_screen


# (允许的起始页, 按钮文字或坐标, 文字区域, 允许的结果页)
TRANSITIONS = {
    'close_legendary_result': ({'legendary_craft_result'}, (1100,300), None, {'forge'}),
    'cancel_legendary_craft': ({'legendary_craft_confirmation'}, '取消', (350,490,560,600), {'forge'}),
    'cancel_sale_level_warning': ({'sale_level_warning'}, '取消', (320,490,525,570), {'batch_organize'}),
    'cancel_batch_sale': ({'sale_confirmation'}, '取消', (350,450,650,600), {'batch_organize','inventory_organize','forge'}),
    'cancel_craft': ({'craft_confirmation'}, '取消', (350,450,650,600), {'forge'}),
    'back_unknown': ({'back_navigation'}, (35,32), None, {'home','forge','inventory','inventory_items','back_navigation'}),
    'dismiss_enhancement_refund': ({'enhancement_refund'}, '点击关闭', (500,480,800,580), {'batch_enhancement'}),
    'dismiss_date': ({'date_change'}, '点击关闭', (500,440,800,530), {'home','attendance_reward','friendship_notice'}),
    'dismiss_attendance': ({'attendance_reward'}, '确认', (950,620,1220,710), {'home','friendship_notice'}),
    'dismiss_friendship': ({'friendship_notice'}, '点击关闭', (500,550,800,640), {'home'}),
    'menu': ({'home','forge'}, (1240,32), None, {'home_menu'}),
    'back_inventory': ({'inventory'}, (35,32), None, {'home','forge'}),
    'forge': ({'home_menu'}, '钢铁工坊', (1100,300,1275,470), {'forge'}),
    'inventory': ({'home','home_menu','forge'}, (1066,32), None, {'inventory','inventory_items'}),
    'inventory_from_batch': ({'batch_enhancement'}, (1066,32), None, {'inventory','inventory_items','forge','home'}),
    'equipment_inventory': ({'inventory_items'}, (52,190), None, {'inventory'}),
    'manage': ({'inventory'}, '管理', (1100,70,1270,140), {'inventory_manage'}),
    'close_manage': ({'inventory_manage'}, '管理', (1100,70,1270,140), {'inventory'}),
    'organize': ({'inventory_manage'}, '整理', None, {'inventory_organize'}),
    'batch_select': ({'inventory_manage'}, '批量强化', None, {'inventory_batch_selection','inventory_batch_selection_empty'}),
    'cancel_inventory': ({'inventory_organize','inventory_batch_selection','inventory_batch_selection_empty'}, '取消',
                         (1100,70,1270,140), {'inventory'}),
    'cancel_batch_organize': ({'batch_organize'}, '取消', (820,60,1000,130), {'batch_enhancement'}),
    'organize_batch': ({'batch_enhancement'}, '整理', (820,60,1000,130), {'batch_organize'}),
    'back_batch': ({'batch_enhancement'}, (35,32), None, {'inventory','inventory_batch_selection','inventory_batch_selection_empty'}),
    'close_craft_result': ({'craft_result'}, '确认', (350,600,620,700), {'forge'}),
    'cancel_full': ({'inventory_full'}, '取消', (350,350,650,650), {'craft_result','forge'}),
    'cancel_extract': ({'extract_confirmation'}, '取消', (350,450,650,600), {'inventory_organize'}),
}


class NavigationPageChanged(ValueError):
    """输入前已变页；携带新截图供上层重新规划，绝不重复已发送的点击。"""
    def __init__(self,action,screen):
        super().__init__(f'导航{action}的起始页面不符：{screen.page}')
        self.screen=screen


class WorkflowNavigator:
    def __init__(self, adb, directory, control, journal=None, screen_reader=inspect_screen):
        self.adb, self.directory, self.control = adb, Path(directory), control
        self.journal, self.screen_reader = journal, screen_reader
        self.counter = 0
        self.last_image = None
        if adb.control is None:
            adb.control = control

    def read(self,screen_reader=None):
        import time
        self.control.checkpoint()
        self.counter += 1
        path = self.directory / f'workflow-{self.counter:04d}.png'
        started=time.perf_counter()
        self.adb.screenshot(str(path))
        captured=time.perf_counter()
        screen = (screen_reader or self.screen_reader)(path)
        self.last_image = screen.source
        if (screen.width,screen.height) != (1280,720):
            raise ValueError('实际导航仅支持1280×720实例；不会按其他尺寸发送点击')
        if self.journal:
            self.journal.emit('workflow_screen', page=screen.page, image=screen.source,
                              capture_seconds=round(captured-started,4),
                              page_read_seconds=round(time.perf_counter()-captured,4))
        return screen

    def read_batch(self):
        if self.screen_reader is not inspect_screen:
            return self.read()
        from .workflow_screen import inspect_batch_controls
        return self.read(screen_reader=inspect_batch_controls)

    def read_forge(self):
        from .workflow_screen import inspect_forge_screen
        return self.read(screen_reader=inspect_forge_screen)

    def read_selection(self):
        from .workflow_screen import inspect_selection_screen
        return self.read(screen_reader=inspect_selection_screen)

    def read_navigation(self,pages):
        if self.screen_reader is not inspect_screen:
            return self.read()
        from .workflow_screen import inspect_navigation_screen
        return self.read(screen_reader=lambda path:inspect_navigation_screen(path,pages))

    def transition(self, action):
        allowed, button, region, destinations = TRANSITIONS[action]
        screen = self.read_navigation(allowed)
        if screen.page not in allowed:
            raise NavigationPageChanged(action,screen)
        if isinstance(button,str):
            word = screen.find(button,region)
            x,y = word['center']
            if action=='forge':
                # 实机菜单文字位于图标下方，文字区域本身不响应；点击对应图标中心。
                y-=38
        else:
            x,y = button
        self.control.checkpoint()
        if self.journal:
            self.journal.emit('navigation_intent', action=action, page=screen.page, x=round(x),y=round(y))
        self.adb.tap(round(x),round(y))
        # 只重读页面；超时绝不重复发送点击。
        # 日期变更会返回大厅并加载资源；只延长此处读屏等待，不重发关闭点击。
        attempts=45 if action=='dismiss_date' else 6
        for attempt in range(attempts):
            self.control.wait(.2 if attempt==0 else .4)
            observed = self.read_navigation(destinations)
            if action=='back_unknown' and observed.page=='back_navigation':
                from PIL import Image,ImageChops,ImageStat
                with Image.open(screen.source) as before,Image.open(observed.source) as after:
                    delta=ImageStat.Stat(ImageChops.difference(before.convert('RGB'),after.convert('RGB')))
                if max(delta.mean)<2:
                    continue  # 箭头仍在而页面没变，不把它当成又退了一层。
            if observed.page in destinations:
                return observed
            if observed.page=='interruption':
                raise ValueError(f'导航遇到意外弹窗：{observed.page}，未确认')
            routable={page for transition in TRANSITIONS.values() for page in transition[0]}
            if observed.page in routable and observed.page not in allowed:
                if self.journal:self.journal.emit('navigation_replanned',action=action,page=observed.page)
                return observed
        raise TimeoutError(f'导航{action}未达到预期页面，禁止重复点击')

    def navigate(self, target):
        if target not in {'forge','inventory','inventory_batch_selection'}:
            raise ValueError('导航目标必须为钢铁工坊、背包或批量选择')
        screen = self.read()
        # 启动时可能截到加载黑帧；只重读，不对未知画面猜测按钮。
        for _ in range(5):
            if screen.page != 'unknown':
                break
            self.control.wait(.4)
            screen = self.read()
        retried_edges=set()
        for _ in range(16):
            page = screen.page
            if page == target or target == 'inventory_batch_selection' and page == 'inventory_batch_selection_empty':
                return screen
            if page == 'enhancement_refund':
                action = 'dismiss_enhancement_refund'
            elif page=='back_navigation':
                action='back_unknown'
            elif page=='craft_confirmation':
                action='cancel_craft'
            elif page=='sale_confirmation':
                action='cancel_batch_sale'
            elif page=='sale_level_warning':
                action='cancel_sale_level_warning'
            elif page == 'legendary_craft_confirmation':
                action = 'cancel_legendary_craft'
            elif page == 'legendary_craft_result':
                action = 'close_legendary_result'
            elif page == 'date_change':
                action = 'dismiss_date'
            elif page == 'attendance_reward':
                action = 'dismiss_attendance'
            elif page == 'friendship_notice':
                action = 'dismiss_friendship'
            elif page == 'inventory_full':
                action = 'cancel_full'
            elif page == 'craft_result':
                action = 'close_craft_result'
            elif page == 'extract_confirmation':
                action = 'cancel_extract'
            elif page in {'inventory_organize','inventory_batch_selection','inventory_batch_selection_empty'}:
                action = 'cancel_inventory'
            elif page == 'batch_organize':
                action = 'cancel_batch_organize'
            elif page == 'batch_enhancement':
                action = 'inventory_from_batch'
            elif page == 'inventory_manage':
                action = 'batch_select' if target == 'inventory_batch_selection' else 'close_manage'
            elif page == 'inventory':
                action = 'manage' if target == 'inventory_batch_selection' else 'back_inventory'
            elif page == 'inventory_items':
                action = 'equipment_inventory'
            elif page == 'home_menu':
                action = 'forge' if target == 'forge' else 'inventory'
            elif page in {'home','forge'}:
                action = 'menu' if target == 'forge' else 'inventory'
            else:
                raise ValueError(f'未知或未处理页面{page}，未发送导航点击')
            try:
                screen = self.transition(action)
            except NavigationPageChanged as exc:
                # 尚未发送输入；处理实际出现的页面，不沿用上次观察的按钮。
                screen=exc.screen
            except TimeoutError:
                # 导航按钮不消耗资源；只有重拍确认仍在原页面时，才允许一次重试。
                fresh=self.read()
                key=(page,action)
                routable={p for transition in TRANSITIONS.values() for p in transition[0]}
                if fresh.page!=page and fresh.page in routable:
                    if self.journal:self.journal.emit('navigation_replanned',action=action,page=fresh.page)
                    screen=fresh
                    continue
                if action!='back_unknown' and fresh.page==page and key not in retried_edges:
                    retried_edges.add(key)
                    if self.journal:self.journal.emit('navigation_retry',action=action,page=page,attempt=1)
                    screen=fresh
                    continue
                raise
        raise RuntimeError('导航步骤达到上限，已停止')
