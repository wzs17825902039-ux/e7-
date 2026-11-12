from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.tasks import TaskControl, Cancelled
from e7_assistant.rules import Equipment,Policy


def card(column, enhancement=0):
    return {'row': 0, 'column': column, 'center': (160 + column * 100, 200),
            'level': 85, 'rarity': 'purple', 'enhancement': enhancement,
            'selected': False, 'signature': str(column), 'identity_vector': [1., 0.],
            'eligible': enhancement < 15, 'known': True}


class SelectionTests(unittest.TestCase):
    def test_custom_set_check_waits_for_batch_page_in_detail_selection_mode(self):
        self.setup_driver([{**card(0),'rarity':'red'}])
        def tap(x,y):
            self.clicks.append((x,y))
            target=self.state['cards'][0]
            target['selected']=not target['selected']
            self.state['selected_count']+=1 if target['selected'] else -1
        self.navigator.adb.tap=tap
        item=Equipment('custom','red',85,0,'helmet',{'atk_pct':8,'crit':3,'effectiveness':8,'resistance':8},True,True)
        driver=BatchSelectionDriver(self.navigator,reader=lambda screen:screen,
            detail_reader=lambda screen,candidate:{'equipment':item,'fingerprint':'test','main':('生命值','540'),'source':'screen.png'},
            policy=Policy(ignore_equipment_level=False,custom_targets_enabled=True,
                          custom_targets=[{'name':'输出','sets':['speed'],'stats':['atk_pct','crit']}]))
        result=driver.collect_visible(limit=1)
        self.assertEqual(len(result['registered']),1)
        self.assertEqual(self.clicks,[(160,200)])
        self.assertTrue(self.state['cards'][0]['selected'])

    def setup_driver(self, cards, policy=None):
        state = {'source': 'screen.png', 'page': 'inventory_batch_selection', 'cards': cards,
                 'selected_count': 0, 'scan_complete': False}
        self.clicks = []
        self.state = state
        def tap(x, y):
            self.clicks.append((x, y))
            target = next(c for c in state['cards'] if c['center'] == (x, y))
            target['selected'] = True
            state['selected_count'] += 1
        navigator = SimpleNamespace(read=lambda: deepcopy(state), adb=SimpleNamespace(tap=tap),
                                    control=TaskControl(), journal=None)
        navigator.control.wait = lambda seconds: navigator.control.checkpoint()
        self.navigator = navigator
        detail = lambda screen,candidate: {'equipment':Equipment('test','purple',85,candidate['enhancement'],'helmet',
                                          {'speed':3,'crit':5,'atk_pct':7,**({'hp_pct':4} if candidate['enhancement']>=12 else {})},True,True,20),
                                          'fingerprint':'test', 'main':('生命值','540'), 'source':'screen.png'}
        return BatchSelectionDriver(navigator, reader=lambda screen: screen, detail_reader=detail,policy=policy)

    def test_selects_unfinished_in_order_and_skips_fifteen(self):
        driver = self.setup_driver([card(0, 15), card(1, 3), card(2, 14)])
        result = driver.collect_visible(limit=2)
        self.assertEqual(self.clicks, [(260, 200), (360, 200)])
        self.assertEqual(result['selection_status'], 'capacity')
        self.assertFalse(result['scan_complete'])
        self.assertEqual([item['equipment']['enhancement'] for item in result['registered']],[3,14])

    def test_confirmed_fifteen_needs_no_other_fields_to_be_preserved(self):
        finished={**card(0,15),'level':None,'known':False,'eligible':False}
        driver=self.setup_driver([finished,card(1,3)])
        result=driver.collect_visible(limit=1)
        self.assertEqual(self.clicks,[(260,200)])
        self.assertEqual(result['registered'][0]['equipment']['enhancement'],3)

    def test_tail_does_not_claim_inventory_exhausted(self):
        driver = self.setup_driver([card(0)])
        result = driver.collect_visible()
        self.assertEqual(result['selected_count'], 1)
        self.assertEqual(result['selection_status'], 'visible_exhausted')
        self.assertFalse(result['scan_complete'])

    def test_unknown_equipment_not_skipped_in_order(self):
        bad = card(0)
        bad.update(eligible=False, enhancement=None)
        driver = self.setup_driver([bad, card(1)])
        with self.assertRaises(ValueError):
            driver.collect_visible()
        self.assertEqual(self.clicks, [])

    def test_existing_selection_is_not_cleared_or_toggled(self):
        driver = self.setup_driver([card(0)])
        self.state['selected_count'] = 1
        with self.assertRaises(ValueError):
            driver.collect_visible()
        self.assertEqual(self.clicks, [])

    def test_no_effect_click_is_not_retried(self):
        driver = self.setup_driver([card(0)])
        self.navigator.adb.tap = lambda x,y: self.clicks.append((x,y))
        with self.assertRaises(ValueError):
            driver.collect_visible()
        self.assertEqual(len(self.clicks), 1)

    def test_zero_mode_can_transition_to_visible_footer_on_first_selection(self):
        driver = self.setup_driver([card(0)])
        self.state['page'] = 'inventory_batch_selection_empty'
        self.state['mode_evidence'] = {'selected_count':0,'empty_detail_confirmed':True}
        original = self.navigator.adb.tap
        def tap(x,y):
            original(x,y)
            self.state['page'] = 'inventory_batch_selection'
            self.state['mode_evidence'] = None
        self.navigator.adb.tap = tap
        result = driver.collect_visible(limit=1)
        self.assertEqual(result['selected_count'],1)
        self.assertEqual(len(result['registered']),1)
        self.assertEqual(len(self.clicks),1)

    def test_user_stop_blocks_input(self):
        driver = self.setup_driver([card(0)])
        self.navigator.control.stop()
        with self.assertRaises(Cancelled):
            driver.collect_visible()
        self.assertEqual(self.clicks, [])

    def test_click_animation_retries_reading_without_repeating_input(self):
        driver = self.setup_driver([card(0)])
        read = self.navigator.read
        frames = []
        def animated():
            result = read()
            if self.clicks:
                frames.append(1)
                if len(frames)<3:
                    result['cards'][0]['identity_vector']=[.98,.199]
            return result
        self.navigator.read=animated
        result=driver.collect_visible(limit=1)
        self.assertEqual(len(frames),3)
        self.assertEqual(result['selected_count'],1)
        self.assertEqual(len(self.clicks),1)

    def test_click_retries_only_temporarily_missing_neighbor_field(self):
        driver=self.setup_driver([card(0),card(1)])
        for c in self.state['cards']:
            c['tracking_box']=(153+c['column']*99,150,226+c['column']*99,248)
        read=self.navigator.read
        frames=[]
        def missing():
            result=read()
            if self.clicks:
                frames.append(1)
                if len(frames)==1:
                    result['cards'][1].update(rarity=None,known=False,eligible=False)
            return result
        self.navigator.read=missing
        with patch('e7_assistant.inventory_tracking.inspect_tracking',return_value={'matched':True}):
            result=driver.collect_visible(limit=1)
        self.assertEqual(len(self.clicks),1)
        self.assertEqual(len(frames),2)
        self.assertEqual(result['selected_count'],1)

    def test_click_never_retries_a_complete_neighbor_conflict(self):
        driver=self.setup_driver([card(0),card(1)])
        read=self.navigator.read
        frames=[]
        def conflict():
            result=read()
            if self.clicks:
                frames.append(1)
                result['cards'][1]['rarity']='red'
            return result
        self.navigator.read=conflict
        with self.assertRaises(ValueError):
            driver.collect_visible(limit=1)
        self.assertEqual(len(self.clicks),1)
        self.assertEqual(len(frames),1)

    def test_persistent_image_mismatch_stops_after_bounded_reads(self):
        driver = self.setup_driver([card(0)])
        read = self.navigator.read
        frames=[]
        def changed():
            result=read()
            if self.clicks:
                frames.append(1)
                result['cards'][0]['identity_vector']=[0.,1.]
            return result
        self.navigator.read=changed
        with self.assertRaisesRegex(ValueError,'图像身份'):
            driver.collect_visible(limit=1)
        self.assertEqual(len(frames),4)
        self.assertEqual(len(self.clicks),1)

    def test_wrong_selection_with_unstable_image_is_not_retried(self):
        driver = self.setup_driver([card(0),card(1)])
        read=self.navigator.read
        frames=[]
        def changed():
            result=read()
            if self.clicks:
                frames.append(1)
                result['cards'][0]['identity_vector']=[0.,1.]
                result['cards'][1]['selected']=True
            return result
        self.navigator.read=changed
        with self.assertRaisesRegex(ValueError,'勾选集合'):
            driver.collect_visible(limit=1)
        self.assertEqual(len(frames),1)
        self.assertEqual(len(self.clicks),1)

    def test_another_card_becoming_selected_stops(self):
        driver = self.setup_driver([card(0), card(1)])
        def wrong(x, y):
            self.clicks.append((x,y))
            self.state['cards'][1]['selected'] = True
            self.state['selected_count'] = 1
        self.navigator.adb.tap = wrong
        with self.assertRaises(ValueError):
            driver.collect_visible()
        self.assertEqual(len(self.clicks), 1)

    def test_policy_protection_skips_equivalent_zero_gear_and_fills_next_candidate(self):
        import tempfile
        from e7_assistant.equipment_protection import EquipmentProtection
        from e7_assistant.inventory_detail import detail_fingerprint
        from e7_assistant.rules import Policy
        driver = self.setup_driver([card(0),card(1),card(2)])
        def tap(x,y):
            self.clicks.append((x,y))
            target = next(c for c in self.state['cards'] if c['center'] == (x,y))
            target['selected'] = not target['selected']
            self.state['selected_count'] += 1 if target['selected'] else -1
        self.navigator.adb.tap = tap
        def detail(screen,candidate):
            stats = {'speed':3,'crit':5,'atk_pct':7} if candidate['column']==2 else {'hp_pct':5,'crit':5,'atk_pct':7}
            equipment = Equipment('test','purple',85,0,'helmet',stats,True,True,25)
            main = ('生命值','540')
            return {'equipment':equipment,'fingerprint':detail_fingerprint(equipment,main),
                    'main':main,'source':'screen.png'}
        with tempfile.TemporaryDirectory() as directory:
            policy = Policy()
            protection = EquipmentProtection(directory,'test-device',policy)
            driver = BatchSelectionDriver(self.navigator,reader=lambda screen:screen,detail_reader=detail,
                                          policy=policy,protection=protection)
            result = driver.collect_visible(limit=1)
            self.assertEqual(len(result['registered']),1)
            self.assertEqual(result['registered'][0]['equipment']['stats']['speed'],3)
            self.assertEqual(self.clicks,[(160,200),(160,200),(260,200),(260,200),(360,200)])
            self.assertEqual(len(protection.records()),1)
            self.assertFalse(self.state['cards'][0]['selected'])
            self.assertFalse(self.state['cards'][1]['selected'])
            self.state['cards'][2]['selected'] = False
            self.state['selected_count'] = 0
            restored = EquipmentProtection(directory,'test-device',Policy())
            next_driver = BatchSelectionDriver(self.navigator,reader=lambda screen:screen,detail_reader=detail,
                                              policy=Policy(),protection=restored)
            next_result = next_driver.collect_visible(limit=1)
            self.assertEqual(len(next_result['registered']),1)
            self.assertEqual(next_result['registered'][0]['equipment']['stats']['speed'],3)
            self.assertEqual(len(restored.records()),1)
            self.assertEqual(len(self.clicks),10)

    def test_policy_mismatch_is_rejected_before_navigation(self):
        import tempfile
        from e7_assistant.equipment_protection import EquipmentProtection
        from e7_assistant.rules import Policy
        driver = self.setup_driver([card(0)])
        with tempfile.TemporaryDirectory() as directory:
            store = EquipmentProtection(directory,'test-device',Policy())
            with self.assertRaises(ValueError):
                BatchSelectionDriver(self.navigator,policy=Policy(initial_speed_min=3),protection=store)
        self.assertEqual(self.clicks,[])

    def test_confirmed_special_gear_is_deselected_and_next_item_fills_batch(self):
        from e7_assistant.inventory_detail import UnsupportedEquipment
        driver=self.setup_driver([card(0),card(1)])
        original=driver.detail_reader
        def detail(screen,candidate):
            if candidate['column']==0:
                raise UnsupportedEquipment('异界装备')
            return original(screen,candidate)
        driver.detail_reader=detail
        def toggle(x,y):
            self.clicks.append((x,y))
            target=next(c for c in self.state['cards'] if c['center']==(x,y))
            target['selected']=not target['selected']
            self.state['selected_count']+=1 if target['selected'] else -1
        self.navigator.adb.tap=toggle
        result=driver.collect_visible(limit=1)
        self.assertEqual(self.clicks,[(160,200),(160,200),(260,200)])
        self.assertFalse(self.state['cards'][0]['selected'])
        self.assertEqual(len(result['registered']),1)

    def test_uncertain_detail_stops_without_skipping_or_selecting_next_item(self):
        driver=self.setup_driver([card(0),card(1)])
        def uncertain(screen,candidate):
            raise ValueError('疑似异界或OCR失败')
        driver.detail_reader=uncertain
        with self.assertRaisesRegex(ValueError,'OCR失败'):
            driver.collect_visible(limit=1)
        self.assertEqual(self.clicks,[(160,200)])
        self.assertTrue(self.state['cards'][0]['selected'])

    def test_confirmed_non_target_levels_are_preserved_without_selection(self):
        unsupported=[{**card(0),'level':88,'eligible':False},
                     {**card(1),'level':90,'eligible':False}]
        driver=self.setup_driver([*unsupported,card(2)],policy=Policy(ignore_equipment_level=False))
        result=driver.collect_visible(limit=1)
        self.assertEqual(self.clicks,[(360,200)])
        self.assertEqual(len(result['registered']),1)
        self.assertFalse(self.state['cards'][0]['selected'])
        self.assertFalse(self.state['cards'][1]['selected'])

    def test_uncertain_non_target_level_does_not_allow_skip(self):
        bad={**card(0),'level':88,'known':False,'eligible':False}
        driver=self.setup_driver([bad,card(1)])
        with self.assertRaisesRegex(ValueError,'未确认'):
            driver.collect_visible(limit=1)
        self.assertEqual(self.clicks,[])
