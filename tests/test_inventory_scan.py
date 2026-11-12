from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
import unittest

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.inventory_scan import InventoryTraversal
from e7_assistant.rules import Equipment
from e7_assistant.tasks import TaskControl


def row(index, local=None):
    local = index if local is None else local
    vector = [float(i == index) for i in range(8)]
    return [{'row':local,'column':col,'level':85,'enhancement':15,'rarity':'purple',
             'selected':False,'identity_vector':vector,'signature':str(index),
             'center':(160+col*100,200+local*130),'eligible':False,'known':True}
            for col in range(7)]


def report(indices, count=0):
    return {'source':'fake.png','page':'inventory_batch_selection','selected_count':count,
            'cards':[card for local,index in enumerate(indices) for card in row(index,local)],
            'scan_complete':False}


class TraversalTests(unittest.TestCase):
    def test_unique_two_row_overlap_tracks_relative_coverage(self):
        traversal = InventoryTraversal()
        traversal.start(report([0,1,2]))
        self.assertEqual(traversal.advance(report([0,1,2]),report([1,2,3])),1)
        self.assertEqual(traversal.evidence()['covered_full_rows'],4)
        self.assertFalse(traversal.evidence()['top_verified'])
        self.assertFalse(traversal.evidence()['end_verified'])

    def test_stationary_or_skipped_pages_do_not_prove_end(self):
        for indices in ([0,1,2],[2,3,4],[3,4,5]):
            with self.subTest(indices=indices),self.assertRaises(ValueError):
                InventoryTraversal().advance(report([0,1,2]),report(indices))

    def test_identical_rows_are_ambiguous_not_unique_ids(self):
        with self.assertRaisesRegex(ValueError,'不唯一'):
            InventoryTraversal().advance(report([0,0,0]),report([0,0,0]))

    def test_verified_partial_tail_records_bottom_without_claiming_top(self):
        tail = report([1,2,3])
        tail['cards'] = tail['cards'][:-2]
        tail['tail_layout'] = {'end_verified':True,'tail_count':5,'row':2}
        traversal = InventoryTraversal()
        traversal.start(report([0,1,2]))
        self.assertEqual(traversal.advance(report([0,1,2]),tail),1)
        evidence = traversal.evidence()
        self.assertTrue(evidence['end_verified'])
        self.assertFalse(evidence['top_verified'])
        self.assertTrue(evidence['last_row_partial'])
        self.assertEqual(evidence['covered_full_rows'],3)

    def test_scrollbar_bottom_without_last_row_does_not_prove_coverage(self):
        tail = report([1,2,3])
        tail['tail_layout'] = {'end_verified':True,'tail_count':5,'row':None}
        traversal = InventoryTraversal()
        traversal.start(tail)
        self.assertFalse(traversal.end_verified)

    def test_partial_rows_and_selection_change_reject_alignment(self):
        before = report([0,1,2])
        for after in (report([1,2,3],1),report([1,2,3])):
            if after['selected_count'] == 0:
                after['cards'].pop()
            with self.assertRaises(ValueError):
                InventoryTraversal().advance(before,after)

    def test_sort_or_inventory_count_change_rejects_alignment(self):
        before,after = report([0,1,2]),report([1,2,3])
        before['inventory_context'] = ('获得','1062/1200')
        after['inventory_context'] = ('最大强化','1062/1200')
        with self.assertRaises(ValueError):
            InventoryTraversal().advance(before,after)

    def test_unknown_or_nan_evidence_does_not_match_rows(self):
        for value in (None,float('nan')):
            before,after = report([0,1,2]),report([1,2,3])
            for card in after['cards'][:14]:
                if value is None:
                    card['level'] = None
                else:
                    card['identity_vector'] = [value]*8
            with self.assertRaises(ValueError):
                InventoryTraversal().advance(before,after)


class PaginatedSelectionTests(unittest.TestCase):
    def anchored_driver(self,eligible=(),visible_head=True):
        driver=self.driver(eligible)
        read=driver.navigator.read
        swipe=driver.navigator.adb.swipe
        context=('35/1200','获得')
        def contextual_read():
            current=read()
            current['inventory_context']=context
            for card in current['cards']:
                card['center']=(card['center'][0],card['center'][1]+11)
            if self.offset==2:
                current['cards']=current['cards'][:-2]
                current['tail_layout']={'end_verified':True,'tail_count':5,'row':2}
            return current
        def rewind_or_advance(*args):
            if args[3]>args[1]:
                self.swipes.append(args)
                self.offset=0
            else:
                swipe(*args)
        driver.navigator.read=contextual_read
        # 此处导航器返回已解析的模拟报告；真实导航快照由独立截图回归覆盖。
        driver.navigation_reader=lambda screen:screen
        driver.navigator.adb.swipe=rewind_or_advance
        driver.top_reader=lambda screen:{'head_visible':visible_head,'source':screen['source'],
                                         'inventory_context':context}
        return driver

    def test_top_anchor_and_verified_overlap_to_tail_allow_small_batch(self):
        driver=self.anchored_driver([(3,0),(4,0)])
        result=driver.collect_pages(max_pages=5,start_at_top=True)
        self.assertEqual(result['selected_count'],2)
        self.assertTrue(result['scan_complete'])
        self.assertTrue(result['scan_evidence']['top_verified'])
        self.assertTrue(result['scan_evidence']['end_verified'])
        self.assertEqual(result['selection_status'],'exhausted')
        self.assertEqual(len(self.swipes),3)
        self.assertEqual(self.details,['3:0','4:0'])

    def test_no_candidates_can_be_exhausted_only_after_anchored_complete_scan(self):
        driver=self.anchored_driver()
        result=driver.collect_pages(max_pages=5,start_at_top=True)
        self.assertTrue(result['scan_complete'])
        self.assertEqual(result['selected_count'],0)
        self.assertEqual(self.taps,[])

    def test_top_alone_and_page_budget_do_not_claim_complete(self):
        driver=self.anchored_driver()
        result=driver.collect_pages(max_pages=1,start_at_top=True)
        self.assertTrue(result['scan_evidence']['top_verified'])
        self.assertFalse(result['scan_complete'])
        self.assertEqual(len(self.swipes),1)

    def test_stationary_rewind_without_head_proof_stops_at_limit(self):
        driver=self.anchored_driver(visible_head=False)
        with self.assertRaisesRegex(ValueError,'未获得滚动条顶部证据'):
            driver.collect_pages(max_pages=2,start_at_top=True)
        self.assertEqual(len(self.swipes),2)
        self.assertEqual(self.taps,[])

    def test_rewind_detects_context_change_before_selection(self):
        driver=self.anchored_driver()
        driver.top_reader=lambda screen:{'head_visible':True,'source':screen['source'],
                                         'inventory_context':('99/1200','获得')}
        with self.assertRaisesRegex(ValueError,'排序或背包数量变化'):
            driver.collect_pages(max_pages=3,start_at_top=True)
        self.assertEqual(self.taps,[])

    def driver(self, eligible, excluded=(), no_move=False):
        self.all_rows = [row(i,0) for i in range(5)]
        for r,c in eligible:
            self.all_rows[r][c].update(enhancement=0,eligible=True)
        self.offset = 0
        self.taps,self.swipes,self.details = [],[],[]
        control = TaskControl()
        control.wait = lambda seconds:control.checkpoint()
        def read():
            result = report([],sum(c['selected'] for group in self.all_rows for c in group))
            for local,group in enumerate(self.all_rows[self.offset:self.offset+3]):
                for card in group:
                    result['cards'].append({**deepcopy(card),'row':local,
                                            'center':(160+card['column']*100,200+local*130)})
            return result
        def tap(x,y):
            control.before_input()
            self.taps.append((x,y))
            item = self.all_rows[self.offset+(y-200)//130][(x-160)//100]
            item['selected'] = not item['selected']
        def swipe(*args):
            control.before_input()
            self.swipes.append(args)
            if not no_move:
                self.offset = min(self.offset+1,2)
        def detail(screen,candidate):
            index = self.offset+candidate['row']
            fingerprint = f'{index}:{candidate["column"]}'
            self.details.append(fingerprint)
            return {'fingerprint':fingerprint,'main':('生命值','540'),'source':'fake.png',
                    'equipment':Equipment(fingerprint,'purple',85,0,'helmet',{'speed':3},True,True,20)}
        navigator = SimpleNamespace(read=read,adb=SimpleNamespace(tap=tap,swipe=swipe),
                                    control=control,journal=None)
        return BatchSelectionDriver(navigator,reader=lambda screen:screen,detail_reader=detail,
                                    excluded_fingerprints=excluded)

    def test_cross_page_collects_in_order_without_reselecting_overlap(self):
        driver = self.driver([(0,0),(1,0),(3,0)])
        result = driver.collect_pages(limit=3,max_pages=3)
        self.assertEqual(self.details,['0:0','1:0','3:0'])
        self.assertEqual(result['selected_count'],3)
        self.assertEqual(len(result['registered']),3)
        self.assertEqual(result['selection_status'],'capacity')
        self.assertEqual(result['scan_evidence']['verified_moves'],1)
        self.assertEqual(len(self.swipes),1)
        self.assertFalse(result['scan_complete'])

    def test_protected_equivalence_is_deselected_and_not_reinspected_in_overlap(self):
        driver = self.driver([(0,0),(1,0),(3,0)],excluded=['1:0'])
        result = driver.collect_pages(limit=2,max_pages=3)
        self.assertEqual(self.details,['0:0','1:0','3:0'])
        self.assertEqual([r['fingerprint'] for r in result['registered']],['0:0','3:0'])
        self.assertEqual(result['protected_equivalence_skipped'],1)
        self.assertFalse(self.all_rows[1][0]['selected'])
        self.assertEqual(len(self.taps),4)

    def test_page_budget_returns_incomplete_instead_of_exhausted(self):
        driver = self.driver([(0,0),(4,0)])
        result = driver.collect_pages(limit=16,max_pages=1)
        self.assertEqual(result['selected_count'],1)
        self.assertFalse(result['scan_complete'])
        self.assertEqual(self.swipes,[])

    def test_positive_bottom_stops_scrolling_without_claiming_full_scan(self):
        driver = self.driver([(3,0),(4,0)])
        original = driver.navigator.read
        def read():
            current = original()
            if self.offset == 2:
                current['cards'] = current['cards'][:-2]
                current['tail_layout'] = {'end_verified':True,'tail_count':5,'row':2}
            return current
        driver.navigator.read = read
        result = driver.collect_pages(limit=16,max_pages=10)
        self.assertEqual(result['selected_count'],2)
        self.assertEqual(len(self.swipes),2)
        self.assertEqual(result['selection_status'],'bottom_reached_unanchored')
        self.assertTrue(result['scan_evidence']['end_verified'])
        self.assertFalse(result['scan_complete'])

    def test_static_scroll_stops_without_repeated_swipe_or_false_empty(self):
        driver = self.driver([],no_move=True)
        with self.assertRaisesRegex(ValueError,'位移'):
            driver.collect_pages()
        self.assertEqual(len(self.swipes),1)
        self.assertEqual(self.taps,[])

    def test_unknown_new_page_card_stops_instead_of_skipping(self):
        driver = self.driver([(3,0)])
        self.all_rows[3][0].update(eligible=False,enhancement=None,known=False)
        with self.assertRaises(ValueError):
            driver.collect_pages()
        self.assertEqual(self.taps,[])


if __name__ == '__main__':
    unittest.main()
