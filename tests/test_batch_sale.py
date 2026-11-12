from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from e7_assistant.batch_sale import BatchSaleDriver
from e7_assistant.batch_sale_vision import OrganizedBatch,SaleConfirmation
from e7_assistant.batch_enhancement import BatchEnhancementDriver
from e7_assistant.batch_resources import BatchResources,UntrackedBatchResources
from e7_assistant.disposal_guard import DisposalGuard
from e7_assistant.initial_cleanup import CleanupInventory
from e7_assistant.rules import Equipment
from e7_assistant.tasks import TaskControl
from e7_assistant.workflow import BatchItem


class BatchSaleTests(unittest.TestCase):
    def fixture(self,root,count=1):
        self.inputs=[];self.events=[];self.confirmed=False;self.selection=[False]*count
        self.page='batch_enhancement';self.corrupt_income=False;self.timeout=False
        self.automatic_return=False;self.inventory_return=False;self.level_warning=False
        self.confirmation_count=1;self.change_confirmation=False;self.modal_reads=0
        self.items=[BatchItem(str(i),Equipment(str(i),'red',85,15,'helmet',
                    {'speed':3,'atk_pct':7,'crit':4,'resistance':4},True,True,30),False,False)
                    for i in range(count)]
        self.before=BatchResources({'gold':1000,'powder':100}, {'gold':1000,'powder':100},
                                   {'powder':0},0,None,'before.png')
        self.after=replace(self.before,available={'gold':1100,'powder':105},
                           remaining={'gold':1100,'powder':105},image='after.png')
        control=TaskControl();control.wait=lambda seconds:control.checkpoint()
        actual=Path(__file__).resolve().parents[1]/'docs/assets/sale-preview-2026-11-10/normal.png'
        def screen(page):
            def find(label,region,minimum_confidence=.9):
                return {'center':{'自动选择':(80,95),'出售':(300,95),
                    '确认':(637,532) if page=='sale_level_warning' else (747,528)}[label]}
            return SimpleNamespace(page=page,source=str(actual),find=find)
        def read():
            return screen('unknown' if self.confirmed and self.timeout else self.page)
        def tap(x,y):
            self.inputs.append((x,y))
            if (x,y)==(80,95): self.selection=[True]*count
            elif (x,y)==(300,95): self.page='sale_level_warning' if self.level_warning else 'sale_confirmation'
            elif (x,y)==(637,532): self.page='sale_confirmation'
            elif (x,y)==(747,528):
                self.confirmed=True;self.page=('inventory_batch_selection_empty' if self.inventory_return else
                                              'batch_enhancement' if self.automatic_return else 'batch_organize')
            else:
                index=(x-62)//244
                self.selection[index]=not self.selection[index]
        def transition(action):
            self.page='batch_organize' if action=='organize_batch' else 'batch_enhancement'
            return screen(self.page)
        nav=SimpleNamespace(directory=Path(root)/'run',control=control,
            batch_inventory_context=('10/1200','获得'),journal=SimpleNamespace(
                emit=lambda kind,**data:self.events.append((kind,data))),
            adb=SimpleNamespace(serial='test-device',tap=tap),read=read,transition=transition,
            navigate=lambda target:screen('inventory'))
        enhancement=SimpleNamespace(navigator=nav,unchanged=BatchEnhancementDriver.unchanged,
            same_resources=BatchEnhancementDriver.same_resources,last_image=None)
        def observe(expected,indices=None):
            return screen('batch_enhancement'),expected,self.after if self.confirmed else self.before
        enhancement.observe=observe
        enhancement.batch_reader=lambda path,slots:{'issues':[],'records':[],
                                      'slots':[{'state':'empty'}]*16}
        enhancement.resource_reader=lambda screen:replace(self.after,
            available={**self.after.available,'gold':1101}) if self.corrupt_income else self.after
        def organized(screen,reference,count):
            return OrganizedBatch(tuple(self.selection),1000,'organize.png',())
        def confirmation(screen):
            self.modal_reads+=1
            digest=f'changed-{self.modal_reads}' if self.change_confirmation and self.modal_reads>1 else 'digest'
            return SaleConfirmation(self.confirmation_count,100,5,digest,'dialog.png')
        self.guard=DisposalGuard(Path(root)/'pending','test-device')
        self.survivor_checks=[]
        def survivor_reader(screen,reference,items,rejected):
            self.survivor_checks.append((screen.page,[i.token for i in items if i.token not in rejected]))
        return BatchSaleDriver(enhancement,organized,confirmation,self.guard,survivor_reader)

    def inventory(self):
        return patch('e7_assistant.batch_sale.inspect_inventory',return_value=
                     CleanupInventory(9,1200,None,1100,'inventory.png'))

    def test_sale_confirms_once_and_settles_gold_powder_and_inventory(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root)
            result=driver.sell(self.items,{'0'},set())
            self.assertEqual(result['disposed'],['0'])
            self.assertEqual(self.inputs,[(80,95),(300,95),(747,528)])
            self.assertFalse(driver.pending)
            self.assertIsNone(self.guard.read())

    def test_historical_survivors_rechecked_before_live_inventory_receipt_without_resubmission(self):
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt),TemporaryDirectory() as root,self.inventory():
                driver=self.fixture(root,2)
                driver.enhancement.resource_reader=lambda screen:UntrackedBatchResources(None,screen.source)
                operation=self.guard.begin('sell',{}, {},Path(root))
                frames=[SimpleNamespace(page='batch_enhancement',source=name) for name in ('a.png','b.png')]
                if corrupt:
                    driver.survivor_reader=lambda *args:(_ for _ in ()).throw(ValueError('属性或锁状态变化'))
                    with self.assertRaises(ValueError):
                        driver.settle_result(self.items,{'0'},{'1'},None,'before.png',None,10,1200,
                                             operation,'forge',historical_survivors=frames)
                    self.assertIsNotNone(self.guard.read())
                else:
                    result=driver.settle_result(self.items,{'0'},{'1'},None,'before.png',None,10,1200,
                                               operation,'forge',historical_survivors=frames)
                    self.assertEqual(result['protected'],['1'])
                    self.assertEqual(len(self.survivor_checks),2)
                    self.assertIsNone(self.guard.read())
                self.assertEqual(self.inputs,[])

    def test_level15_warning_precedes_real_sale_confirmation(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root)
            self.level_warning=True
            driver.sell(self.items,{'0'},set())
            self.assertEqual(self.inputs,[(80,95),(300,95),(637,532),(747,528)])
            self.assertIsNone(self.guard.read())

    def test_level15_warning_without_level15_reject_is_not_confirmed(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root)
            self.level_warning=True
            self.items=[replace(self.items[0],equipment=replace(self.items[0].equipment,enhancement=12))]
            with self.assertRaises(ValueError):
                driver.sell(self.items,{'0'},set())
            self.assertNotIn((637,532),self.inputs)
            self.assertIsNone(self.guard.read())

    def test_transient_render_is_reread_without_repeating_sale_click(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root)
            original=driver.confirmation_reader
            def confirmation(screen):
                value=original(screen)
                return replace(value,digest='first' if self.modal_reads==1 else 'settled')
            driver.confirmation_reader=confirmation
            driver.sell(self.items,{'0'},set())
            self.assertEqual(self.inputs.count((300,95)),1)
            self.assertEqual(self.inputs.count((747,528)),1)
            self.assertGreaterEqual(self.modal_reads,3)

    def test_over_capacity_inventory_can_sell_and_requires_exact_reduction(self):
        for after_count,passed in ((1204,True),(1203,False)):
            with self.subTest(after=after_count),TemporaryDirectory() as root,patch(
                    'e7_assistant.batch_sale.inspect_inventory',return_value=
                    CleanupInventory(after_count,1200,None,1100,'inventory.png')):
                driver=self.fixture(root)
                driver.navigator.batch_inventory_context=('1205/1200','获得')
                if passed:
                    self.assertEqual(driver.sell(self.items,{'0'},set())['disposed'],['0'])
                    self.assertIsNone(self.guard.read())
                else:
                    with self.assertRaises(ValueError):driver.sell(self.items,{'0'},set())
                    self.assertIsNotNone(self.guard.read())
                self.assertEqual(self.inputs.count((747,528)),1)

    def test_untracked_sale_uses_inventory_receipt_without_resource_ocr(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root)
            self.before=UntrackedBatchResources(None,'before.png')
            self.after=UntrackedBatchResources(None,'after.png')
            with patch('e7_assistant.batch_sale.inspect_resources',side_effect=AssertionError('不得读取材料')) as read:
                self.assertEqual(driver.sell(self.items,{'0'},set())['disposed'],['0'])
            read.assert_not_called()
            self.assertEqual(self.inputs.count((747,528)),1)
            self.assertIsNone(self.guard.read())

    def test_untracked_sale_wrong_inventory_reduction_keeps_pending(self):
        with TemporaryDirectory() as root,patch('e7_assistant.batch_sale.inspect_inventory',return_value=
                CleanupInventory(8,1200,None,None,'inventory.png')):
            driver=self.fixture(root)
            self.before=UntrackedBatchResources(None,'before.png')
            self.after=UntrackedBatchResources(None,'after.png')
            with self.assertRaises(ValueError):
                driver.sell(self.items,{'0'},set())
            self.assertEqual(self.inputs.count((747,528)),1)
            self.assertIsNotNone(self.guard.read())

    def test_untracked_all_sold_can_return_directly_to_inventory(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root)
            self.before=UntrackedBatchResources(None,'before.png')
            self.after=UntrackedBatchResources(None,'after.png')
            self.inventory_return=True
            self.assertEqual(driver.sell(self.items,{'0'},set())['disposed'],['0'])
            self.assertEqual(self.inputs.count((747,528)),1)
            self.assertIsNone(self.guard.read())

    def test_sale_toast_retries_survivor_read_without_repeating_confirmation(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root,2)
            original=driver.survivor_reader
            calls=[]
            def delayed(screen,reference,items,rejected):
                calls.append(screen.page)
                if len(calls)==1:
                    raise ValueError('出售成功提示遮挡底行')
                return original(screen,reference,items,rejected)
            driver.survivor_reader=delayed
            self.assertEqual(driver.sell(self.items,{'0'},{'1'})['protected'],['1'])
            self.assertEqual(len(calls),3)
            self.assertEqual(self.inputs.count((747,528)),1)
            self.assertIsNone(self.guard.read())

    def test_native_sale_can_automatically_return_to_batch_enhancement(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root)
            self.automatic_return=True
            result=driver.sell(self.items,{'0'},set())
            self.assertEqual(result['disposed'],['0'])
            self.assertEqual(self.inputs.count((747,528)),1)
            self.assertIsNone(self.guard.read())

    def test_sale_returns_during_cancel_navigation_without_duplicate_input(self):
        from e7_assistant.workflow_navigation import NavigationPageChanged
        for destination,accepted in (('batch_enhancement',True),('unknown',False)):
            with self.subTest(destination=destination),TemporaryDirectory() as root,self.inventory():
                driver=self.fixture(root)
                original=driver.navigator.transition
                def transition(action):
                    if action=='cancel_batch_organize':
                        self.page=destination
                        raise NavigationPageChanged(action,SimpleNamespace(page=destination))
                    return original(action)
                driver.navigator.transition=transition
                if accepted:
                    self.assertEqual(driver.sell(self.items,{'0'},set())['disposed'],['0'])
                    self.assertIsNone(self.guard.read())
                else:
                    with self.assertRaises(NavigationPageChanged):
                        driver.sell(self.items,{'0'},set())
                    self.assertIsNotNone(self.guard.read())
                self.assertEqual(self.inputs,[(80,95),(300,95),(747,528)])

    def test_empty_batch_auto_returns_to_inventory_during_cancel_but_survivors_require_review(self):
        from e7_assistant.workflow_navigation import NavigationPageChanged
        for destination in ('inventory','inventory_batch_selection','inventory_batch_selection_empty'):
            for survivors in (False,True):
                with self.subTest(destination=destination,survivors=survivors),TemporaryDirectory() as root,self.inventory():
                    driver=self.fixture(root,2 if survivors else 1)
                    self.before=UntrackedBatchResources(None,'before.png')
                    self.after=UntrackedBatchResources(None,'after.png')
                    original=driver.navigator.transition
                    def transition(action):
                        if action=='cancel_batch_organize':
                            self.page=destination
                            raise NavigationPageChanged(action,SimpleNamespace(page=destination))
                        return original(action)
                    driver.navigator.transition=transition
                    if survivors:
                        with self.assertRaises(NavigationPageChanged):driver.sell(self.items,{'0'},{'1'})
                        self.assertIsNotNone(self.guard.read())
                    else:
                        self.assertEqual(driver.sell(self.items,{'0'},set())['disposed'],['0'])
                        self.assertIsNone(self.guard.read())
                    self.assertEqual(self.inputs.count((747,528)),1)

    def test_untracked_target_preview_is_rejected_before_sale_baseline(self):
        with TemporaryDirectory() as root:
            driver=self.fixture(root)
            self.before=UntrackedBatchResources(6,'before.png')
            with patch('e7_assistant.batch_sale.inspect_resources') as read:
                with self.assertRaises(ValueError):driver.sell(self.items,{'0'},set())
                read.assert_not_called()
            self.assertEqual(self.inputs,[])

    def test_organize_animation_only_retries_reads_without_inputs(self):
        with TemporaryDirectory() as root:
            driver=self.fixture(root)
            accepted=OrganizedBatch((False,),1000,'organize.png',())
            from unittest.mock import Mock
            driver.organized_reader=Mock(side_effect=(ValueError('闪光'),accepted))
            _,state=driver.observe('before.png',1,1000)
            self.assertEqual(state,accepted)
            self.assertEqual(driver.organized_reader.call_count,2)
            self.assertEqual(self.inputs,[])
            driver.organized_reader=Mock(side_effect=ValueError('内容变化'))
            with self.assertRaises(ValueError):driver.observe('before.png',1,1000)
            self.assertEqual(driver.organized_reader.call_count,3)
            self.assertEqual(self.inputs,[])

    def test_protected_plus15_is_removed_from_auto_selection_and_verified_after_sale(self):
        with TemporaryDirectory() as root,self.inventory():
            driver=self.fixture(root,2)
            self.items[1].locked=True
            result=driver.sell(self.items,{'0'},{'1'})
            self.assertEqual(result['protected'],['1'])
            self.assertEqual(self.inputs,[(80,95),(306,185),(300,95),(747,528)])
            self.assertEqual(self.survivor_checks,[('batch_enhancement',['1'])]*2)

    def test_invalid_targets_locks_action_and_context_fail_before_inputs(self):
        for case in ('locked','overlap','missing_partition','extract','selected','context'):
            with self.subTest(case=case),TemporaryDirectory() as root:
                driver=self.fixture(root); rejected={'0'};protected=set(); action='sell'
                if case=='locked': self.items[0].locked=True
                if case=='overlap': protected={'0'}
                if case=='missing_partition': rejected={'1'}
                if case=='extract': action='extract'
                if case=='selected': self.items[0].selected=True
                if case=='context': driver.navigator.batch_inventory_context=()
                with self.assertRaises(ValueError): driver.sell(self.items,rejected,protected,action)
                self.assertEqual(self.inputs,[])

    def test_jewelry_and_mixed_sales_settle_the_correct_powder_balances(self):
        for mixed in (False,True):
            count=2 if mixed else 1
            with self.subTest(mixed=mixed),TemporaryDirectory() as root,patch(
                    'e7_assistant.batch_sale.inspect_inventory',return_value=
                    CleanupInventory(10-count,1200,None,1100,'inventory.png')):
                driver=self.fixture(root,count)
                self.items[0].equipment.slot='ring'
                before={'gold':1000,'powder':100,'jewelry_powder':100}
                after={'gold':1100,'powder':105 if mixed else 100,'jewelry_powder':105}
                self.before=replace(self.before,available=before,remaining=before)
                self.after=replace(self.after,available=after,remaining=after)
                driver.confirmation_reader=lambda screen:SaleConfirmation(count,100,5 if mixed else 0,
                                                                           'digest','dialog.png',5)
                result=driver.sell(self.items,{str(i) for i in range(count)},set())
                self.assertEqual(len(result['disposed']),count)
                self.assertEqual(self.inputs.count((747,528)),1)
                self.assertIsNone(self.guard.read())

    def test_wrong_reward_category_never_reaches_sale_confirmation_input(self):
        with TemporaryDirectory() as root:
            driver=self.fixture(root)
            self.items[0].equipment.slot='ring'
            with self.assertRaises(ValueError):driver.sell(self.items,{'0'},set())
            self.assertNotIn((747,528),self.inputs)
            self.assertIsNone(self.guard.read())

    def test_old_pending_guard_prevents_any_navigation_or_input(self):
        with TemporaryDirectory() as root:
            driver=self.fixture(root)
            self.guard.begin('sell',{}, {},Path(root))
            with self.assertRaises(ValueError): driver.sell(self.items,{'0'},set())
            self.assertEqual(self.inputs,[])
            self.assertEqual(self.page,'batch_enhancement')

    def test_modal_count_or_digest_conflict_prevents_confirmation(self):
        for case in ('count','digest'):
            with self.subTest(case=case),TemporaryDirectory() as root:
                driver=self.fixture(root)
                self.confirmation_count=2 if case=='count' else 1
                self.change_confirmation=case=='digest'
                with self.assertRaises(ValueError): driver.sell(self.items,{'0'},set())
                self.assertNotIn((747,528),self.inputs)
                self.assertIsNone(self.guard.read())

    def test_unknown_result_and_wrong_income_persist_guard_and_never_repeat(self):
        for case in ('timeout','income'):
            with self.subTest(case=case),TemporaryDirectory() as root,self.inventory():
                driver=self.fixture(root)
                self.timeout=case=='timeout'; self.corrupt_income=case=='income'
                with self.assertRaises((ValueError,TimeoutError)):
                    driver.sell(self.items,{'0'},set())
                self.assertEqual(self.inputs.count((747,528)),1)
                self.assertTrue(driver.pending)
                self.assertIsNotNone(self.guard.read())
                with self.assertRaises(ValueError): driver.sell(self.items,{'0'},set())
                self.assertEqual(self.inputs.count((747,528)),1)

    def test_wrong_inventory_reduction_does_not_settle(self):
        with TemporaryDirectory() as root,patch('e7_assistant.batch_sale.inspect_inventory',return_value=
                CleanupInventory(8,1200,None,1100,'inventory.png')):
            driver=self.fixture(root)
            with self.assertRaises(ValueError): driver.sell(self.items,{'0'},set())
            self.assertIsNotNone(self.guard.read())


if __name__=='__main__': unittest.main()
