import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.probe_batch_sale_preview import SalePreviewAdb,count_selected
from e7_assistant.workflow_screen import inspect_screen,classify


class SalePreviewProbeTests(unittest.TestCase):
    def test_actual_organize_count_and_sale_modal_take_priority(self):
        assets=Path(__file__).resolve().parents[1]/'docs/assets/sale-preview-2026-11-10'
        screen=inspect_screen(assets/'organize.png')
        self.assertEqual(count_selected(screen),1)
        dialog=inspect_screen(assets/'sale-dialog.png')
        self.assertEqual(dialog.page,'sale_confirmation')
        self.assertLess(dialog.find('取消',(350,450,650,600))['center'][0],650)

    def test_sale_title_without_modal_body_does_not_authorize_modal(self):
        words=tuple({'text':t,'confidence':1.,'center':(640,180)}
                    for t in ('出售','确认','取消','批量强化','自动选择'))
        self.assertEqual(classify(words),'batch_organize')

    def intent(self,adb,action,page,x,y):
        adb.event({'kind':'sale_preview_intent','action':action,'page':page,'x':x,'y':y})

    @patch('e7_assistant.adb.Adb._run')
    def test_final_sale_and_enhancement_coordinates_are_blocked_before_adb(self,run):
        adb=SalePreviewAdb('adb','test')
        for action,page,x,y in [('cancel_sale','sale_confirmation',750,530),
                ('open_sale','batch_organize',750,530),('open_sale','sale_confirmation',300,95),
                ('enhance','batch_enhancement',1200,670)]:
            with self.subTest(action=action,page=page):
                self.intent(adb,action,page,x,y)
                with self.assertRaises(ValueError):
                    adb.tap(x,y)
        run.assert_not_called()

    @patch('e7_assistant.adb.Adb._run')
    def test_only_explicit_preview_intent_can_be_used_once(self,run):
        adb=SalePreviewAdb('adb','test')
        self.intent(adb,'open_sale','batch_organize',300,95)
        adb.tap(300,95)
        with self.assertRaises(ValueError):
            adb.tap(300,95)
        self.assertEqual(run.call_count,1)
        self.assertEqual(adb.preview_taps,[{'action':'open_sale','point':(300,95)}])

    @patch('e7_assistant.adb.Adb._run')
    def test_intervening_observation_invalidates_intent_and_cancel_is_left_only(self,run):
        adb=SalePreviewAdb('adb','test')
        self.intent(adb,'open_sale','batch_organize',300,95)
        adb.event({'kind':'workflow_screen'})
        with self.assertRaises(ValueError):
            adb.tap(300,95)
        run.assert_not_called()
        self.intent(adb,'cancel_sale','unknown',485,530)
        adb.tap(485,530)
        self.assertEqual(run.call_count,1)


if __name__=='__main__':
    unittest.main()
