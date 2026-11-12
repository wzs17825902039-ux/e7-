from dataclasses import replace
import unittest

from e7_assistant.enhancement_statistics import EnhancementStatistics
from e7_assistant.rules import Equipment


class EnhancementStatisticsTests(unittest.TestCase):
    def item(self,speed,level=15):
        return Equipment('same-visual-id','red',85,level,'helmet',
                         {'speed':speed,'hp_pct':8,'atk_pct':8,'crit':4},True,True)

    def test_exclusive_speed_bins_and_total(self):
        statistics=EnhancementStatistics()
        for key,speed in enumerate((13,14,15,16,20)):
            statistics.record(key,self.item(4,12),self.item(speed))
        self.assertEqual(statistics.snapshot(),{'speed14':1,'speed15':1,'speed16plus':2,'total14plus':4})

    def test_repeated_result_and_lock_do_not_count_again(self):
        statistics=EnhancementStatistics()
        self.assertTrue(statistics.record((1,'0'),self.item(10,12),self.item(16)))
        self.assertFalse(statistics.record((1,'0'),self.item(10,12),self.item(16)))
        self.assertFalse(statistics.record((1,'0'),self.item(16),self.item(16)))
        self.assertEqual(statistics.snapshot()['total14plus'],1)
        self.assertTrue(statistics.record((2,'0'),self.item(10,12),self.item(16)))
        self.assertEqual(statistics.snapshot()['total14plus'],2)

    def test_existing_completed_intermediate_and_unconfirmed_items_are_excluded(self):
        statistics=EnhancementStatistics()
        self.assertFalse(statistics.record('existing',self.item(16),self.item(16)))
        self.assertFalse(statistics.record('intermediate',self.item(10,9),self.item(16,12)))
        self.assertFalse(statistics.record('uncertain',self.item(10,12),replace(self.item(16),recognition_ok=False)))
        self.assertFalse(statistics.record('other',self.item(10,12),replace(self.item(16),equipment_id='different')))
        self.assertEqual(statistics.snapshot()['total14plus'],0)

    def test_new_task_starts_empty_and_snapshot_cannot_mutate_counts(self):
        statistics=EnhancementStatistics()
        statistics.record('first',self.item(10,12),self.item(14))
        snapshot=statistics.snapshot();snapshot['speed14']=99
        self.assertEqual(statistics.snapshot()['speed14'],1)
        self.assertEqual(EnhancementStatistics().snapshot()['total14plus'],0)


if __name__=='__main__':unittest.main()
