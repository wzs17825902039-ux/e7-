from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.tasks import TaskControl,Cancelled


def snapshot():
    return {'source':'frame.png','page':'inventory_batch_selection_empty','selected_count':0,
            'inventory_context':('1049/1200','获得'),'cards':[
                {'row':0,'column':0,'center':(188,240),'tracking_box':(153,190,226,288),
                 'tracking_source':'frame.png','identity_vector':[1.,0.],
                 'level':85,'rarity':'purple','enhancement':0,'selected':False,
                 'known':True,'eligible':True}]}


class ObservationRetryTests(unittest.TestCase):
    def driver(self,frames):
        self.reads=0
        self.inputs=[]
        self.events=[]
        control=TaskControl()
        control.wait=lambda seconds:control.checkpoint()
        def read():
            self.reads+=1
            return deepcopy(frames[min(self.reads-1,len(frames)-1)])
        nav=SimpleNamespace(read=read,control=control,adb=SimpleNamespace(tap=self.inputs.append),
                            journal=SimpleNamespace(emit=lambda kind,**data:self.events.append((kind,data))))
        return BatchSelectionDriver(nav,reader=lambda frame:frame)

    def missing(self):
        result=snapshot()
        result['cards'][0].update(rarity=None,known=False,eligible=False)
        return result

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_missing_field_requires_new_complete_observation_without_any_input(self,proof):
        before=snapshot()
        driver=self.driver([self.missing(),before])
        result=driver.observe_unchanged(before)
        self.assertEqual(self.reads,2)
        self.assertEqual(result,before)
        self.assertEqual(self.inputs,[])
        self.assertEqual(len(self.events),1)

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_persistent_missing_field_stops_after_four_read_only_attempts(self,proof):
        driver=self.driver([self.missing()])
        with self.assertRaises(ValueError):
            driver.observe_unchanged(snapshot())
        self.assertEqual(self.reads,4)
        self.assertEqual(len(self.events),3)
        self.assertEqual(self.inputs,[])

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_positive_changes_and_nonfinite_image_evidence_never_trigger_retry(self,proof):
        for card_change,report_change in [({'level':90},{}),({'selected':True},{}),
                ({'enhancement':3},{}),({}, {'selected_count':1}),
                ({'identity_vector':[float('nan'),0.]},{}),
                ({'center':(188,242)},{}),({}, {'inventory_context':('1050/1200','获得')})]:
            with self.subTest(card=card_change,report=report_change):
                changed=self.missing()
                changed.update(report_change)
                changed['cards'][0].update(card_change)
                driver=self.driver([changed,snapshot()])
                with self.assertRaises(ValueError):
                    driver.observe_unchanged(snapshot())
                self.assertEqual(self.reads,1)
                self.assertEqual(self.inputs,[])
                self.assertEqual(self.events,[])

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':False})
    def test_missing_value_without_full_card_proof_stops_immediately(self,proof):
        driver=self.driver([self.missing(),snapshot()])
        with self.assertRaises(ValueError):
            driver.observe_unchanged(snapshot())
        self.assertEqual(self.reads,1)
        self.assertEqual(self.inputs,[])

    @patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True})
    def test_stop_during_read_retry_prevents_more_reads(self,proof):
        driver=self.driver([self.missing(),snapshot()])
        driver.navigator.control.wait=lambda seconds:driver.navigator.control.stop()
        with self.assertRaises(Cancelled):
            driver.observe_unchanged(snapshot())
        self.assertEqual(self.reads,1)
        self.assertEqual(self.inputs,[])


if __name__=='__main__':
    unittest.main()
