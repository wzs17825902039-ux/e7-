"""真实取样图片的选装动画、数字裁切及锁动作回归；不连接设备。"""
from copy import deepcopy
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from PIL import Image,ImageDraw

from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_selection import BatchSelectionDriver,SelectionImageUnstable
from e7_assistant.batch_vision import inspect_batch,verify_selection_page,verify_stable_batch_pixels
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.lock_vision import inspect_batch_lock,verify_batch_lock_pixels,matches_locked_level
from e7_assistant.rules import Equipment
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow import BatchItem
from e7_assistant.workflow_screen import inspect_screen

ASSETS=Path(__file__).resolve().parents[1]/'docs/assets/batch-live-2026-11-10'


class BatchLiveRegressionTests(unittest.TestCase):
    def test_boosted_red_organize_uses_attributes_and_locked_overlay(self):
        from e7_assistant.batch_sale_vision import inspect_organized
        root=ASSETS.parents[2]/'runs/selected-inventory-resume-f711b882'
        screen=inspect_screen(root/'workflow-0016.png')
        state=inspect_organized(screen,root/'workflow-0011.png',16,track_gold=False,
                                locked_indices={9,10,12},boosted_red_indices=set(range(2,16)))
        self.assertEqual(state.selected,(False,)*16)
        with Image.open(screen.source) as original, TemporaryDirectory() as temporary:
            for box in ((622,167,648,182),(264,389,280,410)):
                altered=original.copy()
                ImageDraw.Draw(altered).rectangle(box,fill='white')
                path=Path(temporary)/'changed.png';altered.save(path)
                with self.assertRaises(ValueError):
                    inspect_organized(replace(screen,source=str(path)),root/'workflow-0011.png',16,
                                      track_gold=False,locked_indices={9,10,12},
                                      boosted_red_indices=set(range(2,16)))

    def test_lock_ignores_equipment_glow_but_checks_every_attribute_and_lock(self):
        root=ASSETS.parents[2]/'runs/selected-inventory-resume-1be900ed'
        with Image.open(root/'workflow-0023.png') as before, Image.open(root/'workflow-0030.png') as after:
            verify_batch_lock_pixels(before,after,16,9,attributes_only=True)
            for index in (9,10):
                altered=after.copy()
                dx=(index%4)*244;dy=(index//4)*129
                ImageDraw.Draw(altered).rectangle((134+dx,167+dy,160+dx,182+dy),fill='white')
                with self.assertRaises(ValueError):
                    verify_batch_lock_pixels(before,altered,16,9,attributes_only=True)
            with self.assertRaises(ValueError):
                verify_batch_lock_pixels(before,before,16,9,attributes_only=True)

    def test_real_plus4_badge_optional_plus_does_not_reject_batch(self):
        selection=json.loads((ASSETS/'11-plus4-selection.json').read_text(encoding='utf8'))
        slots={i:r['equipment']['slot'] for i,r in enumerate(selection['registered'])}
        report=inspect_batch(ASSETS/'11-plus4-optional-plus.png',slots,ignore_levels=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(len(report['records']),16)
        self.assertEqual(report['records'][14]['equipment']['enhancement'],4)
        self.assertTrue(report['ocr_details']['badge14']['accepted'])

    def test_stable_result_pixels_reject_changed_attribute_selection_and_lock(self):
        path=ASSETS/'07-plus9-speed8.png'
        report=inspect_batch(path,{i:'helmet' if i<13 else 'ring' for i in range(16)},ignore_levels=True)
        items=[BatchItem(str(r['index']),Equipment(**r['equipment']),r['selected'],r['locked'])
               for r in report['records']]
        verify_stable_batch_pixels(path,path,items)
        changed=list(items);changed[0]=replace(items[0],selected=not items[0].selected)
        with self.assertRaises(ValueError):verify_stable_batch_pixels(path,path,changed)
        changed=list(items);changed[0]=replace(items[0],locked=not items[0].locked)
        with self.assertRaises(ValueError):verify_stable_batch_pixels(path,path,changed)
        with TemporaryDirectory() as folder,Image.open(path) as source:
            altered=source.copy()
            ImageDraw.Draw(altered).rectangle((135,205,185,225),fill='white')
            target=Path(folder)/'changed-stat.png';altered.save(target)
            with self.assertRaises(ValueError):verify_stable_batch_pixels(path,target,items)

    def test_real_main_sixty_recovers_full_left_stroke_and_entry(self):
        from e7_assistant.batch_entry import verify_entry
        from e7_assistant.rules import Policy
        selection=json.loads((ASSETS/'10-main-sixty-selection.json').read_text(encoding='utf8'))
        slots={i:r['equipment']['slot'] for i,r in enumerate(selection['registered'])}
        report=inspect_batch(ASSETS/'10-main-sixty.png',slots,ignore_levels=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['records'][9]['main'],{'stat':'def_flat','value':60})
        self.assertTrue(report['ocr_details']['main9']['accepted'])
        self.assertEqual(report['ocr_details']['main9']['expanded_left'],5)
        self.assertEqual(len(verify_entry(selection,report,Policy())),16)

    def test_real_speed_eight_keeps_left_stroke(self):
        slots={i:'helmet' if i<13 else 'ring' for i in range(16)}
        report=inspect_batch(ASSETS/'07-plus9-speed8.png',slots,ignore_levels=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(len(report['records']),16)
        self.assertEqual(report['records'][9]['equipment']['stats'],
                         {'speed':8,'def_pct':8,'cdmg':17})

    def test_last_deselection_allows_disabled_stage_buttons_but_rejects_changed_header(self):
        before=ASSETS/'09-last-selected.png'
        after=ASSETS/'08-final-deselected.png'
        self.assertEqual(verify_selection_page(before,after,16),[False]*16)
        with TemporaryDirectory() as temporary,Image.open(after) as source:
            altered=source.copy()
            ImageDraw.Draw(altered).rectangle((0,0,300,55),fill='white')
            path=Path(temporary)/'wrong-page.png'
            altered.save(path)
            with self.assertRaises(ValueError):
                verify_selection_page(before,path,16)

    def test_actual_clipped_six_and_inventory_entry_fields(self):
        report=inspect_batch(ASSETS/'01-plus0.png',{0:'helmet'})
        self.assertEqual(report['issues'],[])
        self.assertEqual(len(report['records']),1)
        record=report['records'][0]
        self.assertEqual(record['equipment']['stats'],{'atk_pct':8,'speed':3,'resistance':7,'hp_pct':6})
        self.assertEqual(record['main'],{'stat':'hp_flat','value':540})
        self.assertIs(record['locked'],False)
        self.assertTrue(report['ocr_details']['stat0_3']['accepted'])
        self.assertEqual(report['ocr_details']['stat0_3']['text'],'6%')

    def test_real_selection_animation_fails_then_stable_frame_passes(self):
        # 本例核对图像与选择状态；等级已由独立等级回归覆盖。
        reports=[inspect_inventory(inspect_screen(ASSETS/name),
                    read_numbers=lambda path,regions:{key:'85' for key in regions})
                 for name in ('02-selection-before.png','03-selection-animation.png','04-selection-stable.png')]
        with self.assertRaises(SelectionImageUnstable):
            BatchSelectionDriver._verify_click(reports[0],reports[1],(0,0))
        BatchSelectionDriver._verify_click(reports[0],reports[2],(0,0))
        altered=deepcopy(reports[2])
        altered['cards'][1]['selected']=True
        with self.assertRaisesRegex(ValueError,'勾选集合'):
            BatchSelectionDriver._verify_click(reports[0],altered,(0,0))

    def test_lock_templates_reject_empty_wrong_page_and_blank(self):
        with Image.open(ASSETS/'05-plus3-unlocked.png') as image:
            self.assertIs(inspect_batch_lock(image,'batch_enhancement',0,True)['locked'],False)
            self.assertIsNone(inspect_batch_lock(image,'inventory',0,True)['locked'])
            self.assertIsNone(inspect_batch_lock(image,'batch_enhancement',0,False)['locked'])
            self.assertIsNone(inspect_batch_lock(image,'batch_enhancement',1,True)['locked'])
        for color in ('white','black','#808080'):
            self.assertIsNone(inspect_batch_lock(Image.new('RGB',(1280,720),color),
                                                'batch_enhancement',0,True)['locked'])

    def test_lock_body_comparison_rejects_stat_and_other_card_changes(self):
        with Image.open(ASSETS/'05-plus3-unlocked.png') as before,\
             Image.open(ASSETS/'06-plus3-locked.png') as after:
            verify_batch_lock_pixels(before,after,1,0)
            altered=after.copy()
            ImageDraw.Draw(altered).rectangle((134,167,160,182),fill='white')
            with self.assertRaises(ValueError):
                verify_batch_lock_pixels(before,altered,1,0)
            altered=after.copy()
            ImageDraw.Draw(altered).rectangle((134+244,167,160+244,182),fill='white')
            with self.assertRaises(ValueError):
                verify_batch_lock_pixels(before,altered,2,0)

    def test_occluded_level_needs_verified_transition_anchor(self):
        path=ASSETS/'06-plus3-locked.png'
        report=inspect_batch(path,{0:'helmet'})
        self.assertTrue(any('85' in issue for issue in report['issues']))
        with Image.open(path) as image:
            self.assertTrue(matches_locked_level(image,path,0))
            altered=image.copy()
            ImageDraw.Draw(altered).rectangle((35,151,49,160),fill='white')
            self.assertFalse(matches_locked_level(altered,path,0))

    def test_actual_driver_locks_once_with_real_images_and_resources(self):
        before=inspect_screen(ASSETS/'05-plus3-unlocked.png')
        after=inspect_screen(ASSETS/'06-plus3-locked.png')
        state={'locked':False}
        clicks=[]
        control=TaskControl()
        control.wait=lambda seconds:control.checkpoint()
        def tap(x,y):
            clicks.append((x,y))
            state['locked']=True
        current=[BatchItem('test',Equipment('registered','red',85,3,'helmet',
            {'atk_pct':14,'speed':3,'resistance':7,'hp_pct':6},True,True,41),True,False)]
        with TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'run')
            nav=SimpleNamespace(read=lambda:after if state['locked'] else before,
                control=control,adb=SimpleNamespace(tap=tap),journal=journal,directory=journal.directory)
            driver=BatchEnhancementDriver(nav)
            from unittest.mock import patch
            with patch('e7_assistant.lock_vision.verify_batch_lock_pixels',
                       side_effect=[ValueError('已保护装备提示覆盖底行'),None]) as pixels:
                locked=driver.lock_items(current,{'test'})
            self.assertEqual(pixels.call_count,2)
            self.assertIs(locked[0].locked,True)
            self.assertEqual(replace(locked[0],locked=False),current[0])
            self.assertEqual(clicks,[(231,148)])
            self.assertEqual(driver.lock_items(locked,{'test'}),locked)
            self.assertEqual(len(clicks),1)
            self.assertIn('batch_lock_verified',journal.path.read_text(encoding='utf-8'))
