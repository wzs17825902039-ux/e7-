from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_vision import inspect_inventory,inventory_context
from e7_assistant.inventory_scan import InventoryTraversal,rows,same_row
from e7_assistant.inventory_tracking import inspect_tracking
from e7_assistant.workflow_screen import inspect_screen


class InventoryLiveRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        cls.before=inspect_screen(cls.assets/'01-before.png')
        cls.after=inspect_screen(cls.assets/'03-after-144.png')

    def test_actual_locked_plus3_is_skipped_even_when_level_is_obscured(self):
        screen=replace(self.before,words=tuple(w for w in self.before.words if w['text']!='+3'))
        report=inspect_inventory(screen)
        first=report['cards'][0]
        self.assertIsNone(first['level'])
        self.assertEqual(first['enhancement'],3)
        self.assertFalse(first['eligible'])
        self.assertTrue(report['badge_evidence']['badge0_0']['accepted'])

    def test_actual_sort_crop_recovers_missing_global_word(self):
        screen=replace(self.after,words=tuple(w for w in self.after.words if w['text']!='获得'))
        evidence={}
        self.assertEqual(inventory_context(screen,evidence),('1049/1200','获得'))
        self.assertTrue(evidence['inventory_sort']['accepted'])
        self.assertGreaterEqual(evidence['inventory_sort']['confidence'],.95)

    def test_confirmed_context_avoids_extra_ocr(self):
        words=({'text':'获得','confidence':1.,'center':(900,107)},
               {'text':'1049/1200','confidence':1.,'center':(1065,107)})
        with patch('e7_assistant.local_ocr.read_local_regions') as reader:
            self.assertEqual(inventory_context(replace(self.before,words=words)),('1049/1200','获得'))
            reader.assert_not_called()

    def test_diagnostic_candidates_do_not_replace_accepted_field_comparison(self):
        before={'inventory_context':('1049/1200','获得'),'cards':[{'enhancement':3}],
                'badge_evidence':{'raw':'+3','confidence':.96}}
        after={**before,'badge_evidence':{'raw':'3','confidence':.98}}
        BatchSelectionDriver._verify_unchanged(before,after)
        with self.assertRaises(ValueError):
            BatchSelectionDriver._verify_unchanged(before,{**after,'cards':[{'enhancement':0}]})

    def test_four_actual_scroll_samples_align_two_complete_rows(self):
        before=inspect_inventory(self.before)
        for name in ('02-after.png','03-after-144.png','04-after-141.png','05-after-independent.png'):
            with self.subTest(name=name):
                after=inspect_inventory(inspect_screen(self.assets/name))
                traversal=InventoryTraversal()
                traversal.start(before)
                self.assertEqual(traversal.advance(before,after),1)
                self.assertEqual(traversal.covered_rows,4)
                self.assertFalse(traversal.end_verified)
                # 上述来源的错位两行不能与新第一行拼接。
                self.assertFalse(same_row(rows(before)[2],rows(after)[0]))

    def test_same_quality_same_main_but_different_set_icon_is_rejected(self):
        before=inspect_inventory(self.before)
        after=inspect_inventory(inspect_screen(self.assets/'02-after.png'))
        old,new=rows(before)[1][2],rows(after)[1][2]
        self.assertEqual((old['rarity'],old['level'],old['enhancement']),
                         (new['rarity'],new['level'],new['enhancement']))
        self.assertFalse(inspect_tracking(old,new)['matched'])

    def test_blank_tracking_patch_never_proves_card_identity(self):
        from PIL import Image
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path=Path(folder)/'blank.png'
            Image.new('RGB',(1280,720),'black').save(path)
            card={'tracking_source':str(path),'tracking_box':(153,161,226,259)}
            self.assertFalse(inspect_tracking(card,card)['matched'])

    def test_scrollbar_diagnostic_variation_does_not_hide_tail_state_change(self):
        before={'tail_layout':{'end_verified':False,'tail_count':None,'row':None,
                              'bottom_cap_match':.2,'cells':[{'column':0,'state':'unknown','level_pixels':2}]}}
        after={'tail_layout':{'end_verified':False,'tail_count':None,'row':None,
                             'bottom_cap_match':.3,'cells':[{'column':0,'state':'unknown','level_pixels':3}]}}
        BatchSelectionDriver._verify_unchanged(before,after)
        with self.assertRaises(ValueError):
            BatchSelectionDriver._verify_unchanged(before,{'tail_layout':{**after['tail_layout'],'tail_count':1}})

    def test_same_position_image_comparison_keeps_point995_identity_gate(self):
        before={'cards':[{'enhancement':0,'identity_vector':[1.,0.],'signature':'old'}]}
        after={'cards':[{'enhancement':0,'identity_vector':[.9999995,.001],'signature':'new'}]}
        BatchSelectionDriver._verify_unchanged(before,after)
        for change in ({'enhancement':3},{'identity_vector':[.99,.141]},
                       {'identity_vector':[float('nan'),0.]}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                BatchSelectionDriver._verify_unchanged(before,{'cards':[{**after['cards'][0],**change}]})

    def test_separate_orange_specks_do_not_become_an_enhancement_badge(self):
        report=inspect_inventory(inspect_screen(self.assets/'06-separated-orange-noise.png'))
        card=report['cards'][19]
        self.assertGreater(card['orange_ratio'],.025)
        self.assertLessEqual(card['orange_component_ratio'],.025)
        self.assertEqual(card['enhancement'],0)
        self.assertTrue(card['eligible'])

    def test_weapon_rows_align_without_matching_weapon_to_helmet(self):
        before=inspect_inventory(inspect_screen(self.assets/'07-weapons-before.png'))
        after=inspect_inventory(inspect_screen(self.assets/'08-weapons-after.png'))
        traversal=InventoryTraversal()
        traversal.start(before)
        self.assertEqual(traversal.advance(before,after),1)
        helmet,weapon=rows(before)[0][0],rows(after)[1][0]
        self.assertEqual(helmet['rarity'],weapon['rarity'])
        self.assertFalse(inspect_tracking(helmet,weapon)['matched'])

    def test_actual_fractional_scroll_alignment_keeps_point995_gate(self):
        before=inspect_inventory(inspect_screen(self.assets/'09-subpixel-before.png'))
        after=inspect_inventory(inspect_screen(self.assets/'10-subpixel-after.png'))
        traversal=InventoryTraversal()
        traversal.start(before)
        self.assertEqual(traversal.advance(before,after),1)
        for i in (0,1):
            for old,new in zip(rows(before)[i+1],rows(after)[i]):
                proof=inspect_tracking(old,new)
                self.assertTrue(proof['matched'])
                self.assertGreaterEqual(proof['score'],.995)

    def test_actual_daily_modals_are_not_background_inventory(self):
        for name,page in [('11-date-change.png','date_change'),
                          ('12-attendance-mailed.png','attendance_reward'),
                          ('13-attendance-stable.png','attendance_reward'),
                          ('14-friendship-notice.png','friendship_notice')]:
            with self.subTest(name=name):
                screen=inspect_screen(self.assets/name)
                self.assertEqual(screen.page,page)
                with self.assertRaises(ValueError):
                    inspect_inventory(screen)

    def test_purple_card_render_sampling_does_not_break_verified_overlap(self):
        before=inspect_inventory(inspect_screen(self.assets/'15-purple-sampling-before.png'))
        after=inspect_inventory(inspect_screen(self.assets/'16-purple-sampling-after.png'))
        traversal=InventoryTraversal()
        traversal.start(before)
        self.assertEqual(traversal.advance(before,after),1)
        self.assertFalse(same_row(rows(before)[0],rows(after)[0]))
        proof=inspect_tracking(rows(before)[2][5],rows(after)[1][5])
        self.assertTrue(proof['matched'])
        self.assertGreaterEqual(proof['score'],.995)
        self.assertLessEqual(proof['mae'],5)

    def test_animated_purple_glow_does_not_replace_equipment_identity(self):
        before=inspect_inventory(inspect_screen(self.assets/'17-purple-glow-before.png'))
        after=inspect_inventory(inspect_screen(self.assets/'18-purple-glow-after.png'))
        traversal=InventoryTraversal()
        traversal.start(before)
        self.assertEqual(traversal.advance(before,after),1)
        proof=inspect_tracking(rows(before)[2][5],rows(after)[1][5])
        self.assertTrue(proof['matched'])
        self.assertGreaterEqual(proof['score'],.995)
        self.assertFalse(same_row(rows(before)[0],rows(after)[0]))

    def test_exposed_bottom_cards_are_not_a_tail_before_scrollbar_bottom(self):
        reports=[inspect_inventory(inspect_screen(self.assets/name)) for name in
                 ('19-exposed-row-before.png','20-exposed-row-stable.png')]
        for report in reports:
            self.assertFalse(report['tail_layout']['end_verified'])
            self.assertEqual(report['tail_layout']['tail_count'],7)
            self.assertIsNone(report['tail_layout']['row'])
            self.assertEqual(len(rows(report)),3)
            self.assertEqual(len(report['cards']),21)
        BatchSelectionDriver._verify_unchanged(
            {k:v for k,v in reports[0].items() if k!='source'},
            {k:v for k,v in reports[1].items() if k!='source'})

    def test_actual_one_pixel_ocr_anchor_jitter_requires_full_card_proof(self):
        from copy import deepcopy
        reports=[inspect_inventory(inspect_screen(self.assets/name)) for name in
                 ('21-anchor-jitter-before.png','22-anchor-jitter-after.png')]
        before,after=({k:v for k,v in r.items() if k!='source'} for r in reports)
        self.assertEqual(before['cards'][0]['center'][1]-after['cards'][0]['center'][1],1)
        BatchSelectionDriver._verify_unchanged(before,after)
        for change in ({'center':(before['cards'][0]['center'][0],before['cards'][0]['center'][1]+2)},
                       {'level':90},{'selected':True}):
            bad=deepcopy(after)
            bad['cards'][0].update(change)
            with self.assertRaises(ValueError):
                BatchSelectionDriver._verify_unchanged(before,bad)

    def test_decorative_level_dot_is_recorded_without_inventing_a_digit(self):
        from e7_assistant.local_ocr import _value_text
        report=inspect_inventory(inspect_screen(self.assets/'21-anchor-jitter-before.png'))
        card=rows(report)[2][2]
        self.assertEqual(card['level'],85)
        evidence=report['level_evidence']['level2_2']
        self.assertTrue(evidence['accepted'])
        self.assertTrue(any(c.get('raw_text')=='85.' and c['text']=='85' for c in evidence['candidates']))
        for text in ('5.','8.5','8.5.','850.','85..','8S.','0.'):
            self.assertEqual(_value_text(text,'level0_0'),text)
        self.assertEqual(_value_text('85.','main'),'85.')

    def test_quality_frame_confirms_purple_when_body_glow_is_ambiguous(self):
        reports=[inspect_inventory(inspect_screen(self.assets/name)) for name in
                 ('23-rarity-glow-before.png','24-rarity-glow-after.png')]
        old,new=reports[0]['cards'][2],reports[1]['cards'][2]
        self.assertEqual((old['rarity'],new['rarity']),('purple','purple'))
        self.assertEqual(old['rarity_evidence']['source'],'body')
        self.assertEqual(new['rarity_evidence']['source'],'frame')
        self.assertGreater(new['rarity_evidence']['frame_purple'],.35)
        BatchSelectionDriver._verify_unchanged(
            {k:v for k,v in reports[0].items() if k!='source'},
            {k:v for k,v in reports[1].items() if k!='source'})

    def test_merged_global_tokens_locate_rows_but_do_not_assign_item_levels(self):
        screen=inspect_screen(self.assets/'25-merged-level-anchors.png')
        merged=[w for w in screen.words if w['text'] in ('85元','85元m')]
        self.assertGreaterEqual(len(merged),3)
        report=inspect_inventory(screen)
        self.assertEqual(len(rows(report)),3)
        self.assertEqual(len(report['cards']),21)
        self.assertEqual(rows(report)[1][0]['level'],85)
        unknown=inspect_inventory(screen,read_numbers=lambda path,regions:{})
        self.assertEqual(len(rows(unknown)),3)
        self.assertTrue(all(c['level'] is None and not c['eligible'] for c in unknown['cards']))
        # 单个低置信度合并词不能补出整行；低置信度纯数字仍不作锚点。
        for mode in ('single_merged','weak_plain'):
            words=[]
            kept=False
            for word in screen.words:
                if 330<word['center'][1]<360 and word['text'] in ('85元','85元m'):
                    if mode=='weak_plain':
                        words.append({**word,'text':'85','confidence':.7})
                    elif not kept:
                        words.append(word)
                        kept=True
                else:
                    words.append(word)
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                inspect_inventory(replace(screen,words=tuple(words)),read_numbers=lambda path,regions:{})

    def test_actual_temporary_quality_loss_can_only_trigger_read_only_recovery(self):
        from copy import deepcopy
        from types import SimpleNamespace
        from e7_assistant.tasks import TaskControl
        before=inspect_inventory(inspect_screen(self.assets/'26-quality-missing-before.png'))
        observed=inspect_inventory(inspect_screen(self.assets/'27-quality-missing-after.png'))
        self.assertEqual(rows(before)[1][2]['rarity'],'purple')
        self.assertEqual(rows(observed)[1][2]['rarity'],'purple')
        self.assertEqual(rows(observed)[1][2]['rarity_evidence']['source'],'outer_purple_glow')
        BatchSelectionDriver._verify_unchanged(
            {k:v for k,v in before.items() if k!='source'},
            {k:v for k,v in observed.items() if k!='source'})
        # 原照片可由新光晕证据恢复；保留真实像素上的字段缺失保护断言。
        missing=deepcopy(observed)
        rows(missing)[1][2].update(rarity=None,known=False,eligible=False)
        self.assertIsNone(rows(missing)[1][2]['rarity'])
        self.assertTrue(BatchSelectionDriver._can_retry_missing(before,missing))
        with self.assertRaises(ValueError):
            BatchSelectionDriver._verify_unchanged(
                {k:v for k,v in before.items() if k!='source'},
                {k:v for k,v in missing.items() if k!='source'})
        frames=iter((missing,before))
        control=TaskControl()
        control.wait=lambda seconds:control.checkpoint()
        nav=SimpleNamespace(read=lambda:next(frames),control=control,journal=None)
        recovered=BatchSelectionDriver(nav,reader=lambda frame:frame).observe_unchanged(before)
        self.assertIs(recovered,before)
        self.assertIsNone(rows(missing)[1][2]['rarity'])


if __name__=='__main__':
    unittest.main()
