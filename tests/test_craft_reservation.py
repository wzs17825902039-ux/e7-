import unittest

from e7_assistant.craft_reservation import CraftReservation
from e7_assistant.tasks import Ledger,Limits


class CraftReservationTests(unittest.TestCase):
    def session(self,**kwargs):
        ledger=Ledger(Limits(gold=1000000,craft_material=2000,max_steps=kwargs.get('max_steps',5)))
        return CraftReservation(ledger,{'gold':2000000,'craft_material':5000},
                                {'gold':210000,'craft_material':400})

    def test_repeat_budget_is_reserved_but_not_reported_as_actual_material_spend(self):
        session=self.session()
        for gold in (1790000,1580000):
            session.mark_commit();session.observe_gold(gold)
        self.assertEqual(session.ledger.spent['craft_material'],0)
        self.assertFalse(session.evidence()['material_balance_observed'])
        session.settle({'gold':1580000,'craft_material':4200})
        self.assertEqual(session.ledger.spent['craft_material'],800)
        self.assertEqual(session.ledger.steps,2)

    def test_shared_budget_includes_existing_spend(self):
        session=self.session()
        session.ledger.spent['gold']=700000
        session.mark_commit()
        session.observe_gold(1790000)
        with self.assertRaises(ValueError):
            session.check_next()
        self.assertEqual(session.committed,1)

    def test_result_gold_mismatch_is_not_treated_as_success(self):
        session=self.session();session.mark_commit()
        with self.assertRaises(ValueError):
            session.observe_gold(1790001)

    def test_final_material_mismatch_records_actual_and_cannot_settle_twice(self):
        session=self.session();session.mark_commit();session.observe_gold(1790000);session.mark_commit()
        with self.assertRaises(ValueError):
            session.settle({'gold':1580000,'craft_material':4100})
        self.assertEqual(session.ledger.spent['craft_material'],900)
        self.assertEqual(session.ledger.steps,2)
        with self.assertRaises(ValueError):
            session.settle({'gold':1580000,'craft_material':4200})

    def test_step_limit_counts_each_repeat(self):
        session=self.session(max_steps=1);session.mark_commit();session.observe_gold(1790000)
        with self.assertRaises(ValueError):
            session.check_next()
