from pathlib import Path
from dataclasses import replace
from unittest.mock import Mock
import unittest

from e7_assistant.inventory_detail import read_detail,UnsupportedEquipment
from e7_assistant.workflow_screen import Screen


def screen():
    rows = [('传说头盔',1006,192),('生命值',914,342),('速度',902,382),
            ('防御力',909,404),('效果命中',918,426),('攻击力',909,450)]
    return Screen(str(Path(__file__).resolve().parents[1]/'docs/assets/user-workflow-2026-11-09/15-select-unenhanced.png'),
                  'inventory_batch_selection',1661,933,
                  tuple({'text':text,'center':(x,y),'confidence':1.} for text,x,y in rows))


class DetailTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {'rarity':'red','level':85,'enhancement':0}
        self.values = {'level':'85','score':'23','main':'540','stat0':'3','stat1':'28','stat2':'4%','stat3':'5%'}

    def test_registers_all_attributes_and_main_stat(self):
        detail = read_detail(screen(),self.candidate,lambda path,boxes:self.values)
        self.assertEqual(detail['equipment'].slot,'helmet')
        self.assertEqual(detail['equipment'].stats,{'speed':3,'def_flat':28,'effectiveness':4,'atk_pct':5})
        self.assertEqual(detail['main'],('生命值','540'))

    def test_wrong_quality_or_level_rejected(self):
        for update in ({'rarity':'purple'},{'level':88},{'enhancement':3}):
            with self.assertRaises(ValueError):
                read_detail(screen(),{**self.candidate,**update},lambda path,boxes:self.values)

    def test_special_tier_title_is_not_registered_as_ordinary_legendary(self):
        original = screen()
        for text in ('异界传说武', '异界'):
            special = replace(original, words=original.words + (
                {'text':text,'center':(1006,192),'confidence':.7},))
            reader = Mock()
            with self.assertRaisesRegex(ValueError, '异界'):
                read_detail(special,self.candidate,reader)
            reader.assert_not_called()

    def test_missing_unit_or_number_rejected(self):
        for key,value in [('stat0','3%'),('stat2','4'),('score',''),('main','')]:
            with self.subTest(field=key),self.assertRaises(ValueError):
                read_detail(screen(),self.candidate,lambda path,boxes:{**self.values,key:value})

    def test_only_complete_confirmed_special_title_registers_as_bonus_red(self):
        original=screen()
        for confidence in (.7,.94,.95,1.):
            special=replace(original,words=tuple(w for w in original.words if w['text']!='传说头盔')+(
                {'text':'异界传说头盔','center':(1006,192),'confidence':confidence},))
            reader=Mock(return_value=self.values)
            if confidence<.95:
                with self.assertRaises(ValueError):read_detail(special,self.candidate,reader)
                reader.assert_not_called()
            else:
                detail=read_detail(special,{**self.candidate,'rarity':'purple'},reader)
                self.assertEqual(detail['equipment'].rarity,'red')
                self.assertTrue(detail['equipment'].enhancement_bonus)
                self.assertEqual(len(detail['equipment'].stats),4)

    def test_stale_enhanced_detail_is_not_registered_as_zero(self):
        original = screen()
        stale = Screen(original.source,original.page,original.width,original.height,
                       original.words + ({'text':'+15','center':(950,178),'confidence':1.},))
        with self.assertRaisesRegex(ValueError,'强化徽标'):
            read_detail(stale,self.candidate,lambda path,boxes:self.values)

    def test_existing_enhancement_is_verified_and_preserved(self):
        for stage in (3, 9, 12, 14):
            original = screen()
            words = tuple({**word, 'text': '英雄头盔'} if word['text']=='传说头盔' else word
                          for word in original.words)
            if stage < 12:
                words = tuple(word for word in words if word['center'][1] != 450)
            observed = replace(original, words=words + (
                {'text':f'+{stage}','center':(950,178),'confidence':1.},))
            candidate = {**self.candidate,'rarity':'purple','enhancement':stage}
            values = {**self.values,'enhancement':f'+{stage}'}
            with self.subTest(stage=stage):
                actual = read_detail(observed,candidate,lambda path,boxes:values)
                self.assertEqual(actual['equipment'].enhancement,stage)
                self.assertEqual(len(actual['equipment'].stats),3 if stage<12 else 4)
                for wrong in ('', '+15', '+2'):
                    with self.assertRaises(ValueError):
                        read_detail(observed,candidate,lambda path,boxes:{**values,'enhancement':wrong})

    def test_finished_equipment_cannot_be_registered(self):
        with self.assertRaises(ValueError):
            read_detail(screen(),{**self.candidate,'enhancement':15},lambda path,boxes:self.values)
