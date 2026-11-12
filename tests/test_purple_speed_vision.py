import json
from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.workflow import BatchItem
from e7_assistant.rules import Equipment
from e7_assistant.workflow_screen import inspect_screen, classify
from e7_assistant.purple_speed_vision import inspect_purple_speed_batch

ASSETS=Path(__file__).resolve().parents[1]/'docs/assets/batch-selection-2026-11-10'


class PurpleSpeedTests(unittest.TestCase):
    def test_speed_only_reader_recovers_real_six_badges_with_glyph_fallback(self):
        root=ASSETS.parents[2]/'runs/pending-inventory-resume-484033fe'
        previous=json.loads((root/'result.json').read_text(encoding='utf8'))
        items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked']) for i in previous['items']]
        speed_rows=dict(enumerate((2,0,2,2,0,1,2,0,0,0,2,2,2,2,2,1)))
        report=inspect_purple_speed_batch(inspect_screen(root/'workflow-0016.png'),items,speed_rows,{},ignore_levels=True)
        self.assertEqual([r['equipment']['enhancement'] for r in report['records']],
                         [3,3,6,3,4,6,4,6,3,3,6,3,6,3,3,4])
        self.assertEqual([r['equipment']['stats']['speed'] for r in report['records']],
                         [3,3,5,4,4,8,3,7,3,3,6,3,7,4,4,4])

    def test_real_sixteen_required_fields_match_full_observation(self):
        truth=json.loads((ASSETS/'purple-speed-truth.json').read_text(encoding='utf8'))
        original=[BatchItem(str(i),Equipment(**record['equipment']),record['selected'],record['locked'])
                  for i,record in enumerate(truth)]
        driver=BatchEnhancementDriver(None,purple_speed_only=True)
        items=driver.normalize_items(original)
        screen=inspect_screen(ASSETS/'round-stage3-zero.png')
        report=inspect_purple_speed_batch(screen,items,driver.speed_rows,{})
        self.assertEqual(len(report['records']),16)
        for actual,expected in zip(report['records'],truth):
            self.assertEqual(actual['equipment']['enhancement'],expected['equipment']['enhancement'])
            self.assertEqual(actual['equipment']['stats'],{'speed':expected['equipment']['stats']['speed']})
            self.assertIsNone(actual['equipment']['game_score'])
            self.assertEqual(actual['equipment']['observation_scope'],'purple_speed')
            self.assertEqual(actual['selected'],expected['selected'])
            self.assertEqual(actual['locked'],expected['locked'])
        with patch('e7_assistant.purple_speed_vision.match_icon',return_value=('crit',.99)):
            with self.assertRaisesRegex(ValueError,'速度行图标'):
                inspect_purple_speed_batch(screen,items,driver.speed_rows,{})

    def test_red_final_badge_is_fifteen_not_zero_and_four_stats(self):
        from e7_assistant.batch_vision import inspect_batch
        report=inspect_batch(ASSETS/'final-red-badge.png',{i:'helmet' for i in range(16)})
        self.assertFalse(report['issues'])
        final=report['records'][4]['equipment']
        self.assertEqual(final['enhancement'],15)
        self.assertEqual(final['stats'],{'speed':15,'atk_flat':73,'hp_pct':6,'atk_pct':5})

    def test_refund_overlay_precedes_batch_page(self):
        texts=['批量强化','强化材料','全部选择','整理','获得奖励',
               '超过上限的经验值已作为强化粉末返还。','点击关闭']
        words=[{'text':text,'confidence':.99,'center':(600,300)} for text in texts]
        self.assertEqual(classify(words),'enhancement_refund')
        self.assertEqual(inspect_screen(ASSETS/'final-refund.png').page,'enhancement_refund')
        wrong=[word for word in words if '超过上限' not in word['text']]
        self.assertNotEqual(classify(wrong),'enhancement_refund')
