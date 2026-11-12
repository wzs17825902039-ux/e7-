from pathlib import Path
from copy import deepcopy
import json
import unittest
from PIL import Image,ImageDraw

from e7_assistant.batch_vision import inspect_batch,_stat_crop_consensus
from e7_assistant.lock_vision import inspect_batch_lock
from e7_assistant.batch_entry import verify_entry

ASSET=Path(__file__).resolve().parents[1]/'docs/assets/batch-entry-2026-11-10/16-plus0.png'


class MultiEntryLiveTests(unittest.TestCase):
    def test_all_sixteen_real_cards_read_completely(self):
        report=inspect_batch(ASSET,{i:'helmet' for i in range(16)})
        self.assertEqual(report['issues'],[])
        self.assertEqual(len(report['records']),16)
        self.assertEqual(report['records'][5]['equipment']['stats'],{'speed':4,'atk_pct':7,'crit':5})
        self.assertTrue(all(c['locked'] is False for c in report['records']))
        self.assertTrue(report['ocr_details']['stat5_1']['accepted'])
        self.assertEqual(report['ocr_details']['stat5_1']['text'],'7%')
        self.assertGreaterEqual(report['ocr_details']['stat5_1']['confidence'],.9)
        selection=json.loads(ASSET.with_name('selection.json').read_text(encoding='utf8'))
        items=verify_entry(selection,report)
        self.assertEqual(len(items),16)

    def test_real_fifteenth_open_lock(self):
        with Image.open(ASSET) as image:
            self.assertIs(inspect_batch_lock(image,'batch_enhancement',14,True)['locked'],False)

    def test_original_color_conflicts_and_missing_proof_rejected(self):
        evidence={'accepted':True,'text':'7%','candidates':[
            {'variant':'raw','text':'7%','confidence':.96},
            {'variant':'invert','text':'70%','confidence':.91}]}
        self.assertEqual(_stat_crop_consensus(evidence,evidence,evidence),'7%')
        for case in ('raw_conflict','context_conflict','not_accepted','low_confidence','no_raw'):
            first,second,third=[deepcopy(evidence) for _ in range(3)]
            if case=='raw_conflict':second['candidates'][0]['text']='70%'
            if case=='context_conflict':second['candidates'].append(
                {'variant':'guided','text':'70%','confidence':.95})
            if case=='not_accepted':third['accepted']=False
            if case=='low_confidence':first['candidates'][0]['confidence']=.89
            if case=='no_raw':first['candidates']=[]
            with self.subTest(case=case):self.assertIsNone(_stat_crop_consensus(first,second,third))

    def test_shifted_lock_search_does_not_accept_erased_or_moved_button(self):
        with Image.open(ASSET) as image:
            for case in ('erased','moved'):
                changed=image.convert('RGB').resize((1661,933))
                box=(907,674,960,715)
                button=changed.crop(box)
                ImageDraw.Draw(changed).rectangle(box,fill='#303030')
                if case=='moved':changed.paste(button,(912,674))
                with self.subTest(case=case):
                    self.assertIsNone(inspect_batch_lock(changed,'batch_enhancement',14,True)['locked'])


if __name__=='__main__':unittest.main()
