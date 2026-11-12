from dataclasses import replace
from pathlib import Path
import tempfile
import uuid
import unittest

from e7_assistant.initial_cleanup import (CleanupConfirmation, CleanupInventory,
                                        InitialCleanupDriver, inspect_confirmation,
                                        inspect_inventory, verify_cleanup)
from e7_assistant.tasks import TaskControl
from e7_assistant.workflow_screen import Screen


def word(text, x, y, confidence=.99):
    return {'text': text, 'center': (x, y), 'confidence': confidence}


def screen(page='inventory_organize', selected=0, count=1205, gold=343327724):
    words = [word(f'{count}/1200', 1058, 106), word(f'{gold:,}', 728, 33),
             word(f'[{selected}]', 750, 105), word('快速选择', 210, 103),
             word('出售', 424, 103), word('萃取', 576, 103)]
    if page in {'extract_confirmation', 'sale_confirmation'}:
        label = '萃取' if page == 'extract_confirmation' else '出售'
        words += [word(label+'装备', 640, 179), word(label, 747, 529), word('取消', 534, 529)]
    return Screen(f'{page}-{selected}-{count}.png', page, 1280, 720, tuple(words))


class FakeNavigator:
    journal = None
    root = None

    def __init__(self, reads):
        self.directory = Path(self.root) / uuid.uuid4().hex
        self.directory.mkdir()
        self.serial = 'test-device'
        self.reads = iter(reads)
        self.taps = []
        self.navigation = []
        self.adb = self
        self.control = TaskControl()
        self.control.wait = lambda seconds: self.control.checkpoint()

    def navigate(self, target):
        self.navigation.append(target)

    def transition(self, action):
        self.navigation.append(action)
        return screen()

    def read(self):
        return next(self.reads)

    def tap(self, x, y):
        self.control.before_input()
        self.taps.append((x, y))


def confirmation_reader(s, action):
    if s.page != ('extract_confirmation' if action == 'extract' else 'sale_confirmation'):
        raise ValueError('错误弹窗')
    return CleanupConfirmation(action, s.source, 'stable')


class InitialCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        FakeNavigator.root = temporary.name

    def test_inventory_counts_include_over_capacity_and_partial_brackets(self):
        s = screen(selected=143)
        s = replace(s, words=tuple(word('[143', 750, 105) if w['center'] == (750,105) else w for w in s.words))
        found = inspect_inventory(s)
        self.assertEqual((found.count, found.capacity, found.selected, found.gold),
                         (1205, 1200, 143, 343327724))

    def test_ambiguous_low_confidence_and_modal_background_are_not_counts(self):
        s = screen()
        for bad in (replace(s, page='extract_confirmation'),
                    replace(s, words=s.words+(word('2', 755, 105, .2),)),
                    replace(s, words=tuple({**w,'text':'1O'} if w['center']==(750,105) else w for w in s.words))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inspect_inventory(bad)

    def test_selected_count_ignores_only_bracket_noise_with_numeric_consensus(self):
        from unittest.mock import patch
        s=screen(selected=220)
        s=replace(s,words=tuple({**w,'confidence':.86} if w['center']==(750,105) else w for w in s.words))
        for texts,expected in ((['[220][','[220]','220'],220),
                               (['[220]','[221]'],None),(['[220]','22O'],None),
                               (['[220]'],None)):
            details={'selected':{'accepted':False,'candidates':[
                {'text':text,'confidence':.99} for text in texts]}}
            with self.subTest(texts=texts),patch('e7_assistant.local_ocr.read_local_regions',return_value=({'selected':''},details)):
                if expected is None:
                    with self.assertRaises(ValueError):inspect_inventory(s)
                else:
                    self.assertEqual(inspect_inventory(s).selected,expected)

    def test_confirmation_hash_ignores_background_but_detects_changed_modal(self):
        from pathlib import Path
        import tempfile
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'modal.png'
            image = Image.new('RGB',(1280,720),'black')
            image.save(path)
            s = replace(screen('extract_confirmation'),source=str(path))
            first = inspect_confirmation(s,'extract')
            ImageDraw.Draw(image).rectangle((1000,80,1125,130),fill='red')
            image.save(path)
            self.assertEqual(first.digest,inspect_confirmation(s,'extract').digest)
            ImageDraw.Draw(image).rectangle((500,300,510,310),fill='red')
            image.save(path)
            self.assertNotEqual(first.digest,inspect_confirmation(s,'extract').digest)
            with self.assertRaises(ValueError):
                inspect_confirmation(s,'sell')

    def test_actual_extraction_count_can_be_less_than_quick_selection(self):
        before = CleanupInventory(1205,1200,143,100,'before')
        after = CleanupInventory(1070,1200,None,100,'after')
        self.assertEqual(verify_cleanup(before,after,'extract')['not_removed'],8)
        with self.assertRaises(ValueError):
            verify_cleanup(before,replace(after,gold=200),'sell')

    def test_tall_multirow_extract_modal_is_verified(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'modal.png'
            Image.new('RGB',(1280,720)).save(path)
            s=replace(screen('extract_confirmation'),source=str(path))
            s=replace(s,words=tuple({**w,'center':(640,123)} if w['text']=='萃取装备' else
                                   {**w,'center':(w['center'][0],584)} if w['text'] in ('萃取','取消') and w['center'][1]==529 else w
                                   for w in s.words))
            self.assertEqual(inspect_confirmation(s,'extract').action,'extract')

    def test_cleanup_waits_for_server_when_old_selection_still_visible(self):
        selected=screen(selected=2)
        modal=screen('extract_confirmation',selected=2)
        after=screen('inventory',count=1203)
        nav=FakeNavigator([selected,selected,modal,modal,selected,after,after])
        driver=InitialCleanupDriver(nav,confirmation_reader=confirmation_reader)
        self.assertEqual(driver.initial_cleanup('extract')['removed'],2)
        self.assertFalse(driver.pending)

    def test_invalid_result_does_not_count_as_success(self):
        before = CleanupInventory(1205,1200,143,100,'before')
        for after in (replace(before,selected=0), replace(before,count=1000,selected=0),
                      replace(before,count=1062,capacity=1300,selected=0),
                      replace(before,count=1062,gold=99,selected=0),
                      replace(before,count=1062,selected=1)):
            with self.subTest(after=after), self.assertRaises(ValueError):
                verify_cleanup(before,after,'extract')

    def test_extract_uses_preset_and_one_confirmation_then_checks_actual_count(self):
        selected = screen(selected=143)
        modal = screen('extract_confirmation', selected=143)
        after = screen('inventory_manage',count=1070)
        nav = FakeNavigator([selected, selected, modal, modal, modal, after, after])
        driver = InitialCleanupDriver(nav, confirmation_reader=confirmation_reader)
        result = driver.initial_cleanup()
        self.assertEqual(result['removed'],135)
        self.assertEqual(result['not_removed'],8)
        self.assertEqual(nav.taps,[(210,103),(576,103),(747,529)])
        self.assertEqual(nav.navigation,['inventory','manage','organize'])
        self.assertFalse(driver.pending)

    def test_sale_only_uses_sale_buttons_and_requires_income(self):
        selected = screen(selected=2)
        modal = screen('sale_confirmation', selected=2)
        after = screen('inventory',count=1203,gold=343337724)
        nav = FakeNavigator([selected, selected, modal, modal, after, after])
        result = InitialCleanupDriver(nav, confirmation_reader=confirmation_reader).initial_cleanup('sell')
        self.assertEqual(result['removed'],2)
        self.assertEqual(nav.taps,[(210,103),(424,103),(747,529)])

    def test_zero_selection_sends_no_disposal_input(self):
        nav = FakeNavigator([screen()])
        result = InitialCleanupDriver(nav).initial_cleanup()
        self.assertEqual(result['removed'],0)
        self.assertEqual(nav.taps,[(210,103)])

    def test_timeout_does_not_repeat_confirm_and_prevents_next_run(self):
        selected = screen(selected=143)
        modal = screen('extract_confirmation',selected=143)
        nav = FakeNavigator([selected,selected,modal,modal]+[modal]*8)
        driver = InitialCleanupDriver(nav, confirmation_reader=confirmation_reader)
        with self.assertRaises(TimeoutError):
            driver.initial_cleanup()
        with self.assertRaises(ValueError):
            driver.initial_cleanup()
        self.assertEqual(len(nav.taps),3)
        self.assertTrue(driver.pending)

    def test_wrong_action_modal_and_changed_preview_never_confirm(self):
        selected = screen(selected=143)
        for changed in (False,True):
            modal = screen('extract_confirmation' if changed else 'sale_confirmation',selected=143)
            nav = FakeNavigator([selected,selected,modal,modal])
            calls = []
            def reader(s,action):
                result = confirmation_reader(s,action)
                calls.append(result)
                return replace(result,digest=str(len(calls)))
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                InitialCleanupDriver(nav,confirmation_reader=reader).initial_cleanup()
            self.assertEqual(len(nav.taps),2)

    def test_result_mismatch_preserves_pending_without_retry(self):
        selected = screen(selected=143)
        modal = screen('extract_confirmation',selected=143)
        after = screen('inventory_manage',count=1000)
        nav = FakeNavigator([selected,selected,modal,modal,after])
        driver = InitialCleanupDriver(nav,confirmation_reader=confirmation_reader)
        with self.assertRaises(ValueError):
            driver.initial_cleanup()
        self.assertTrue(driver.pending)
        self.assertEqual(len(nav.taps),3)

    def test_existing_selection_and_selection_change_are_not_overwritten(self):
        nav = FakeNavigator([])
        nav.transition = lambda action: screen(selected=2)
        with self.assertRaises(ValueError):
            InitialCleanupDriver(nav).initial_cleanup()
        self.assertEqual(nav.taps,[])
        nav = FakeNavigator([screen(selected=143),screen(selected=142)])
        with self.assertRaises(ValueError):
            InitialCleanupDriver(nav).initial_cleanup()
        self.assertEqual(len(nav.taps),1)

    def test_input_error_leaves_outcome_unknown(self):
        selected = screen(selected=143)
        modal = screen('extract_confirmation',selected=143)
        nav = FakeNavigator([selected,selected,modal,modal])
        original = nav.tap
        def tap(x,y):
            original(x,y)
            if y == 529:
                raise OSError('ADB timeout')
        nav.tap = tap
        driver = InitialCleanupDriver(nav,confirmation_reader=confirmation_reader)
        with self.assertRaises(OSError):
            driver.initial_cleanup()
        self.assertTrue(driver.pending)
        self.assertEqual(len(nav.taps),3)

    def test_unknown_result_blocks_new_driver_and_new_run_before_navigation(self):
        selected = screen(selected=143)
        modal = screen('extract_confirmation', selected=143)
        nav = FakeNavigator([selected, selected, modal, modal] + [modal]*8)
        driver = InitialCleanupDriver(nav, confirmation_reader=confirmation_reader)
        with self.assertRaises(TimeoutError):
            driver.initial_cleanup()
        record = driver.guard.read()
        self.assertEqual(record['before']['selected'], 143)
        self.assertEqual(record['confirmation']['digest'], 'stable')
        nav.directory = nav.directory.parent/'second-run'
        nav.navigation.clear()
        nav.taps.clear()
        restarted = InitialCleanupDriver(nav, confirmation_reader=confirmation_reader)
        with self.assertRaisesRegex(ValueError, '未结算'):
            restarted.initial_cleanup('sell')
        self.assertEqual(nav.navigation, [])
        self.assertEqual(nav.taps, [])

    def test_success_releases_persistent_record(self):
        selected = screen(selected=2)
        modal = screen('extract_confirmation',selected=2)
        after = screen('inventory_manage',count=1203)
        nav = FakeNavigator([selected,selected,modal,modal,after,after])
        driver = InitialCleanupDriver(nav,confirmation_reader=confirmation_reader)
        driver.initial_cleanup()
        self.assertIsNone(driver.guard.read())
        nav.reads = iter([screen()])
        result = InitialCleanupDriver(nav).initial_cleanup()
        self.assertEqual(result['selected'], 0)

    def test_corrupt_persistent_record_blocks_all_navigation(self):
        nav = FakeNavigator([])
        driver = InitialCleanupDriver(nav)
        driver.guard.path.parent.mkdir(parents=True)
        driver.guard.path.write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '无法读取'):
            driver.initial_cleanup()
        self.assertEqual(nav.navigation, [])
        self.assertEqual(nav.taps, [])

    def test_journal_failure_after_intent_record_does_not_send_confirmation(self):
        from types import SimpleNamespace
        selected = screen(selected=2)
        modal = screen('extract_confirmation',selected=2)
        nav = FakeNavigator([selected,selected,modal,modal])
        def emit(kind, **data):
            if kind == 'cleanup_commit_intent':
                raise OSError('日志写入失败')
        nav.journal = SimpleNamespace(emit=emit)
        driver = InitialCleanupDriver(nav,confirmation_reader=confirmation_reader)
        with self.assertRaises(OSError):
            driver.initial_cleanup()
        self.assertTrue(driver.pending)
        self.assertIsNotNone(driver.guard.read())
        self.assertEqual(nav.taps, [(210,103),(576,103)])


if __name__ == '__main__':
    unittest.main()
