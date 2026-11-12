from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from e7_assistant.inventory_tail_vision import inspect_tail
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import Screen


class TailVisionTests(unittest.TestCase):
    def test_single_card_selection_checks_content_at_original_coordinates(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.selection_state import verify_selection_state,IncompleteSelectionState
        from copy import deepcopy
        assets=Path(__file__).resolve().parents[1]/'docs/assets'
        before,after=[inspect_inventory(inspect_screen(assets/name),ignore_levels=True)
                      for name in ('inventory-single-before.png','inventory-single-selected.png')]
        verify_selection_state(before,after,(0,0),True)
        with tempfile.TemporaryDirectory() as directory,Image.open(after['source']) as image:
            ImageDraw.Draw(image).rectangle((150,165,220,198),fill='black')
            path=Path(directory)/'changed.png';image.save(path)
            changed=deepcopy(after);changed['cards'][0]['tracking_source']=str(path)
            with self.assertRaises(IncompleteSelectionState):verify_selection_state(before,changed,(0,0),True)

    def test_single_item_real_list_has_complete_tail_and_top_anchor(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_top_vision import inspect_top,verify_top_anchor
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-single-item.png'
        screen=inspect_screen(source)
        report=inspect_inventory(screen,ignore_levels=True)
        self.assertEqual(len(report['cards']),1)
        self.assertEqual((report['tail_layout']['row'],report['tail_layout']['tail_count']),(0,1))
        head=inspect_top(screen)
        self.assertTrue(head['head_visible'])
        anchor={'method':'visible_head_then_settled','head_visible':True,
                'head_source':screen.source,'stable_source':screen.source,
                'inventory_context':report['inventory_context']}
        self.assertTrue(verify_top_anchor(anchor,report))
        from e7_assistant.selection_state import verify_selection_state,IncompleteSelectionState
        from copy import deepcopy
        verify_selection_state(report,report)
        unknown=deepcopy(report);unknown['tail_layout']['end_verified']=False
        with self.assertRaises(IncompleteSelectionState):verify_selection_state(unknown,unknown)
        with tempfile.TemporaryDirectory() as directory,Image.open(source) as image:
            changed=image.copy();ImageDraw.Draw(changed).rectangle((350,350,420,450),fill='black')
            path=Path(directory)/'changed.png';changed.save(path)
            tail=inspect_tail(replace(screen,source=str(path)))
            self.assertNotEqual(tail.get('method'),'calibrated_compact_list')

    def test_short_real_list_has_fifteen_cards_and_one_item_tail(self):
        from e7_assistant.workflow_screen import inspect_screen
        from e7_assistant.inventory_grid_vision import locate_rows
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-short-list.png'
        screen=inspect_screen(source)
        tail=inspect_tail(screen)
        self.assertTrue(tail['end_verified'])
        self.assertEqual((tail['tail_count'],tail['row_top']),(1,419))
        self.assertEqual(len(locate_rows(source,tail)),3)
        report=inspect_inventory(screen,ignore_levels=True)
        self.assertEqual(len(report['cards']),15)
        self.assertEqual(report['tail_layout']['row'],2)
        selected=inspect_screen(source.with_name('inventory-short-selected.png'))
        selected_report=inspect_inventory(selected,ignore_levels=True)
        self.assertEqual((len(selected_report['cards']),selected_report['selected_count']),(15,9))
        with tempfile.TemporaryDirectory() as directory,Image.open(source) as image:
            for box in ((350,450,420,510),(350,580,420,650)):
                changed=image.copy();ImageDraw.Draw(changed).rectangle(box,fill='black')
                path=Path(directory)/'changed.png';changed.save(path)
                result=inspect_tail(replace(screen,source=str(path)))
                self.assertNotEqual(result.get('method'),'calibrated_short_third_row')

    def setUp(self):
        self.directory = Path(__file__).resolve().parents[1]/'docs/assets/inventory-mode-2026-11-09'

    def screen(self,name='03-zero-selection-tail.png'):
        return Screen(str(self.directory/name),'inventory_batch_selection',1280,720,())

    def test_real_independent_tail_has_five_occupied_two_empty_and_bottom(self):
        for name in ('03-zero-selection-tail.png','05-one-selection-after-swipe.png'):
            with self.subTest(name=name):
                result = inspect_tail(self.screen(name))
                self.assertEqual(result['tail_count'],5)
                self.assertEqual([c['state'] for c in result['cells']],['occupied']*5+['empty']*2)
                self.assertTrue(result['end_verified'])

    def test_faded_scrollbar_preserves_tail_shape_but_does_not_prove_bottom(self):
        result = inspect_tail(self.screen('04-one-selection-tail.png'))
        self.assertEqual(result['tail_count'],5)
        self.assertFalse(result['end_verified'])

    def test_middle_and_initial_views_do_not_match_bottom_or_tail(self):
        for name in ('01-zero-selection.png','02-zero-selection-scrolled.png','06-zero-after-deselect.png'):
            with self.subTest(name=name):
                result = inspect_tail(self.screen(name))
                self.assertFalse(result['end_verified'])
                self.assertIsNone(result['tail_count'])

    def test_blank_and_corrupted_empty_cell_are_unknown_not_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'mutated.png'
            Image.new('RGB',(1280,720),'black').save(target)
            result = inspect_tail(replace(self.screen(),source=str(target)))
            self.assertTrue(all(c['state']=='unknown' for c in result['cells']))
            self.assertFalse(result['end_verified'])
            with Image.open(self.screen().source) as image:
                ImageDraw.Draw(image).rectangle((641,600,723,709),fill='black')
                image.save(target)
            result = inspect_tail(replace(self.screen(),source=str(target)))
            self.assertTrue(result['end_verified'])
            self.assertEqual(result['cells'][5]['state'],'unknown')
            self.assertIsNone(result['tail_count'])

    def test_equipment_pasted_into_empty_cell_is_not_classified_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'six.png'
            with Image.open(self.screen().source) as image:
                image.paste(image.crop((146,600,229,710)),(641,600))
                image.save(target)
            result = inspect_tail(replace(self.screen(),source=str(target)))
            self.assertEqual(result['cells'][5]['state'],'occupied')
            self.assertEqual(result['tail_count'],6)

    def test_other_pages_and_unmarked_resolution_do_not_use_fixed_templates(self):
        with self.assertRaises(ValueError):
            inspect_tail(replace(self.screen(),page='inventory'))
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'resized.png'
            with Image.open(self.screen().source) as image:
                image.resize((1661,933)).save(target)
            result = inspect_tail(replace(self.screen(),source=str(target),width=1661,height=933))
            self.assertFalse(result['end_verified'])
            self.assertEqual(result['cells'],[])

    def test_tail_equipment_is_read_but_empty_cells_are_not_ocr_candidates(self):
        words = [{'text':'批量强化(0)','confidence':1.,'center':(1115,674)}]
        for y in (214,348,481,615):
            words += [{'text':'85','confidence':1.,'center':(165,y)},
                      {'text':'85','confidence':1.,'center':(265,y)}]
        screen = replace(self.screen(),words=tuple(words))
        captured = {}
        def numbers(path,regions):
            captured.update(regions)
            return {key:'85' for key in regions}
        result = inspect_inventory(screen,numbers)
        self.assertEqual(len(result['cards']),26)
        self.assertEqual([c['column'] for c in result['cards'] if c['row']==3],list(range(5)))
        self.assertNotIn('level3_5',captured)
        self.assertNotIn('level3_6',captured)
        self.assertTrue(all(c['eligible'] for c in result['cards'][-5:]))
        self.assertTrue(result['tail_layout']['end_verified'])
        self.assertFalse(result['scan_complete'])
        unknown = inspect_inventory(screen,lambda path,regions:{})
        self.assertTrue(all(c['level'] is None and not c['eligible'] for c in unknown['cards'][-5:]))


if __name__ == '__main__':
    unittest.main()
