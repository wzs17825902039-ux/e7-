from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw

from e7_assistant.batch_vision import _stat_guided_crop_consensus,inspect_batch,inspect_selection_flags,verify_selection_page


class DimmedStatConsensusTests(unittest.TestCase):
    def test_stage_buttons_change_when_selected_equipment_changes(self):
        root=Path(__file__).resolve().parents[1]/'runs/full-workflow-de0200e3'
        flags=verify_selection_page(root/'workflow-0058.png',root/'selection-3c1008039ac9.png',16)
        self.assertEqual([i for i,value in enumerate(flags) if value],[0,15])

    def test_impossible_percent_is_independently_reread_from_unit_and_number(self):
        source=Path(__file__).resolve().parents[1]/'runs/pending-inventory-resume-e41236fc/workflow-0017.png'
        report=inspect_batch(source,{i:'helmet' for i in range(16)},ignore_levels=True,
                             require_score=False,ignore_purple_main=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['records'][4]['equipment']['stats']['hp_pct'],7)
        evidence=report['ocr_details']['stat4_1']
        self.assertEqual(evidence['method'],'percent_icon_then_numeric_ocr')
        self.assertEqual(evidence['out_of_range_rejection']['text'],'70%')

    def test_live_summon_broadcast_disappearing_does_not_change_page(self):
        root=Path(__file__).resolve().parents[1]/'runs/pending-inventory-resume-00f0f5d8'
        self.assertEqual(verify_selection_page(root/'workflow-0012.png',root/'selection-c6bb9847667a.png',16),[False]*16)

    def test_live_summon_broadcast_shadow_is_not_a_page_change(self):
        root=Path(__file__).resolve().parents[1]/'runs/full-workflow-60a52030'
        flags=verify_selection_page(root/'selection-b715ad26606c.png',root/'selection-10b59e763a9c.png',16)
        self.assertEqual(flags,[False,False]+[True]*14)

    def test_impossible_initial_percent_is_rejected_instead_of_scored(self):
        source=Path(__file__).resolve().parents[1]/'runs/live-adb-recovery-check.png'
        with patch('e7_assistant.numeric_units.read_percent_value',return_value=None):
            report=inspect_batch(source,{i:'helmet' for i in range(16)},ignore_levels=True,
                                 require_score=False,ignore_purple_main=True)
        self.assertTrue(any('百分比副属性超过当前强化阶段' in issue for issue in report['issues']))

    def test_graph_selection_checks_known_page_and_rejects_overlay(self):
        root=Path(__file__).resolve().parents[1]/'runs/current-result-recovery-5c000646'
        before,after=root/'workflow-0003.png',root/'workflow-0004.png'
        flags=verify_selection_page(before,after,16)
        self.assertEqual([i for i,v in enumerate(flags) if v],[0,1])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'changed.png'
            with Image.open(after) as image:
                ImageDraw.Draw(image).rectangle((860,75,980,115),fill='black')
                image.save(path)
            with self.assertRaisesRegex(ValueError,'页面区域变化'):
                verify_selection_page(before,path,16)

    def test_independent_crop_requires_original_raw_guided_and_accepted_shifted(self):
        original={'candidates':[{'variant':'raw','text':'7%','confidence':.98},
                                {'variant':'guided','text':'7%','confidence':.99}]}
        shifted={'accepted':True,'text':'7%','candidates':[{'variant':'raw','text':'7%','confidence':.96}]}
        self.assertEqual(_stat_guided_crop_consensus(original,shifted),'7%')
        for case in ('guided','raw','shifted','conflict'):
            a,b=deepcopy(original),deepcopy(shifted)
            if case=='guided':a['candidates'][1]['confidence']=.89
            if case=='raw':a['candidates'][0]['confidence']=.89
            if case=='shifted':b['accepted']=False
            if case=='conflict':a['candidates'].append({'variant':'detected','text':'70%','confidence':.95})
            with self.subTest(case=case):self.assertIsNone(_stat_guided_crop_consensus(a,b))

    def test_actual_dimmed_seven_percent_is_read_without_changing_numeric_text(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/sale-preview-2026-11-10/dimmed-stat-seven-percent.png'
        slots={i:'helmet' if i<2 else 'boots' if i<7 else 'ring' for i in range(16)}
        report=inspect_batch(source,slots,ignore_levels=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['records'][11]['equipment']['stats']['atk_pct'],7)
        self.assertEqual(len(report['records']),16)

    def test_actual_committed_result_preserves_seven_percent_and_growth(self):
        source=Path(__file__).resolve().parents[1]/'runs/after-current-commit-175808.png'
        slots={i:'helmet' if i<2 else 'boots' if i<7 else 'ring' for i in range(16)}
        report=inspect_batch(source,slots,ignore_levels=True)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['records'][5]['equipment']['stats']['atk_pct'],7)
        self.assertEqual(report['records'][5]['equipment']['stats']['hp_pct'],9)
        self.assertEqual(report['records'][0]['equipment']['stats']['speed'],6)
        self.assertEqual(inspect_selection_flags(source,16),[r['selected'] for r in report['records']])
        self.assertEqual([i for i,v in enumerate(inspect_selection_flags(source,16)) if v],[0,1,5])
