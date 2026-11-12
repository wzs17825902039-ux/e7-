from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import tempfile
import unittest

from e7_assistant.legendary_crafting import LegendaryForgeLoop,run_legendary,verify_set_selection,preview_legendary,verify_legendary_result,settle_legendary,read_charges,wait_legendary_result
from e7_assistant.workflow import WorkflowOptions
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.tasks import Journal,Ledger,Limits,TaskControl
from e7_assistant.disposal_guard import CraftSessionGuard
from e7_assistant.forge_loop import ForgePreview
from e7_assistant.legendary_crafting import retry_observation,observe_forge,observe_settlement

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'docs/assets/legendary-crafting/wyvern-speed-helmet-confirmation.png'


class LegendaryCraftingTests(unittest.TestCase):
    def test_adaptive_crop_keeps_all_digits_for_one_two_and_three_digit_samples(self):
        from e7_assistant.local_ocr import read_local_regions
        cases=[('forge-charges-8.png',8),('forge-charges-77.png',77),
               ('forge-charges-266.png',266),('forge-charges-271.png',271),
               ('after-single-craft-170.png',170)]
        for name,expected in cases:
            with self.subTest(name=name):
                calls=[]
                def reader(path,regions,*args,**kwargs):
                    if args or kwargs:return read_local_regions(path,regions,*args,**kwargs)
                    calls.append(regions)
                    if len(calls)<3:
                        return ({key:'' for key in regions},{key:{'confidence':0} for key in regions})
                    return read_local_regions(path,regions)
                with patch('e7_assistant.local_ocr.read_local_regions',side_effect=reader):
                    self.assertEqual(read_charges(ROOT/'docs/assets/legendary-crafting'/name),expected)
                self.assertEqual(len(calls),3)

    def test_real_single_digit_8_uses_complete_glyph_width_and_two_confident_crops(self):
        path=ROOT/'docs/assets/legendary-crafting/forge-charges-8.png'
        self.assertEqual(read_charges(path),8)

    def test_adaptive_counter_never_overrides_confident_full_width_conflict(self):
        with patch('e7_assistant.local_ocr.read_local_regions',side_effect=[
            ({'counter':'18','counter_tight':''},{'counter':{'confidence':.99},'counter_tight':{'confidence':0}}),
            ({'counter_digits':'8'},{'counter_digits':{'confidence':.99}})]) as reader:
            with self.assertRaisesRegex(ValueError,'冲突'):read_charges('not-opened.png')
            self.assertEqual(reader.call_count,2)

    def test_archived_result_and_two_resource_frames_recover_without_current_balance(self):
        import json
        for conflicting_commit in (False,True):
            with self.subTest(conflicting_commit=conflicting_commit),tempfile.TemporaryDirectory() as temporary:
                original=Journal(Path(temporary)/'original')
                journal=Journal(Path(temporary)/'recovery')
                names=['forge-77-result.png','forge-charges-77.png','forge-charges-77-second.png']
                for name in names:
                    (original.directory/name).write_bytes((ROOT/'docs/assets/legendary-crafting'/name).read_bytes())
                before={'source_index':0,'slot':'helmet','gear_set':'speed','charges':78,
                        'resources':{'craft_material':29380},'cost':{'craft_material':40}}
                guard=CraftSessionGuard(Path(temporary)/'craft-pending','archive-test')
                operation=guard.begin('craft',{'mode':'legendary',**before},{},original.directory)
                original.emit('legendary_commit_intent',operation_id=operation,preview=before)
                for name in names:
                    original.emit('workflow_screen',page='legendary_craft_result' if name==names[0] else 'forge',
                                  image=str(original.directory/name))
                if conflicting_commit:original.emit('legendary_commit_intent',operation_id='unrelated',preview={})
                nav=SimpleNamespace(adb=Mock(serial='archive-test'),read=Mock(side_effect=AssertionError('不得读取当前余额')),
                                    control=Mock(),journal=journal)
                ledger=Ledger(Limits(craft_material=1000))
                if conflicting_commit:
                    with self.assertRaisesRegex(ValueError,'其他制作提交'):
                        settle_legendary(nav,WorkflowOptions(),ledger,journal)
                    self.assertIsNotNone(guard.read())
                else:
                    result=settle_legendary(nav,WorkflowOptions(),ledger,journal)
                    self.assertEqual((result['recovered'],result['remaining_charges']),(1,77))
                    self.assertEqual(ledger.spent['craft_material'],40)
                    self.assertIsNone(guard.read())
                nav.read.assert_not_called()
                nav.adb.tap.assert_not_called()

    def test_recovery_can_restore_missing_slot_without_crafting_or_changing_count(self):
        empty=inspect_screen(ROOT/'docs/assets/legendary-crafting/forge-no-slot-selected.png')
        selected=inspect_screen(ROOT/'docs/assets/legendary-crafting/forge-charges-77.png')
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'run')
            nav=SimpleNamespace(adb=Mock(serial='restore-slot'),control=Mock(),
                                navigate=Mock(return_value=empty),read=Mock(return_value=selected))
            loop=LegendaryForgeLoop(nav,WorkflowOptions(track_craft_consumption=True),Ledger(Limits()),nav.control,journal)
            preview=loop.configure()
            self.assertEqual(preview.resources,{'craft_material':29340})
            nav.adb.tap.assert_called_once_with(354,307)

    def test_real_two_digit_77_counter_recovers_without_border(self):
        self.assertEqual(read_charges(ROOT/'docs/assets/legendary-crafting/forge-charges-77.png'),77)

    def test_startup_pending_is_automatically_reconciled_before_new_work(self):
        for recover in (True,False):
            with self.subTest(recover=recover),tempfile.TemporaryDirectory() as temporary:
                journal=Journal(Path(temporary)/'run')
                guard=CraftSessionGuard(Path(temporary)/'craft-pending','test-auto-start')
                operation=guard.begin('craft',{'mode':'legendary'},{},journal.directory)
                nav=SimpleNamespace(adb=Mock(serial='test-auto-start'),control=Mock(),last_image='forge.png')
                ledger=Ledger(Limits(craft_material=1000))
                def settle(*args):
                    if not recover:raise ValueError('材料差额仍不确定')
                    guard.settle(operation)
                    ledger.spent['craft_material']+=40
                    return {'recovered':1}
                with patch('e7_assistant.legendary_crafting.settle_legendary',side_effect=settle) as recovery,\
                     patch('e7_assistant.legendary_crafting.preview_legendary',return_value={
                         'state':'charges_exhausted','charges':0,'last_image':'forge.png'}) as preview:
                    result=run_legendary(nav,WorkflowOptions(),ledger,journal)
                recovery.assert_called_once()
                self.assertEqual(result['state'],'complete' if recover else 'failed')
                self.assertEqual(result['outcome_unknown'],not recover)
                if recover:
                    preview.assert_called_once()
                    self.assertEqual(result['recovered'],1)
                    self.assertEqual(result['spent']['craft_material'],40)
                    self.assertIsNone(guard.read())
                else:
                    preview.assert_not_called()
                    self.assertIsNotNone(guard.read())
                nav.adb.tap.assert_not_called()

    def test_post_commit_timeout_automatically_reconciles_without_second_click(self):
        for recover in (True,False):
            with self.subTest(recover=recover),tempfile.TemporaryDirectory() as temporary:
                journal=Journal(Path(temporary)/'run')
                guard=CraftSessionGuard(Path(temporary)/'craft-pending','test-auto-post')
                screen=SimpleNamespace(source='modal.png',find=Mock(return_value={'center':(816,550)}))
                nav=SimpleNamespace(adb=Mock(serial='test-auto-post'),control=Mock(),read=Mock(return_value=screen),last_image='result.png')
                ledger=Ledger(Limits(craft_material=1000))
                preview={'state':'preview_ready','last_image':'preview.png','charges':78,
                         'resources':{'craft_material':29380},'cost':{'craft_material':40}}
                loop=Mock();loop.wait_for.side_effect=TimeoutError('结果动画超时')
                def settle(*args):
                    if not recover:raise ValueError('结果仍不确定')
                    ledger.settle(preview['resources'],{'craft_material':29340},preview['cost'])
                    guard.settle(guard.read()['operation_id'])
                    return {'recovered':1,'actual':{'craft_material':40},'remaining_charges':77,'last_image':'final.png'}
                with patch('e7_assistant.legendary_crafting.preview_legendary',return_value=preview),\
                     patch('e7_assistant.legendary_crafting.observe_modal',return_value=(screen,preview['cost'])),\
                     patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop),\
                     patch('e7_assistant.legendary_crafting.settle_legendary',side_effect=settle) as recovery:
                    result=run_legendary(nav,WorkflowOptions(legendary_count=1),ledger,journal)
                recovery.assert_called_once()
                self.assertEqual(result['state'],'complete' if recover else 'failed')
                self.assertEqual(result['completed'],1 if recover else 0)
                self.assertEqual(result['outcome_unknown'],not recover)
                self.assertEqual(nav.adb.tap.call_count,1)
                self.assertEqual(result['spent']['craft_material'],40 if recover else 0)

    def test_real_stopped_screens_settle_same_260_charges_without_input(self):
        result=inspect_screen(ROOT/'docs/assets/legendary-crafting/net-count-260-result.png')
        verify_legendary_result(result,'helmet','speed')
        screen=inspect_screen(ROOT/'docs/assets/legendary-crafting/net-count-260-after.png')
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'run')
            second=Path(temporary)/'second.png'
            second.write_bytes(Path(screen.source).read_bytes())
            nav=SimpleNamespace(control=Mock(),read=Mock(return_value=replace(screen,source=str(second))),
                                adb=Mock(serial='net-count'),journal=journal)
            loop=LegendaryForgeLoop(nav,WorkflowOptions(track_craft_consumption=True),Ledger(Limits()),nav.control,journal)
            initial=loop.preview(screen)
            final,charges=observe_settlement(loop,{'charges':260,'resources':{'craft_material':36940},
                    'cost':{'craft_material':40}},initial,result_verified=True)
            self.assertEqual((charges,final.resources),(260,{'craft_material':36900}))
            nav.read.assert_called_once()
            nav.adb.tap.assert_not_called()

    def test_same_charge_settlement_needs_result_and_two_exact_resource_frames(self):
        before={'charges':260,'resources':{'craft_material':36940},'cost':{'craft_material':40}}
        initial=ForgePreview({'craft_material':36900},{},'helmet',1,0,'first.png')
        for result_verified in (True,False):
            nav=SimpleNamespace(control=Mock(),read=Mock(),adb=Mock(),journal=Mock())
            loop=SimpleNamespace(navigator=nav,preview=Mock(return_value=replace(initial,image='second.png')))
            with patch('e7_assistant.legendary_crafting.read_charges',return_value=260):
                if result_verified:
                    final,count=observe_settlement(loop,before,initial,result_verified=True)
                    self.assertEqual((final.resources,count),({'craft_material':36900},260))
                    nav.read.assert_called_once()
                else:
                    with self.assertRaises(ValueError):observe_settlement(loop,before,initial,result_verified=False)
            nav.adb.tap.assert_not_called()

    def test_settlement_retries_stale_counts_but_rejects_wrong_material_delta(self):
        before={'charges':260,'resources':{'craft_material':36940},'cost':{'craft_material':40}}
        for material in (36900,36899):
            final=ForgePreview({'craft_material':material},{},'helmet',1,0,'first.png')
            nav=SimpleNamespace(control=Mock(),read=Mock(),adb=Mock(),journal=Mock())
            loop=SimpleNamespace(navigator=nav,preview=Mock(return_value=replace(final,image='second.png')))
            with patch('e7_assistant.legendary_crafting.read_charges',side_effect=[260,259,259,259]):
                if material==36900:self.assertEqual(observe_settlement(loop,before,final,result_verified=True)[1],259)
                else:
                    with self.assertRaises(ValueError):observe_settlement(loop,before,final,result_verified=True)
            nav.adb.tap.assert_not_called()
    def test_counter_266_rejection_recovers_with_independent_crops(self):
        self.assertEqual(read_charges(ROOT/'docs/assets/legendary-crafting/forge-charges-266.png'),266)

    def test_confident_counter_conflict_is_never_overridden_by_fallback(self):
        with patch('e7_assistant.local_ocr.read_local_regions',return_value=(
            {'counter':'266','counter_tight':'268'},
            {'counter':{'confidence':.99},'counter_tight':{'confidence':.99}})) as reader:
            with self.assertRaisesRegex(ValueError,'冲突'):read_charges('fake.png')
            reader.assert_called_once()

    def test_cancellation_during_retry_does_not_send_input(self):
        from e7_assistant.tasks import Cancelled
        nav=SimpleNamespace(control=Mock(),adb=Mock(),read=Mock(),journal=Mock())
        nav.control.checkpoint.side_effect=Cancelled('停止')
        with self.assertRaises(Cancelled):retry_observation(nav,'initial',Mock(),'次数')
        nav.read.assert_not_called()
        nav.adb.tap.assert_not_called()

    def test_observation_retries_are_bounded_read_only_and_can_recover(self):
        for recover in (True,False):
            nav=SimpleNamespace(control=Mock(),read=Mock(return_value='fresh'),adb=Mock(),journal=Mock())
            observe=Mock(side_effect=[ValueError('暂时拒识'),266] if recover else ValueError('拒识'))
            if recover:self.assertEqual(retry_observation(nav,'initial',observe,'次数'),266)
            else:
                with self.assertRaisesRegex(ValueError,'连续4次'):
                    retry_observation(nav,'initial',observe,'次数')
            self.assertEqual(nav.read.call_count,1 if recover else 3)
            nav.adb.tap.assert_not_called()

    def test_forge_retry_refreshes_resources_and_counter_together(self):
        old=ForgePreview({'craft_material':1000},{},'helmet',1,0,'old.png')
        fresh=replace(old,resources={'craft_material':960},image='fresh.png')
        nav=SimpleNamespace(control=Mock(),read=Mock(),adb=Mock(),journal=Mock())
        loop=SimpleNamespace(navigator=nav,preview=Mock(return_value=fresh))
        with patch('e7_assistant.legendary_crafting.read_charges',side_effect=[ValueError('拒识'),266]):
            self.assertEqual(observe_forge(loop,old),(fresh,266))
        nav.read.assert_called_once()
        nav.adb.tap.assert_not_called()

    def test_blank_count_continues_until_zero_charges_with_two_settlements(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'run')
            screen=SimpleNamespace(source='confirmation.png',find=Mock(return_value={'center':(816,550)}))
            nav=SimpleNamespace(adb=Mock(serial='test-unlimited'),control=Mock(),read=Mock(return_value=screen),last_image='final.png')
            previews=[{'state':'preview_ready','last_image':'preview.png','charges':2-i,
                       'resources':{'craft_material':1000-i*40},'cost':{'craft_material':40}}
                      for i in range(2)]+[{'state':'charges_exhausted','charges':0,'last_image':'final.png'}]
            loop=Mock()
            finals=[(ForgePreview({'craft_material':960-i*40},{},'helmet',1,0,'final.png'),1-i) for i in range(2)]
            with patch('e7_assistant.legendary_crafting.preview_legendary',side_effect=previews),\
                 patch('e7_assistant.legendary_crafting.observe_modal',return_value=(screen,{'craft_material':40})),\
                 patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop),\
                 patch('e7_assistant.legendary_crafting.wait_legendary_result'),\
                 patch('e7_assistant.legendary_crafting.observe_settlement',side_effect=finals):
                result=run_legendary(nav,WorkflowOptions(),Ledger(Limits(craft_material=1000)),journal)
            self.assertEqual((result['state'],result['completed'],result['remaining_charges']),('complete',2,0),result)
            self.assertEqual(result['spent']['craft_material'],80)
            self.assertEqual(nav.adb.tap.call_count,2)
            self.assertFalse(result['outcome_unknown'])

    def test_unselected_set_still_clicks_and_requires_fresh_selected_border(self):
        from PIL import Image,ImageDraw
        from e7_assistant.forge_loop import ForgePreview
        stable=inspect_screen(FIXTURE)
        word=stable.find('速度套装',(560,400,1100,480))
        x,y=map(round,word['center'])
        for changed_page in (False,True):
            with self.subTest(changed_page=changed_page),tempfile.TemporaryDirectory() as temporary:
                journal=Journal(Path(temporary)/'run')
                path=Path(temporary)/'unselected.png'
                with Image.open(FIXTURE) as image:
                    ImageDraw.Draw(image).rectangle((x-60,y-120,x+60,y-106),fill=(20,30,40))
                    image.save(path)
                initial=replace(stable,source=str(path))
                nav=SimpleNamespace(adb=Mock(serial='test-speed-selection'),control=Mock(),
                                    read=Mock(return_value=replace(stable,page='unknown') if changed_page else stable),
                                    last_image=str(FIXTURE))
                loop=Mock()
                loop.configure.return_value=ForgePreview({'craft_material':166573},{},'helmet',1,0,str(FIXTURE))
                loop.wait_for.return_value=initial
                with patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop),\
                     patch('e7_assistant.legendary_crafting.read_charges',return_value=171),\
                     patch('e7_assistant.legendary_crafting.number',return_value='166573/40'):
                    if changed_page:
                        with self.assertRaises(ValueError):
                            preview_legendary(nav,WorkflowOptions(),Ledger(Limits()),'speed',journal)
                    else:
                        result=preview_legendary(nav,WorkflowOptions(),Ledger(Limits()),'speed',journal)
                        self.assertEqual(result['state'],'preview_ready')
                self.assertEqual(nav.adb.tap.call_count,2)
                self.assertEqual(nav.read.call_count,4 if changed_page else 1)

    def test_counter_reads_271_without_including_upper_badge_edge(self):
        screen=SimpleNamespace(source=str(ROOT/'docs/assets/legendary-crafting/forge-charges-271.png'))
        self.assertEqual(read_charges(screen),271)
        self.assertEqual(read_charges(screen.source),271)

    def test_legendary_cost_comes_from_modal_not_normal_ten_craft_preview(self):
        from e7_assistant.forge_loop import ForgePreview
        screen=inspect_screen(FIXTURE)
        for gold in (False,True):
            with self.subTest(gold=gold),tempfile.TemporaryDirectory() as temporary:
                journal=Journal(Path(temporary)/'run')
                nav=SimpleNamespace(adb=Mock(serial='test-preview'),control=Mock(),
                                    read=Mock(return_value=screen),last_image=str(FIXTURE))
                resources={'craft_material':166573,**({'gold':1000000} if gold else {})}
                loop=Mock()
                loop.configure.return_value=ForgePreview(resources,{},'helmet',1,0,str(FIXTURE))
                loop.wait_for.return_value=screen
                with patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop),\
                     patch('e7_assistant.legendary_crafting.read_charges',return_value=171),\
                     patch('e7_assistant.legendary_crafting.number',side_effect=lambda screen,key,*args:
                           '166573/40' if key=='legendary_material' else '21000'):
                    result=preview_legendary(nav,WorkflowOptions(slot='helmet',craft_count=10,track_craft_consumption=True,
                                             track_craft_gold=gold),Ledger(Limits()),'speed',journal)
                self.assertEqual(result['cost'],{'craft_material':40,**({'gold':21000} if gold else {})})
                self.assertEqual(result['state'],'preview_ready')
                self.assertEqual(nav.adb.tap.call_count,1)  # 已选目标套装，只点击中央入口。
                nav.read.assert_not_called()  # 次数复用配置截图，选中边框复用弹窗截图。

    def test_selected_source_and_slot_are_reused_with_normal_count_ten(self):
        from PIL import Image,ImageDraw
        for gold in (False,True):
            with self.subTest(gold=gold),tempfile.TemporaryDirectory() as temporary:
                journal=Journal(Path(temporary)/'run')
                path=Path(temporary)/'forge.png'
                with Image.open(ROOT/'docs/assets/legendary-crafting/wyvern-helmet-selected.png') as image:
                    draw=ImageDraw.Draw(image)
                    draw.rectangle((1150,480,1200,510),fill=(30,30,30))
                    draw.rectangle((1220,480,1270,510),fill=(240,240,240))
                    image.save(path)
                screen=SimpleNamespace(page='forge',source=str(path),words=[
                    {'text':'制作装备【双足飞龙】','confidence':1}])
                nav=SimpleNamespace(adb=Mock(serial='test'),navigate=Mock(return_value=screen),control=Mock())
                loop=LegendaryForgeLoop(nav,WorkflowOptions(slot='helmet',track_craft_gold=gold,track_craft_consumption=True),
                                       Ledger(Limits()),nav.control,journal)
                with patch('e7_assistant.legendary_crafting.number',side_effect=lambda screen,key,*args:
                           '5000/400' if key=='material' else '1000000'):
                    preview=loop.configure()
                self.assertEqual(preview.resources,{'craft_material':5000,**({'gold':1000000} if gold else {})})
                self.assertEqual(preview.cost,{})
                self.assertEqual(preview.count,1)
                nav.adb.tap.assert_not_called()

    def test_result_animation_retries_read_only_until_actual_title_visible(self):
        animation=inspect_screen(ROOT/'docs/assets/legendary-crafting/single-result-animation.png')
        stable=inspect_screen(ROOT/'docs/assets/legendary-crafting/single-legendary-result.png')
        with self.assertRaises(ValueError):verify_legendary_result(animation,'helmet','speed')
        nav=SimpleNamespace(read=Mock(return_value=stable),adb=Mock(),journal=None,control=Mock())
        self.assertEqual(wait_legendary_result(nav,animation,'helmet','speed'),stable)
        self.assertEqual(nav.read.call_count,1)
        nav.adb.tap.assert_not_called()
        nav.read=Mock(return_value=animation)
        with self.assertRaises(ValueError):wait_legendary_result(nav,animation,'helmet','speed')
        self.assertEqual(nav.read.call_count,7)
        nav.adb.tap.assert_not_called()
    def test_counter_ignores_full_screen_ocr_missing_leading_digit(self):
        screen=SimpleNamespace(source=str(ROOT/'docs/assets/legendary-crafting/after-single-craft-170.png'),
                               words=[{'text':'70','confidence':.999,'center':(554,352)}])
        self.assertEqual(read_charges(screen),170)
    def test_actual_single_result_cannot_be_mistaken_for_forge_background(self):
        screen=inspect_screen(ROOT/'docs/assets/legendary-crafting/single-legendary-result.png')
        self.assertEqual(screen.page,'legendary_craft_result')
        verify_legendary_result(screen,'helmet','speed')
        for slot,gear_set in (('weapon','speed'),('helmet','crit')):
            with self.assertRaises(ValueError):verify_legendary_result(screen,slot,gear_set)

    def test_actual_modal_detects_selected_set_and_rejects_unselected_sets(self):
        screen=inspect_screen(FIXTURE)
        self.assertEqual(screen.page,'legendary_craft_confirmation')
        verify_set_selection(screen,'speed')
        for name in ('crit','hit'):
            with self.assertRaises(ValueError):verify_set_selection(screen,name)

    def test_source_and_count_validation(self):
        for source,gear_set in ((0,'speed'),(1,'protection'),(2,'counter'),(3,'immunity'),(4,'torrent')):
            self.assertEqual(WorkflowOptions(source_index=source,legendary_set=gear_set).legendary_set,gear_set)
        for updates in ({'legendary_set':'counter'},{'legendary_count':0},{'legendary_count':True}):
            with self.assertRaises(ValueError):WorkflowOptions(**updates)

    def test_wrong_source_set_sends_no_input(self):
        nav=Mock()
        with self.assertRaises(ValueError):preview_legendary(nav,WorkflowOptions(),Mock(),'torrent',Mock())
        nav.adb.tap.assert_not_called()

    def run_case(self,after_charges=170,after_material=960,result_page='legendary_craft_result',budget=1000):
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'run')
            guard=CraftSessionGuard(Path(temporary)/'craft-pending','test-legendary')
            control=TaskControl()
            screen=SimpleNamespace(page='legendary_craft_confirmation',source=str(FIXTURE),
                                   find=lambda *args:{'center':(816,550)})
            nav=SimpleNamespace(directory=journal.directory,adb=Mock(serial='test-legendary'),
                                control=control,read=lambda:screen,last_image=str(FIXTURE),transition=Mock())
            preview={'state':'preview_ready','last_image':str(FIXTURE),'charges':171,
                     'resources':{'craft_material':1000},'cost':{'craft_material':40},
                     'gear_set':'speed','slot':'helmet','source_index':0,'committed':False}
            ledger=Ledger(Limits(craft_material=budget))
            loop=Mock()
            loop.wait_for.return_value=SimpleNamespace(page=result_page)
            loop.settlement_preview.return_value=ForgePreview({'craft_material':after_material},{},'helmet',1,0,str(FIXTURE))
            with patch('e7_assistant.legendary_crafting.preview_legendary',return_value=preview),\
                 patch('e7_assistant.legendary_crafting.verify_set_selection'),\
                 patch('e7_assistant.legendary_crafting.verify_legendary_result'),\
                 patch('e7_assistant.legendary_crafting.number',return_value='1000/40'),\
                 patch('e7_assistant.legendary_crafting.read_charges',return_value=after_charges),\
                 patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop):
                result=run_legendary(nav,WorkflowOptions(legendary_set='speed',legendary_count=1),ledger,journal)
            return result,nav.adb.tap.call_args_list,guard.read(),nav.transition.call_args_list

    def test_one_commit_requires_both_material_and_charge_settlement(self):
        result,taps,pending,_=self.run_case()
        self.assertEqual(result['state'],'complete')
        self.assertEqual(result['completed'],1)
        self.assertEqual(result['spent']['craft_material'],40)
        self.assertEqual(len(taps),1)
        self.assertFalse(result['outcome_unknown'])
        self.assertIsNone(pending)

    def test_abnormal_charge_or_wrong_material_preserves_pending_no_repeat(self):
        for options in ({'after_charges':172},{'after_material':959},{'result_page':'inventory_full'}):
            with self.subTest(options=options):
                result,taps,pending,_=self.run_case(**options)
                self.assertEqual(result['state'],'failed')
                self.assertTrue(result['outcome_unknown'])
                self.assertEqual(len(taps),1)
                self.assertEqual(pending['before']['mode'],'legendary')

    def test_budget_stops_before_commit_and_cancels_modal(self):
        result,taps,pending,transitions=self.run_case(budget=1)
        self.assertEqual(result['state'],'budget_reached')
        self.assertEqual(taps,[])
        self.assertIsNone(pending)
        self.assertEqual(transitions[0].args,('cancel_legendary_craft',))

    def test_recovery_checks_both_balances_and_never_sends_commit(self):
        import json
        for charges in (170,171):
            with self.subTest(charges=charges),tempfile.TemporaryDirectory() as temporary:
                original=Journal(Path(temporary)/'original')
                journal=Journal(Path(temporary)/'recovery')
                before={'source_index':0,'slot':'helmet','gear_set':'speed','charges':171,
                        'resources':{'craft_material':1000},'cost':{'craft_material':40}}
                guard=CraftSessionGuard(Path(temporary)/'craft-pending','test-legendary')
                operation=guard.begin('craft',{'mode':'legendary',**before},{},original.directory)
                original.emit('legendary_commit_intent',operation_id=operation,preview=before)
                nav=SimpleNamespace(adb=Mock(serial='test-legendary'),read=lambda:SimpleNamespace(page='forge'),
                                    directory=journal.directory,control=TaskControl())
                ledger=Ledger(Limits(craft_material=1000))
                final=SimpleNamespace(resources={'craft_material':960},cost={'craft_material':40},image=str(FIXTURE))
                loop=Mock();loop.configure.return_value=final;loop.preview.return_value=final
                with patch('e7_assistant.legendary_crafting.LegendaryForgeLoop',return_value=loop),\
                     patch('e7_assistant.legendary_crafting.read_charges',return_value=charges):
                    if charges==170:
                        result=settle_legendary(nav,WorkflowOptions(),ledger,journal)
                        loop.configure.assert_called_once()
                        self.assertEqual(result['recovered'],1)
                        self.assertIsNone(guard.read())
                        self.assertEqual(ledger.spent['craft_material'],40)
                    else:
                        with self.assertRaises(ValueError):settle_legendary(nav,WorkflowOptions(),ledger,journal)
                        self.assertIsNotNone(guard.read())
                nav.adb.tap.assert_not_called()
