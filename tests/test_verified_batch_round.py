from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.run_verified_batch_round import verify_authorized_selection,AuthorizedRoundDriver


class VerifiedRoundTests(unittest.TestCase):
    def test_authorization_requires_same_sixteen_in_order(self):
        approved={'selected_count':16,'registered':[
            {'fingerprint':str(i),'main':['生命值','540']} for i in range(16)]}
        fresh=deepcopy(approved)
        for card in fresh['registered']:card['main']=tuple(card['main'])
        verify_authorized_selection(approved,fresh)
        for case in ('count','order','identity','main'):
            current=deepcopy(approved)
            if case=='count':current['selected_count']=15
            if case=='order':current['registered'].reverse()
            if case=='identity':current['registered'][0]['fingerprint']='different'
            if case=='main':current['registered'][0]['main']=['生命值','100']
            with self.subTest(case=case),self.assertRaises(ValueError):
                verify_authorized_selection(approved,current)

    def test_authorized_round_rejects_disposal(self):
        driver=AuthorizedRoundDriver(None,approved_cost={})
        with self.assertRaises(ValueError):driver.dispose_batch([],set(),set(),'sell')

    def test_changed_first_preview_cannot_be_committed(self):
        driver=AuthorizedRoundDriver(None,approved_cost={'gold':236800})
        with patch('e7_assistant.batch_enhancement.BatchEnhancementDriver.prepare_enhancement',
                   return_value=SimpleNamespace(cost={'gold':236801})):
            with self.assertRaises(ValueError):driver.prepare_enhancement([],3)
        self.assertTrue(driver.first)


if __name__=='__main__':unittest.main()
