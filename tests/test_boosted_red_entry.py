from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from PIL import Image

from e7_assistant.workflow_screen import inspect_selection_screen
from e7_assistant.inventory_detail import read_selection_header
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.inventory_grid_vision import locate_rows
from e7_assistant.slot_vision import inspect_slots

ROOT=Path(__file__).resolve().parents[1]


class BoostedRedEntryTests(unittest.TestCase):
    def test_same_attributes_survive_decorative_badge_background_glow(self):
        from e7_assistant.batch_sale_vision import content_proof
        folder=ROOT/'runs/full-workflow-04553449'
        with Image.open(folder/'workflow-0053.png') as before,Image.open(folder/'workflow-0054.png') as after:
            for index in range(16):
                content_proof(before,after,index,strict=True,attributes_only=True)

    def test_registered_batch_observes_attributes_without_classifying_artwork(self):
        from e7_assistant.batch_vision import inspect_batch,verify_stable_batch_pixels
        from e7_assistant.rules import Equipment
        from e7_assistant.workflow import BatchItem
        folder=ROOT/'runs/selected-inventory-resume-b5a2fb99'
        previous=json.loads((folder/'result.json').read_text(encoding='utf8'))
        items=[BatchItem(i['token'],Equipment(**i['equipment']),i['selected'],i['locked'])
               for i in previous['items']]
        source=folder/'workflow-0020.png'
        with patch('e7_assistant.batch_vision._rarity',side_effect=AssertionError('不得重复识别装备大图')):
            report=inspect_batch(source,{i:item.equipment.slot for i,item in enumerate(items)},
                                 known_items=items,ignore_levels=True,require_score=False)
        self.assertEqual(report['issues'],[])
        self.assertEqual(len(report['records']),16)
        for item,record in zip(items,report['records']):
            self.assertEqual(record['equipment']['stats'],item.equipment.stats)
        with TemporaryDirectory() as directory:
            output=Path(directory)/'artwork-covered.png'
            with Image.open(source) as image:
                image=image.convert('RGB')
                from e7_assistant.batch_sale_vision import origin
                for index in range(16):
                    dx,dy=origin(index)
                    image.paste((0,0,0),(25+dx,165+dy,74+dx,208+dy))
                image.save(output)
            verify_stable_batch_pixels(source,output,items)
        for color in ('black','white'):
            slots=inspect_slots(Image.new('RGB',(1661,933),color),
                                registered_rarities={i:item.equipment.rarity for i,item in enumerate(items)})
            self.assertTrue(all(s['state']=='unknown' for s in slots))

    def test_bonus_red_glow_fading_does_not_override_valid_red_evidence(self):
        folder=ROOT/'runs/selected-inventory-resume-b5a2fb99'
        for name in ('workflow-0018.png','workflow-0019.png','workflow-0020.png'):
            with Image.open(folder/name) as image:
                result=inspect_slots(image.convert('RGB').resize((1661,933)),range(4,16))
            self.assertEqual(result[6]['state'],'occupied',name)
            self.assertEqual(result[6]['rarity'],'red',name)

    def test_bonus_red_boots_use_red_rules_and_no_unverified_score_multiplier(self):
        from e7_assistant.rules import Equipment,Policy,evaluate
        policy=Policy(red_profile_enabled=True,sell_failed_red=True)
        ordinary=Equipment('red-boots','red',None,0,'boots',
                           {'speed':3,'atk_pct':8,'crit':5,'cdmg':7},True,True)
        boosted=replace(ordinary,enhancement_bonus=True)
        self.assertEqual(evaluate(boosted,policy),evaluate(ordinary,policy))
        self.assertEqual(evaluate(boosted,policy).action,'continue')
        with self.assertRaises(ValueError):replace(boosted,rarity='purple')

    def test_real_mixed_ordinary_and_bonus_red_batch_reads_all_four_stats(self):
        from e7_assistant.batch_vision import inspect_batch
        folder=ROOT/'runs/boosted-red-entry-149228ed'
        selection=json.loads((folder/'selection-0001.json').read_text(encoding='utf8'))
        registered=selection['registered']
        slots={i:entry['equipment']['slot'] for i,entry in enumerate(registered)}
        boosted={i for i,entry in enumerate(registered) if entry['equipment'].get('enhancement_bonus')}
        self.assertEqual(boosted,set(range(4,16)))
        report=inspect_batch(folder/'workflow-0038.png',slots,ignore_levels=True,
                             require_score=False,ignore_purple_main=True,
                             purple_speed_only=True,boosted_red_indices=boosted)
        self.assertEqual(report['issues'],[])
        self.assertEqual([r['index'] for r in report['records']],list(range(16)))
        for record in report['records']:
            equipment=record['equipment']
            self.assertEqual(equipment['rarity'],'red')
            self.assertEqual(equipment['enhancement_bonus'],record['index'] in boosted)
            self.assertEqual(equipment['observation_scope'],'full')
            self.assertEqual(len(equipment['stats']),4)
        from e7_assistant.batch_entry import verify_entry
        items=verify_entry(selection,report)
        self.assertEqual({i for i,item in enumerate(items) if item.equipment.enhancement_bonus},boosted)
        report['records'][4]['equipment']['enhancement_bonus']=False
        with self.assertRaisesRegex(ValueError,'强化加成'):
            verify_entry(selection,report)

    def test_bonus_slots_require_registered_type_and_visible_equipment(self):
        source=ROOT/'runs/boosted-red-entry-149228ed/workflow-0038.png'
        with Image.open(source) as image:
            image=image.convert('RGB').resize((1661,933))
            ordinary=inspect_slots(image)
            confirmed=inspect_slots(image,range(4,16))
        self.assertTrue(any(s['rarity']!='red' for s in ordinary[4:]))
        self.assertTrue(all(s['rarity']=='red' and s['state']=='occupied' for s in confirmed))
        for color in ('black','white','#262626'):
            blank=inspect_slots(Image.new('RGB',(1661,933),color),range(16))
            self.assertTrue(all(s['state']=='unknown' for s in blank))

    def test_wrapped_otherworld_legendary_title_is_red_and_not_purple(self):
        source=ROOT/'runs/boosted-red-entry-6d7af0a7/workflow-0025.png'
        screen=inspect_selection_screen(source)
        header=read_selection_header(screen,{'rarity':'purple','enhancement':0})
        self.assertEqual(header,{'rarity':'red','slot':'ring','level':None,'enhancement':0,'enhancement_bonus':True})
        missing=replace(screen,words=tuple(w for w in screen.words if w['text']!='指'))
        with self.assertRaises(ValueError):read_selection_header(missing,{'rarity':'purple','enhancement':0})

    def test_fully_selected_golden_rows_still_have_all_seven_card_edges(self):
        source=ROOT/'runs/boosted-red-entry-138bf795/workflow-0034.png'
        report=inspect_inventory(inspect_selection_screen(source),ignore_levels=True)
        self.assertEqual(report['selected_count'],14)
        self.assertEqual(len(report['cards']),21)
        self.assertEqual(sum(c['selected'] for c in report['cards']),14)
        with TemporaryDirectory() as folder:
            output=Path(folder)/'missing-card.png'
            with Image.open(source) as image:
                image=image.convert('RGB');image.paste((0,0,0),(537,147,634,274));image.save(output)
            with self.assertRaises(ValueError):locate_rows(output,{})
