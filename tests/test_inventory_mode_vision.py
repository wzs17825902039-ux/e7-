from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from e7_assistant.inventory_mode_vision import inspect_zero_selection
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


class InventoryModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).resolve().parents[1]/'docs/assets/inventory-mode-2026-11-09/01-zero-selection.png'
        cls.screen = inspect_screen(cls.source)

    def test_real_zero_selection_mode_uses_text_and_graphics(self):
        self.assertEqual(self.screen.page,'inventory_batch_selection_empty')
        evidence = inspect_zero_selection(self.source,self.screen.words)
        self.assertEqual(evidence['selected_count'],0)
        self.assertGreaterEqual(evidence['all_tab_match'],.95)
        self.assertTrue(evidence['empty_detail_confirmed'])

    def test_unknown_tab_or_visible_footer_button_cannot_be_zero_mode(self):
        for box,color in (((143,90,231,145),'black'),((1005,640,1220,710),(20,100,20))):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'mutated.png'
                with Image.open(self.source) as image:
                    ImageDraw.Draw(image).rectangle(box,fill=color)
                    image.save(path)
                with self.subTest(box=box),self.assertRaises(ValueError):
                    inspect_zero_selection(path,self.screen.words)

    def test_missing_low_confidence_or_conflicting_mode_text_rejects_zero(self):
        words = self.screen.words
        for changed in (tuple(w for w in words if w['text']!='未选择道具。'),
                        tuple({**w,'confidence':.5} if w['text']=='取消' else w for w in words),
                        words+({'text':'快速选择','confidence':.99,'center':(210,103)},),
                        words+({'text':'批量强化(1)','confidence':.99,'center':(1115,674)},)):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                inspect_zero_selection(self.source,changed)

    def test_zero_mode_does_not_silently_drop_single_anchor_middle_row(self):
        # 实图中第二行只被整页OCR读出一个85，逐格等级仍应逐件检查。
        report = inspect_inventory(self.screen,lambda path,boxes:{key:'85' for key in boxes})
        self.assertEqual(len(report['cards']),21)
        self.assertEqual(report['selected_count'],0)
        self.assertEqual(sorted({c['row'] for c in report['cards']}),[0,1,2])
        self.assertFalse(report['scan_complete'])

    def test_missing_middle_row_anchor_rejects_instead_of_skipping_row(self):
        # 删除该行全部定位证据，包括现在可用的等级/图案合并文本。
        words = tuple(w for w in self.screen.words
                      if not (145<w['center'][0]<800 and 290<w['center'][1]<320))
        with self.assertRaisesRegex(ValueError,'间断'):
            inspect_inventory(replace(self.screen,words=words),lambda path,boxes:{})

    def test_missing_first_full_row_does_not_start_from_second_row(self):
        words = tuple(w for w in self.screen.words
                      if not (145<w['center'][0]<800 and 150<w['center'][1]<190))
        with self.assertRaisesRegex(ValueError,'顶部可见行'):
            inspect_inventory(replace(self.screen,words=words),lambda path,boxes:{})

    def test_missing_middle_row_requires_every_local_level_not_inferred_numbers(self):
        words=tuple(w for w in self.screen.words
                    if not (145<w['center'][0]<800 and 290<w['center'][1]<320))
        missing=replace(self.screen,words=words)
        for bad in ('','5','75'):
            def reader(path,boxes):
                return {k:(bad if k=='level_anchor_3' else '85') for k in boxes}
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'间断'):
                inspect_inventory(missing,reader)
        report=inspect_inventory(missing,lambda path,boxes:{k:'85' for k in boxes})
        self.assertEqual(len(report['cards']),21)
        self.assertEqual(sorted({c['row'] for c in report['cards']}),[0,1,2])

    def test_actual_full_image_missing_row_recovers_from_seven_local_reads(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/39-missing-middle-row.png'
        screen=inspect_screen(source)
        self.assertFalse(any(w['text'] in {'85','88','90'} and 305<w['center'][1]<335 for w in screen.words))
        report=inspect_inventory(screen)
        self.assertEqual(len(report['cards']),21)
        middle=[c for c in report['cards'] if c['row']==1]
        self.assertEqual(len(middle),7)
        self.assertTrue(all(c['level']==85 and c['known'] and not c['selected'] for c in middle))
        self.assertFalse(report['scan_complete'])

    def test_trailing_missing_row_requires_all_seven_levels(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/40-missing-trailing-row.png'
        screen=inspect_screen(source)
        report=inspect_inventory(screen)
        self.assertEqual(len(report['cards']),21)
        self.assertTrue(all(c['known'] and c['level']==85 for c in report['cards'][14:]))
        for bad in ('','5','75'):
            def reader(path,boxes):
                return {k:(bad if k=='level_trailing_anchor_3' else '85') for k in boxes}
            with self.subTest(bad=bad):
                rejected=inspect_inventory(screen,reader)
                self.assertEqual(len(rejected['cards']),14)
                self.assertFalse(rejected['scan_complete'])

    def test_actual_top_missing_row_recovers_only_with_seven_local_levels(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/46-top-row-missing.png'
        screen=inspect_screen(source)
        report=inspect_inventory(screen)
        self.assertEqual(len(report['cards']),21)
        first=report['cards'][:7]
        self.assertTrue(all(c['level']==85 and c['known'] and not c['selected'] for c in first))
        self.assertEqual([c['column'] for c in first],list(range(7)))
        self.assertFalse(report['scan_complete'])

    def test_single_anchor_real_pair_recovers_two_rows_and_verifies_overlap(self):
        from e7_assistant.inventory_scan import InventoryTraversal
        folder=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10'
        before=inspect_inventory(inspect_screen(folder/'47-single-anchor-before.png'))
        after=inspect_inventory(inspect_screen(folder/'48-single-anchor-after.png'))
        self.assertEqual(len(after['cards']),21)
        self.assertTrue(all(c['known'] and c['level']==85 and c['selected'] is False for c in after['cards']))
        traversal=InventoryTraversal()
        traversal.start(before)
        self.assertEqual(traversal.advance(before,after),1)
        self.assertEqual(traversal.covered_rows,4)
        self.assertFalse(traversal.end_verified)

    def test_single_anchor_recovery_requires_every_level_in_each_added_row(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/48-single-anchor-after.png'
        screen=inspect_screen(source)
        for row in (1,2):
            for col in range(7):
                for bad in ('','5','75'):
                    def reader(path,boxes):
                        return {k:(bad if k==f'level_single_anchor_{row}_{col}' else '85') for k in boxes}
                    with self.subTest(row=row,col=col,bad=bad),self.assertRaisesRegex(ValueError,'单行定位'):
                        inspect_inventory(screen,reader)

    def test_top_missing_row_never_fills_one_unknown_or_wrong_level(self):
        source=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/46-top-row-missing.png'
        screen=inspect_screen(source)
        for bad in ('','5','75'):
            def reader(path,boxes):
                return {k:(bad if k=='level_leading_anchor_3' else '85') for k in boxes}
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'顶部可见行'):
                inspect_inventory(screen,reader)

    def test_top_recovery_does_not_crop_without_two_valid_complete_row_positions(self):
        words=tuple(w for w in self.screen.words
                    if not (140<w['center'][0]<830 and 140<w['center'][1]<620))
        def forbidden(path,boxes):
            self.fail('不完整定位证据不能提出局部裁切或补行')
        for positions in ((495,), (300,445), (400,590)):
            anchors=tuple({'text':'85','confidence':.99,'center':(166,y)} for y in positions)
            with self.subTest(positions=positions),self.assertRaisesRegex(ValueError,'顶部可见行'):
                inspect_inventory(replace(self.screen,words=words+anchors),forbidden)


if __name__ == '__main__':
    unittest.main()
