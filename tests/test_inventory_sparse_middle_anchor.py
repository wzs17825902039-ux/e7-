from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.inventory_vision import inspect_inventory, InventoryObservationIncomplete
from e7_assistant.workflow_screen import inspect_screen


class SparseMiddleAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/72-single-middle-anchor-with-main-grid.png'
        cls.screen=inspect_screen(source)

    def test_one_middle_level_and_four_main_numbers_recover_all_local_levels(self):
        report=inspect_inventory(self.screen)
        self.assertEqual(len(report['cards']),21)
        self.assertTrue(all(c['level']==85 and c['known'] and c['enhancement']==0 for c in report['cards']))

    def test_missing_main_grid_does_not_propose_leading_row(self):
        words=tuple(w for w in self.screen.words if not (180<w['center'][1]<310))
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(replace(self.screen,words=words))

    def test_rejected_local_level_never_inherits_grid_level(self):
        def rejected(path,boxes):
            return {key:('' if key.endswith('_3') else '85') for key in boxes}
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(self.screen,read_numbers=rejected)

    def test_three_strong_columns_and_one_weak_column_are_insufficient(self):
        words=tuple({**w,'confidence':.94} if 180<w['center'][0]<200 and 280<w['center'][1]<305 else w
                    for w in self.screen.words)
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(replace(self.screen,words=words))

    def test_actual_missing_anchor_frame_uses_independent_levels_not_empty_fallback(self):
        source=Path(self.screen.source).with_name('75-missing-grid-requires-reread.png')
        report=inspect_inventory(inspect_screen(source))
        self.assertEqual(len(report['cards']),21)
        self.assertTrue(all(c['level']==85 and c['known'] for c in report['cards']))

    def test_missing_anchor_without_wide_numeric_rows_is_still_incomplete(self):
        source=Path(self.screen.source).with_name('75-missing-grid-requires-reread.png')
        screen=inspect_screen(source)
        words=tuple(w for w in screen.words if not (280<w['center'][1]<310
                    and (w['center'][0]<200 or w['center'][0]>750)))
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(replace(screen,words=words))

    def test_only_bottom_anchor_requires_both_leading_numeric_rows_and_local_levels(self):
        source=Path(self.screen.source).with_name('77-bottom-anchor-two-leading-rows.png')
        screen=inspect_screen(source)
        report=inspect_inventory(screen)
        self.assertEqual(len(report['cards']),21)
        self.assertTrue(all(c['known'] and c['level']==85 for c in report['cards']))
        # 只借网格定位；最上方没有宽网格，或任一等级拒识，都不得补行。
        missing=tuple(w for w in screen.words if not (w['center'][0]>400 and 280<w['center'][1]<305))
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(replace(screen,words=missing))
        def rejected(path,boxes):
            return {key:('' if key.endswith('_3') else '85') for key in boxes}
        with self.assertRaises(InventoryObservationIncomplete):
            inspect_inventory(screen,read_numbers=rejected)

    def test_one_sparse_leading_row_still_requires_all_fourteen_local_grades(self):
        source=Path(self.screen.source).with_name('78-bottom-anchor-sparse-leading-row.png')
        screen=inspect_screen(source)
        report=inspect_inventory(screen)
        self.assertEqual(len(report['cards']),21)
        self.assertTrue(all(card['known'] and card['level']==85 for card in report['cards']))

    def test_default_mode_uses_frames_without_level_or_attribute_text(self):
        source=Path(self.screen.source).with_name('81-three-sparse-numeric-rows.png')
        screen=inspect_screen(source)
        words=tuple(w for w in screen.words if not (130<w['center'][0]<840 and 140<w['center'][1]<710))
        with patch('e7_assistant.inventory_vision._read_levels',side_effect=AssertionError('不能读取等级')):
            report=inspect_inventory(replace(screen,words=words),ignore_levels=True)
        self.assertEqual(len(report['cards']),21)
        self.assertTrue(all(card['known'] and card['level'] is None for card in report['cards']))
        self.assertEqual(report['level_scope'],'ignored')
        import tempfile
        from PIL import Image,ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            damaged=Path(directory)/'damaged.png'
            with Image.open(source) as image:
                ImageDraw.Draw(image).rectangle((145,190,237,312),fill=(0,0,0))
                image.save(damaged)
            with self.assertRaises(InventoryObservationIncomplete):
                inspect_inventory(replace(screen,source=str(damaged)),ignore_levels=True)

    def test_selected_border_does_not_shift_only_one_identity_crop(self):
        from e7_assistant.batch_selection import BatchSelectionDriver
        folder=Path(self.screen.source).parent
        before=inspect_inventory(inspect_screen(folder/'82-grid-before-eighth-selection.png'),ignore_levels=True)
        after=inspect_inventory(inspect_screen(folder/'83-grid-after-eighth-selection.png'),ignore_levels=True)
        BatchSelectionDriver._verify_click(before,after,(1,0))

    def test_three_contour_anchors_still_require_all_seven_card_borders(self):
        import tempfile
        from PIL import Image,ImageDraw
        from e7_assistant.inventory_grid_vision import locate_rows
        source=Path(self.screen.source).with_name('84-three-contour-seven-full-borders.png')
        self.assertEqual(locate_rows(source,{}),[256,428,600])
        with tempfile.TemporaryDirectory() as directory:
            damaged=Path(directory)/'damaged.png'
            with Image.open(source) as image:
                ImageDraw.Draw(image).rectangle((732,220,760,260),fill=(0,0,0))
                image.save(damaged)
            with self.assertRaises(ValueError):
                locate_rows(damaged,{})

    def test_nested_contours_do_not_give_one_column_multiple_votes(self):
        from e7_assistant.inventory_grid_vision import locate_rows
        source=Path(self.screen.source).with_name('85-nested-card-contours.png')
        self.assertEqual(locate_rows(source,{}),[259,431,603])

    def test_new_helmets_with_n_marker_keep_all_three_rows(self):
        from e7_assistant.inventory_grid_vision import locate_rows
        source=Path(__file__).resolve().parents[1]/'runs/cleanup-workflow-resume-7bd3f1ce/workflow-0015.png'
        self.assertEqual(locate_rows(source,{}),[207,379,551])

    def test_selected_yellow_border_above_edge_anchor_does_not_shift_row(self):
        from e7_assistant.inventory_grid_vision import locate_rows
        source=Path(__file__).resolve().parents[1]/'runs/pending-sale-resume-97e11d10/workflow-0117.png'
        self.assertEqual(locate_rows(source,{}),[208,380,552])


if __name__=='__main__':
    unittest.main()
