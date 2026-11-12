from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from PIL import Image,ImageChops
from e7_assistant.selection_state import verify_selection_state,IncompleteSelectionState
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.batch_selection import BatchSelectionDriver

ROOT=Path(__file__).resolve().parents[1]


class SelectionStateTests(unittest.TestCase):
    def test_actual_single_item_tail_half_pixel_settling_before_input(self):
        from e7_assistant.workflow_screen import inspect_selection_screen
        reports=[inspect_inventory(inspect_selection_screen(
            ROOT/'runs/desktop-d6115ab0fdd1'/f'workflow-{name}.png'),ignore_levels=True)
            for name in ('0975','0979')]
        with self.assertRaises(IncompleteSelectionState):verify_selection_state(*reports)
        for offset in ((0,.75),(1,0),(0,2)):
            with self.subTest(offset=offset),patch('e7_assistant.selection_state.inspect_tracking',
                    return_value={'matched':True,'offset':offset}):
                with self.assertRaises(IncompleteSelectionState):verify_selection_state(*reports)

    def test_top_settling_registers_consecutive_stable_frames_without_input(self):
        from e7_assistant.workflow_screen import inspect_selection_screen
        reports=[inspect_inventory(inspect_selection_screen(
            ROOT/'runs/desktop-5a1fefde7613'/f'workflow-{name}.png'),ignore_levels=True)
            for name in ('0356','0359','0360')]
        driver=BatchSelectionDriver.__new__(BatchSelectionDriver)
        driver.navigator=SimpleNamespace(control=SimpleNamespace(checkpoint=Mock(),wait=Mock()),adb=Mock())
        driver._read_screen=Mock(side_effect=reports[1:])
        driver.reader=lambda screen:screen
        self.assertIs(driver.settle_top_snapshot(reports[0]),reports[2])
        driver.navigator.adb.tap.assert_not_called()
        driver.navigator.adb.swipe.assert_not_called()

    @classmethod
    def setUpClass(cls):
        cls.cases=[]
        samples=[
            ('full-workflow-ea1671cf','0034','0035',(1,0),True),
            ('full-workflow-ae2170a0','0124','0128',(2,2),True),
            ('full-workflow-1ea7be17','0070','0074',(2,3),True),
            ('full-workflow-96fd338d','0139','0140',(2,0),True),
            ('full-workflow-040c60ca','0065','0069',(2,6),False),
            ('full-workflow-65a501ec','0021','0025',(0,3),True),
            ('full-workflow-2bb91d15','0028','0029',None,True)]
        for folder,first,last,target,selected in samples:
            frames=[inspect_inventory(inspect_screen(ROOT/'runs'/folder/f'workflow-{name}.png'),ignore_levels=True)
                    for name in (first,last)]
            cls.cases.append((*frames,target,selected))

    def test_real_failure_family_uses_native_selection_state_and_stationary_rows(self):
        for before,after,target,selected in self.cases:
            with self.subTest(image=after['source']):verify_selection_state(before,after,target,selected)

    def test_count_ticks_fields_context_and_missing_evidence_still_reject(self):
        before,after,target,selected=self.cases[-2]
        for case in ('count','tick','rarity','stage','context','missing','geometry'):
            changed=deepcopy(after)
            if case=='count':changed['selected_count']+=1
            if case=='tick':changed['cards'][1]['selected']=not changed['cards'][1]['selected']
            if case=='rarity':changed['cards'][1]['rarity']='purple'
            if case=='stage':changed['cards'][1]['enhancement']=15
            if case=='context':changed['inventory_context']=('0/1200','最大强化')
            if case=='missing':changed['cards'][1]['enhancement']=None
            if case=='geometry':changed['cards'][1]['center']=(287,100)
            with self.subTest(case=case),self.assertRaises(ValueError):
                verify_selection_state(before,changed,target,selected)

    def test_actual_list_translation_is_not_stationary_even_when_fields_and_ticks_match(self):
        before,after,target,selected=self.cases[-2]
        with TemporaryDirectory() as folder:
            output=Path(folder)/'moved.png';changed=deepcopy(after)
            with Image.open(after['source']) as image:
                image=image.convert('RGB');box=(140,145,830,605)
                image.paste(ImageChops.offset(image.crop(box),0,2),box);image.save(output)
            for card in changed['cards']:card['tracking_source']=str(output)
            with self.assertRaises(IncompleteSelectionState):verify_selection_state(before,changed,target,selected)

    def test_production_selection_only_driver_routes_to_new_state_checker(self):
        before,after,target,selected=self.cases[-2]
        driver=BatchSelectionDriver.__new__(BatchSelectionDriver)
        driver.defer_details=True;driver.native_selection_state=True;driver.observe=Mock(return_value=after)
        driver._verify_click=Mock(side_effect=AssertionError('旧逐卡像素路径不应调用'))
        driver.navigator=SimpleNamespace(journal=None)
        self.assertIs(driver._observe_click(before,target,selected),after)
        driver._verify_click.assert_not_called()
