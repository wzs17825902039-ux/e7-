from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from e7_assistant.tasks import TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator
from e7_assistant.workflow_screen import Screen, classify


def word(text,x=500,y=300,confidence=.99):
    return {'text':text,'confidence':confidence,'center':(x,y),'box':(x-10,y-10,x+10,y+10)}


def screen(page):
    labels = {
        'inventory':[word('背包',100,32),word('管理',1189,107)],
        'home_menu':[word('钢铁工坊',1204,408),word('宠物小屋'),word('好友')],
        'forge':[word('钢铁工坊'),word('制作装备〖双足飞龙〗')],
        'inventory_manage':[word('管理',1189,107),word('整理',1172,169),word('批量强化',1172,227),word('背包')],
        'inventory_batch_selection':[word('背包'),word('取消',1189,107),word('清空'),word('批量强化(16)')],
        'date_change':[word('变更日期',641,216),word('日期变更,将前往大厅。',640,358),word('点击关闭',642,480)],
        'attendance_reward':[word('联动签到奖励!'),word('奖励已用邮件寄出'),word('确认',1073,664)],
        'friendship_notice':[word('辅助英雄友情点数抵达'),word('点击关闭',640,586)],
        'batch_enhancement':[word('整理',925,96)],
        'batch_organize':[word('取消',925,96)],
    }.get(page,[])
    return Screen('fake.png',page,1280,720,tuple(labels))


class FakeAdb:
    control = None
    def __init__(self,page='inventory',transition=True):
        self.state = screen(page)
        self.taps=[]
        self.transition=transition
    def screenshot(self,path):
        pass
    def tap(self,x,y):
        self.control.before_input()
        self.taps.append((x,y))
        if self.transition:
            next_page = {'inventory': 'home' if x==35 else 'inventory_manage',
                         'home':'home_menu','date_change':'home','attendance_reward':'home','friendship_notice':'home',
                         'home_menu':'forge','inventory_manage':'inventory_batch_selection',
                         'batch_enhancement':'batch_organize','batch_organize':'batch_enhancement'}[self.state.page]
            self.state=screen(next_page)


class NavigationTests(unittest.TestCase):
    def test_delayed_navigation_detected_after_timeout_replans_without_original_reclick(self):
        from unittest.mock import Mock
        nav=self.navigator(FakeAdb())
        nav.read=Mock(side_effect=[screen('inventory'),screen('home')])
        nav.transition=Mock(side_effect=[TimeoutError('画面延迟'),screen('home_menu'),screen('forge')])
        self.assertEqual(nav.navigate('forge').page,'forge')
        self.assertEqual([call.args[0] for call in nav.transition.call_args_list],['back_inventory','menu','forge'])

    def test_known_notice_during_navigation_returns_for_replanning(self):
        from unittest.mock import Mock
        adb=FakeAdb('inventory',transition=False)
        nav=self.navigator(adb)
        nav.read_navigation=Mock(side_effect=[screen('inventory'),screen('date_change')])
        self.assertEqual(nav.transition('manage').page,'date_change')
        self.assertEqual(adb.taps,[(1189,107)])

    def test_recognized_back_arrow_does_not_repeat_when_page_does_not_change(self):
        from unittest.mock import Mock
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unchanged.png';Image.new('RGB',(1280,720)).save(path)
            state=replace(screen('back_navigation'),source=str(path))
            adb=FakeAdb('back_navigation',transition=False)
            nav=self.navigator(adb);nav.read_navigation=Mock(return_value=state)
            with self.assertRaises(TimeoutError):nav.transition('back_unknown')
            self.assertEqual(adb.taps,[(35,32)])
            self.assertEqual(nav.read_navigation.call_count,7)

    def test_all_supported_start_pages_can_route_to_each_task_destination(self):
        from unittest.mock import Mock
        from e7_assistant.workflow_navigation import TRANSITIONS
        destinations={'cancel_legendary_craft':'forge','close_legendary_result':'forge',
            'cancel_sale_level_warning':'batch_organize','cancel_batch_sale':'batch_organize',
            'cancel_craft':'forge','back_unknown':'home','dismiss_enhancement_refund':'batch_enhancement',
            'dismiss_date':'home','dismiss_attendance':'home','dismiss_friendship':'home',
            'menu':'home_menu','back_inventory':'home','forge':'forge','inventory':'inventory',
            'inventory_from_batch':'inventory','equipment_inventory':'inventory','manage':'inventory_manage',
            'close_manage':'inventory','organize':'inventory_organize','batch_select':'inventory_batch_selection',
            'cancel_inventory':'inventory','cancel_batch_organize':'batch_enhancement','organize_batch':'batch_organize',
            'back_batch':'inventory','close_craft_result':'forge','cancel_full':'forge','cancel_extract':'inventory_organize'}
        starts={page for transition in TRANSITIONS.values() for page in transition[0]}
        for start in starts:
            for target in ('forge','inventory','inventory_batch_selection'):
                with self.subTest(start=start,target=target):
                    nav=self.navigator(FakeAdb(start))
                    nav.transition=Mock(side_effect=lambda action:screen(destinations[action]))
                    expected='inventory_batch_selection_empty' if start=='inventory_batch_selection_empty' and target=='inventory_batch_selection' else target
                    self.assertEqual(nav.navigate(target).page,expected)
                    self.assertLessEqual(nav.transition.call_count,12)

    def test_batch_exit_via_home_replans_inventory_without_repeating_exit(self):
        adb=FakeAdb('batch_enhancement')
        def tap(x,y):
            adb.taps.append((x,y))
            if adb.state.page=='batch_enhancement':
                self.assertEqual((x,y),(1066,32))
                adb.state=screen('home')
            elif adb.state.page=='home':
                self.assertEqual((x,y),(1066,32))
                adb.state=screen('inventory')
            else:self.fail('不应继续导航')
        adb.tap=tap
        self.assertEqual(self.navigator(adb).navigate('inventory').page,'inventory')
        self.assertEqual(len(adb.taps),2)

    def test_real_consumables_inventory_is_not_an_unknown_page(self):
        from e7_assistant.workflow_screen import inspect_screen
        source=Path(__file__).resolve().parents[1]/'runs/workflow-e1fd4117b5ca/workflow-0244.png'
        self.assertEqual(inspect_screen(source).page,'inventory_items')

    def test_consumables_inventory_switches_to_equipment_before_manage(self):
        adb=FakeAdb('inventory_items')
        original=adb.tap
        def tap(x,y):
            if adb.state.page=='inventory_items':
                adb.taps.append((x,y))
                self.assertEqual((x,y),(52,190))
                adb.state=screen('inventory')
            else:
                original(x,y)
        adb.tap=tap
        self.assertEqual(self.navigator(adb).navigate('inventory_batch_selection').page,'inventory_batch_selection')
        self.assertEqual(adb.taps,[(52,190),(1189,107),(1172,227)])

    def test_use_button_without_inventory_title_is_not_an_inventory_page(self):
        self.assertEqual(classify([word('使用',1150,675)]),'unknown')
        self.assertEqual(classify([word('背包',100,32),word('使用',500,300)]),'unknown')

    def navigator(self,adb,control=None):
        control=control or TaskControl()
        control.wait=lambda seconds:control.checkpoint()
        return WorkflowNavigator(adb,Path(tempfile.gettempdir()),control,
                                 screen_reader=lambda path:adb.state)

    def test_inventory_to_forge_checks_each_page(self):
        adb=FakeAdb()
        result=self.navigator(adb).navigate('forge')
        self.assertEqual(result.page,'forge')
        self.assertEqual(adb.taps,[(35,32),(1240,32),(1204,370)])

    def test_inventory_can_return_directly_to_forge(self):
        adb=FakeAdb()
        def tap(x,y):
            adb.control.before_input()
            adb.taps.append((x,y))
            self.assertEqual((x,y),(35,32))
            adb.state=screen('forge')
        adb.tap=tap
        result=self.navigator(adb).navigate('forge')
        self.assertEqual(result.page,'forge')
        self.assertEqual(adb.taps,[(35,32)])

    def test_inventory_to_batch_selection_does_not_select_or_enhance_gear(self):
        adb=FakeAdb()
        result=self.navigator(adb).navigate('inventory_batch_selection')
        self.assertEqual(result.page,'inventory_batch_selection')
        self.assertEqual(adb.taps,[(1189,107),(1172,227)])

    def test_empty_selection_layout_is_valid_navigation_destination(self):
        adb=FakeAdb()
        original=adb.tap
        def tap(x,y):
            original(x,y)
            if adb.state.page=='inventory_batch_selection':
                adb.state=screen('inventory_batch_selection_empty')
        adb.tap=tap
        result=self.navigator(adb).navigate('inventory_batch_selection')
        self.assertEqual(result.page,'inventory_batch_selection_empty')
        self.assertEqual(len(adb.taps),2)

    def test_unexpected_page_and_wrong_resolution_send_no_input(self):
        for state in (screen('unknown'),replace(screen('inventory'),width=1661,height=933)):
            adb=FakeAdb();adb.state=state
            with self.subTest(state=state),self.assertRaises(ValueError):
                self.navigator(adb).navigate('forge')
            self.assertEqual(adb.taps,[])

    def test_navigation_timeout_retries_only_once_after_confirming_same_page(self):
        adb=FakeAdb(transition=False)
        with self.assertRaises(TimeoutError):
            self.navigator(adb).navigate('forge')
        self.assertEqual(len(adb.taps),2)

    def test_back_batch_accepts_empty_inventory_selection(self):
        adb=FakeAdb('batch_enhancement')
        def tap(x,y):
            adb.taps.append((x,y));adb.state=screen('inventory_batch_selection_empty')
        adb.tap=tap
        self.assertEqual(self.navigator(adb).transition('back_batch').page,'inventory_batch_selection_empty')
        self.assertEqual(adb.taps,[(35,32)])

    def test_batch_result_opens_inventory_with_top_inventory_button(self):
        adb=FakeAdb('batch_enhancement')
        def tap(x,y):
            adb.taps.append((x,y))
            if (x,y)==(1066,32):
                adb.state=screen('inventory')
        adb.tap=tap
        self.assertEqual(self.navigator(adb).navigate('inventory').page,'inventory')
        self.assertEqual(adb.taps,[(1066,32)])

    def test_batch_inventory_route_can_return_via_forge(self):
        adb=FakeAdb('batch_enhancement')
        def tap(x,y):
            adb.taps.append((x,y))
            self.assertEqual((x,y),(1066,32))
            adb.state=screen('forge' if len(adb.taps)==1 else 'inventory')
        adb.tap=tap
        self.assertEqual(self.navigator(adb).navigate('inventory').page,'inventory')
        self.assertEqual(adb.taps,[(1066,32),(1066,32)])

    def test_initial_loading_frame_is_reread_without_input(self):
        adb=FakeAdb('unknown')
        nav=self.navigator(adb)
        reads=0
        def reader(path):
            nonlocal reads
            reads+=1
            self.assertEqual(adb.taps,[])
            return screen('unknown' if reads<3 else 'forge')
        nav.screen_reader=reader
        self.assertEqual(nav.navigate('forge').page,'forge')
        self.assertEqual(reads,3)

    def test_persistent_unknown_has_bounded_reads_and_no_input(self):
        adb=FakeAdb('unknown')
        nav=self.navigator(adb)
        with self.assertRaises(ValueError):
            nav.navigate('forge')
        self.assertEqual(nav.counter,6)
        self.assertEqual(adb.taps,[])

    def test_ambiguous_text_button_is_rejected(self):
        adb=FakeAdb('home_menu')
        adb.state=replace(adb.state,words=adb.state.words+(word('钢铁工坊',1210,410),))
        with self.assertRaises(ValueError):
            self.navigator(adb).navigate('forge')
        self.assertEqual(adb.taps,[])

    def test_modal_priority_and_numeric_batch_selection(self):
        words=[word('背包'),word('管理'),word('装备背包已满，请先整理'),word('取消')]
        self.assertEqual(classify(words),'inventory_full')
        self.assertEqual(classify(screen('inventory_batch_selection').words),'inventory_batch_selection')

    def test_low_confidence_title_is_not_a_known_page(self):
        self.assertEqual(classify([word('钢铁工坊',confidence=.2),word('制作装备〖双足飞龙〗')]),'unknown')

    def test_date_change_modal_overrides_background_inventory(self):
        words=screen('date_change').words+screen('inventory').words
        self.assertEqual(classify(words),'date_change')
        self.assertEqual(classify([word('变更日期')]),'unknown')

    def test_navigation_can_dismiss_date_change_before_entering_forge(self):
        adb=FakeAdb('date_change')
        result=self.navigator(adb).navigate('forge')
        self.assertEqual(result.page,'forge')
        self.assertEqual(adb.taps,[(642,480),(1240,32),(1204,370)])

    def test_date_change_waits_for_long_loading_without_repeating_close(self):
        from unittest.mock import Mock
        adb=FakeAdb('date_change')
        nav=self.navigator(adb)
        nav.read_navigation=Mock(side_effect=[screen('date_change')]+[screen('unknown')]*10+[screen('home')])
        result=nav.transition('dismiss_date')
        self.assertEqual(result.page,'home')
        self.assertEqual(adb.taps,[(642,480)])

    def test_date_change_loading_remains_bounded_and_never_reclicks(self):
        from unittest.mock import Mock
        adb=FakeAdb('date_change')
        nav=self.navigator(adb)
        nav.read_navigation=Mock(side_effect=[screen('date_change')]+[screen('unknown')]*45)
        with self.assertRaises(TimeoutError):nav.transition('dismiss_date')
        self.assertEqual(adb.taps,[(642,480)])
        self.assertEqual(nav.read_navigation.call_count,46)

    def test_attendance_requires_mailed_or_verified_reward_counter(self):
        self.assertEqual(classify(screen('attendance_reward').words+screen('inventory').words),'attendance_reward')
        self.assertEqual(classify([word('联动签到奖励!'),word('签到奖励一天可获得一次。'),
                                  word('获得的奖励:14/28')]),'attendance_reward')
        self.assertEqual(classify([word('联动签到奖励!'),word('确认')]),'unknown')

    def test_popup_appearing_before_input_replans_without_clicking_background(self):
        adb=FakeAdb('home')
        nav=self.navigator(adb)
        read=nav.read
        count=0
        def changed():
            nonlocal count
            count+=1
            if count==2:
                adb.state=screen('attendance_reward')
            return read()
        nav.read=changed
        result=nav.navigate('forge')
        self.assertEqual(result.page,'forge')
        self.assertEqual(adb.taps,[(1073,664),(1240,32),(1204,370)])

    def test_friendship_notice_closes_without_clicking_background_menu(self):
        self.assertEqual(classify(screen('friendship_notice').words+screen('home_menu').words),'friendship_notice')
        adb=FakeAdb('friendship_notice')
        result=self.navigator(adb).navigate('forge')
        self.assertEqual(result.page,'forge')
        self.assertEqual(adb.taps,[(640,586),(1240,32),(1204,370)])

    def test_batch_organize_navigation_and_cancel_do_not_confirm_resources(self):
        adb=FakeAdb('batch_enhancement')
        nav=self.navigator(adb)
        self.assertEqual(nav.transition('organize_batch').page,'batch_organize')
        self.assertEqual(nav.transition('cancel_batch_organize').page,'batch_enhancement')
        self.assertEqual(adb.taps,[(925,96),(925,96)])
