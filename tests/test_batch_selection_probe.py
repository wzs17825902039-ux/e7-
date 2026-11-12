import unittest
from unittest.mock import patch

from scripts.probe_batch_selection import SelectionOnlyAdb


class SelectionProbeGuardTests(unittest.TestCase):
    def test_no_resource_or_unregistered_tap_can_reach_adb(self):
        for event,point in ((None,(1120,670)),
                            ({'kind':'batch_enhance_intent'},(1120,670)),
                            ({'kind':'batch_selection_intent'},(1120,670)),
                            ({'kind':'batch_entry_intent','count':15},(1120,670)),
                            ({'kind':'batch_entry_intent','count':16},(200,250))):
            adb=SelectionOnlyAdb(serial='test')
            if event is not None:
                adb.event(event)
            with self.subTest(event=event,point=point),patch.object(adb,'_run') as run:
                with self.assertRaises(ValueError):adb.tap(*point)
                run.assert_not_called()

    def test_selection_intent_is_consumed_once(self):
        adb=SelectionOnlyAdb(serial='test')
        adb.event({'kind':'batch_selection_intent'})
        with patch.object(adb,'_run') as run:
            adb.tap(200,250)
            with self.assertRaises(ValueError):adb.tap(200,250)
        run.assert_called_once_with(['shell','input','tap','200','250'],device=True)
        self.assertEqual(len(adb.selection_inputs),1)

    def test_only_full_batch_entry_intent_authorizes_entry_region(self):
        adb=SelectionOnlyAdb(serial='test')
        adb.event({'kind':'batch_entry_intent','count':16})
        with patch.object(adb,'_run') as run:
            adb.tap(1120,670)
        run.assert_called_once_with(['shell','input','tap','1120','670'],device=True)
        self.assertEqual(adb.selection_inputs[0]['kind'],'batch_entry_intent')

    def test_preview_must_be_explicit_and_matches_registered_stage_and_point(self):
        event={'kind':'batch_stage_preview_intent','target':3,'x':100,'y':675}
        for enabled,target,point in ((False,3,(100,675)),(True,6,(100,675)),
                                     (True,3,(1120,675)),(True,3,(101,675))):
            adb=SelectionOnlyAdb(serial='test',allow_preview=enabled)
            adb.event({**event,'target':target})
            with self.subTest(enabled=enabled,target=target,point=point),patch.object(adb,'_run') as run:
                with self.assertRaises(ValueError):adb.tap(*point)
                run.assert_not_called()

    def test_preview_never_authorizes_commit_or_a_second_input(self):
        adb=SelectionOnlyAdb(serial='test',allow_preview=True)
        adb.event({'kind':'batch_stage_preview_intent','target':3,'x':100,'y':675})
        with patch.object(adb,'_run') as run:
            adb.tap(100,675)
            with self.assertRaises(ValueError):adb.tap(100,675)
            adb.event({'kind':'batch_enhance_commit_intent','target':3})
            with self.assertRaises(ValueError):adb.tap(1210,675)
        run.assert_called_once()

    def test_sale_layout_preview_can_never_confirm_or_reuse_intent(self):
        for enabled,action,page,point in ((False,'cancel_sale','sale_confirmation',(500,528)),
                    (True,'confirm_sale','sale_confirmation',(747,528)),
                    (True,'cancel_sale','sale_confirmation',(747,528)),
                    (True,'open_sale','sale_confirmation',(300,95)),
                    (True,'toggle','batch_organize',(100,200))):
            adb=SelectionOnlyAdb(serial='test',allow_sale_layouts=enabled)
            adb.event({'kind':'sale_layout_preview_intent','action':action,'page':page,
                       'x':point[0],'y':point[1]})
            with self.subTest(action=action,enabled=enabled,point=point),patch.object(adb,'_run') as run:
                with self.assertRaises(ValueError):adb.tap(*point)
                run.assert_not_called()
        adb=SelectionOnlyAdb(serial='test',allow_sale_layouts=True)
        adb.event({'kind':'sale_layout_preview_intent','action':'cancel_sale',
                   'page':'sale_confirmation','x':500,'y':528})
        with patch.object(adb,'_run') as run:
            adb.tap(500,528)
            with self.assertRaises(ValueError):adb.tap(500,528)
            run.assert_called_once()


if __name__=='__main__':
    unittest.main()
