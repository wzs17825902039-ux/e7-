"""红紫混合批次的离线截图及规则回归；不连接模拟器。"""
from dataclasses import replace
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from PIL import Image
from unittest.mock import patch

from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_vision import inspect_batch,read_badge_level
from e7_assistant.rules import Equipment,Policy,evaluate
from e7_assistant.settings import Settings,current_red_gate_settings,red_gate_note
from e7_assistant.workflow import BatchItem,WorkflowTask,WorkflowOptions
from e7_assistant.tasks import TaskControl,Journal,Limits
from e7_assistant.workflow_screen import inspect_batch_controls

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'docs/assets/batch-live-2026-11-10'


class MixedBatchTests(unittest.TestCase):
    def test_unseen_weapon_background_needs_no_position_specific_template(self):
        with Image.open(ROOT/'runs/selected-inventory-resume-fc69a235/workflow-0078.png') as image:
            reference=image.convert('RGB').resize((1661,933))
        for index in range(16):
            with self.subTest(index=index):
                self.assertEqual(read_badge_level(reference,round(index%4*316.667),
                                                 round(index//4*167.333),''),0)

    def test_blank_badge_region_is_not_evidence_for_zero(self):
        for color in ('black','white','gray'):
            with self.subTest(color=color),self.assertRaises(ValueError):
                read_badge_level(Image.new('RGB',(1661,933),color),0,0,'')

    def test_graphic_absence_fallback_rejects_dimmed_enhanced_badges(self):
        from PIL import ImageEnhance
        with Image.open(ASSETS/'11-plus4-optional-plus.png') as image:
            reference=image.convert('RGB').resize((1661,933))
        with patch('e7_assistant.batch_vision._absent_badge_templates',return_value=()), \
             patch('e7_assistant.batch_vision._numbered_badge_templates',return_value=()):
            for gain in (.3,.5,1):
                current=ImageEnhance.Brightness(reference).enhance(gain)
                for index in (6,7,8,9,10,11,14,15):
                    with self.subTest(gain=gain,index=index),self.assertRaises(ValueError):
                        read_badge_level(current,round(index%4*316.667),round(index//4*167.333),'')

    def test_entry_retry_reuses_only_pixel_identical_successful_cards(self):
        source=ROOT/'runs/selected-inventory-resume-fc69a235/workflow-0078.png'
        options=dict(ignore_levels=True,require_score=False,ignore_purple_main=True)
        slots={i:'weapon' for i in range(16)}
        first=inspect_batch(source,slots,**options)
        self.assertEqual(first['issues'],[])
        retry=inspect_batch(source,slots,retry_report=first,**options)
        self.assertEqual(retry['issues'],[])
        self.assertTrue(all(r.get('content_source')=='entry_retry_unchanged_pixels' for r in retry['records']))
        with TemporaryDirectory() as folder:
            changed=Path(folder)/'changed.png'
            with Image.open(source) as image:
                image=image.convert('RGB');image.putpixel((30,170),(0,255,0));image.save(changed)
            report=inspect_batch(changed,slots,retry_report=first,**options)
        self.assertEqual(report['issues'],[])
        self.assertNotEqual(report['records'][0].get('content_source'),'entry_retry_unchanged_pixels')
        self.assertTrue(all(r.get('content_source')=='entry_retry_unchanged_pixels' for r in report['records'][1:]))

    def test_live_unenhanced_weapon_art_is_not_an_unread_badge(self):
        for name in ('runs/full-workflow-33db72be/workflow-0050.png',
                     'runs/selected-inventory-resume-1336f421/workflow-0092.png',
                     'runs/selected-inventory-resume-e43561b0/workflow-0079.png'):
            with self.subTest(source=name):
                report=inspect_batch(ROOT/name,{i:'weapon' for i in range(16)},ignore_levels=True,
                                     require_score=False,ignore_purple_main=True)
                self.assertEqual(report['issues'],[])
                self.assertEqual([r['equipment']['enhancement'] for r in report['records']],[0]*16)

    def test_purple_and_speed_red_record_three_but_score_red_keeps_first_six_target(self):
        from test_workflow import FlowDriver
        class Driver(FlowDriver):
            def __init__(self):
                super().__init__()
                self.groups=[]
            def prepare_enhancement(self,items,target):
                self.groups.append((target,[i.token for i in items if i.selected]))
                return super().prepare_enhancement(items,target)
            def finish_enhancement(self,preview):
                return {'items':[replace(i,equipment=replace(i.equipment,enhancement=self.target))
                                 if i.selected else i for i in self.current],
                        'resources':self.resources(),'image':'after.png'}
        items=[BatchItem('p',Equipment('p','purple',85,0,'helmet',
                                      {'speed':3,'crit':5,'atk_pct':7},True,True),True,False),
               BatchItem('r',Equipment('r','red',85,0,'helmet',
                                      {'speed':3,'crit':3,'atk_pct':4,'resistance':4},True,True),True,False),
               BatchItem('n',Equipment('n','red',85,0,'helmet',
                                      {'atk_pct':8,'crit':5,'cdmg':7,'hp_pct':8},True,True),True,False)]
        with TemporaryDirectory() as folder:
            driver=Driver()
            task=WorkflowTask(driver,WorkflowOptions(first_target=6),
                              Policy(red_profile_enabled=True,sell_failed_red=True,sell_failed_purple=True),
                              Limits(),TaskControl(.2),Journal(Path(folder)/'run'))
            result=task.run_batch(items)
        self.assertEqual(result['state'],'complete')
        # r3要求带速红装保留+3观测，用于累计未加速次数；无速红装仍可首档+6。
        self.assertEqual(driver.groups,[(3,['p','r']),(6,['r','n'])])
        red=next(item for item in result['items'] if item['token']=='r')
        self.assertEqual(red['equipment']['red_speed_misses'],2)
        self.assertEqual(driver.sales,[({'p','r','n'},set(),'sell')])

    def test_unread_enhanced_badges_are_never_assumed_zero(self):
        import json
        folder=ROOT/'docs/assets/batch-selection-2026-11-10'
        truth=json.loads((folder/'purple-speed-truth.json').read_text(encoding='utf8'))
        with Image.open(folder/'round-stage3-zero.png') as image:
            reference=image.convert('RGB').resize((1661,933))
        for index,record in enumerate(truth):
            if record['equipment']['enhancement']<=0:continue
            row,col=divmod(index,4)
            with self.subTest(index=index),self.assertRaises(ValueError):
                read_badge_level(reference,round(col*316.667),round(row*167.333),'')

    def test_live_plus6_graphic_fallback_does_not_accept_other_badges(self):
        source=ROOT/'runs/selected-inventory-resume-6bc910cd/workflow-0024.png'
        with Image.open(source) as image:
            reference=image.convert('RGB').resize((1661,933))
        for index in (5,9,11,14):
            row,col=divmod(index,4)
            self.assertEqual(read_badge_level(reference,round(col*316.667),round(row*167.333),''),6)
        for index in (0,8,12):
            row,col=divmod(index,4)
            with self.assertRaises(ValueError):
                read_badge_level(reference,round(col*316.667),round(row*167.333),'')
        with Image.open(ROOT/'runs/after-current-commit-175808.png') as image:
            reference=image.convert('RGB').resize((1661,933))
        for index in (0,1,5):
            row,col=divmod(index,4)
            with self.subTest(committed=index),self.assertRaises(ValueError):
                read_badge_level(reference,round(col*316.667),round(row*167.333),'')
        with Image.open(ASSETS/'11-plus4-optional-plus.png') as image:
            reference=image.convert('RGB').resize((1661,933))
        for index in (6,7,8,9,10,11,14,15):
            row,col=divmod(index,4)
            with self.subTest(mixed=index),self.assertRaises(ValueError):
                read_badge_level(reference,round(col*316.667),round(row*167.333),'')

    def test_mixed_real_frame_preserves_full_red_and_speed_only_purple(self):
        source=ASSETS/'07-plus9-speed8.png'
        slots={i:'helmet' if i<13 else 'ring' for i in range(16)}
        full=inspect_batch(source,slots,ignore_levels=True,require_score=False,ignore_purple_main=True)
        self.assertEqual(full['issues'],[])
        items=[BatchItem(str(r['index']),Equipment(**r['equipment']),r['selected'],r['locked'])
               for r in full['records']]
        self.assertEqual({i.equipment.rarity for i in items},{'purple','red'})
        driver=BatchEnhancementDriver(None,purple_speed_only=True)
        expected=driver.normalize_items(items)
        report=inspect_batch(source,slots,ignore_levels=True,require_score=False,ignore_purple_main=True,
                             purple_speed_only=True,speed_rows=driver.speed_rows,known_items=expected)
        self.assertEqual(report['issues'],[])
        self.assertEqual(len(report['records']),len(items))
        for old,actual in zip(expected,report['records']):
            with self.subTest(token=old.token):
                for key in ('stats','enhancement','observation_scope','rarity'):
                    self.assertEqual(actual['equipment'][key],getattr(old.equipment,key))
                if old.equipment.observation_scope=='purple_speed':
                    self.assertIsNone(actual['main'])
                    self.assertEqual(set(actual['equipment']['stats']),{'speed'})
        # 恢复记录未存行号时，仍能从当前画面重新找到速度行。
        rebuilt=inspect_batch(source,slots,ignore_levels=True,require_score=False,ignore_purple_main=True,
                              purple_speed_only=True,known_items=expected)
        self.assertEqual(rebuilt['issues'],[])
        self.assertEqual(rebuilt['speed_rows'],report['speed_rows'])
        # 未归一化的完整记录不能在观察中途丢失其他副属性。
        retained=inspect_batch(source,slots,ignore_levels=True,require_score=False,ignore_purple_main=True,
                               purple_speed_only=True,known_items=items)
        self.assertEqual(retained['issues'],[])
        self.assertTrue(all(r['equipment']['observation_scope']=='full' for r in retained['records']))

    def test_refund_overlay_cannot_be_a_normal_batch_page(self):
        source=ROOT/'docs/assets/batch-selection-2026-11-10/final-refund.png'
        self.assertEqual(inspect_batch_controls(source).page,'enhancement_refund')

    def test_purple_right_ignores_flat_main_but_boots_are_not_disposed(self):
        policy=Policy(discard_flat_right_without_speed=True,sell_failed_purple=True)
        item=Equipment('p','purple',None,0,'ring',{'crit':5,'atk_pct':7,'hp_pct':8},False,True,
                       main_stat='def_flat')
        self.assertIn('紫装无速度',evaluate(item,policy).reasons[0])
        fast=replace(item,stats={'speed':3,'crit':5,'atk_pct':7})
        self.assertEqual(evaluate(fast,policy).action,'continue')
        boots=evaluate(replace(fast,slot='boots'),policy)
        self.assertEqual(boots.action,'stop')
        self.assertFalse(boots.discard_allowed)

    def test_red_with_speed_targets_six_and_uses_current_main_whitelist(self):
        policy=Policy(red_profile_enabled=True,right_main_stats={'ring':['atk_pct']})
        item=Equipment('r','red',None,3,'ring',{'speed':3,'crit':3,'hp_pct':4,'resistance':4},
                       False,True,main_stat='atk_pct')
        self.assertEqual(evaluate(item,policy).target_level,6)
        self.assertEqual(evaluate(item,replace(policy,right_main_stats={})).action,'store')

    def test_reset_only_changes_red_gates_and_preserves_hidden_workflow(self):
        settings=Settings()
        settings.policy['red_left_gates']={'0':22,'3':28,'6':34,'9':40,'12':46,'15':52}
        settings.policy['red_right_gates']={'0':20,'3':26,'6':32,'9':38,'12':44,'15':50}
        settings.workflow['track_craft_gold']=True
        self.assertIn('旧版默认',red_gate_note(settings.policy))
        updated=current_red_gate_settings(settings)
        self.assertEqual(updated.workflow,settings.workflow)
        self.assertEqual(updated.limits,settings.limits)
        for key in settings.policy.keys()-{'red_left_gates','red_right_gates'}:
            self.assertEqual(updated.policy[key],settings.policy[key])
        self.assertEqual(updated.policy['red_left_gates']['0'],20)
        self.assertEqual(settings.policy['red_left_gates']['0'],22)
