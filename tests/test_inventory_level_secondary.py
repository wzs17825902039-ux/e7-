from pathlib import Path
import unittest
from unittest.mock import patch

from e7_assistant.inventory_vision import _read_levels
from tests import test_inventory_level_color as color_cases


class SecondaryLevelTests(unittest.TestCase):
    def test_real_margin_conflict_requires_independent_engine(self):
        path=Path(__file__).resolve().parents[1]/'docs/assets/inventory-traversal-2026-11-10/87-level-secondary.png'
        # 原输入框经过_level_region内缩后才是(354,203,375,217)。
        values,evidence=_read_levels(path,{'level0_2':(348,198,375,222)},True)
        self.assertEqual(values['level0_2'],'85')
        self.assertEqual(evidence['level0_2']['recovery'],'secondary_color_consensus')
        proof=evidence['level0_2']['original']['secondary_level_evidence']
        self.assertEqual((proof['engine'],proof['text'],proof['accepted']),('windows','85',True))
        self.assertIsNone(proof['confidence'])

    def scenario(self,margin='15',secondary='85',original='5'):
        kwargs=({'side_effect':secondary} if isinstance(secondary,Exception) else {'return_value':{'level':secondary}})
        with patch('e7_assistant.vision.read_regions',**kwargs) as reader:
            candidates=[{'text':'5','confidence':.96}]
            if original!='5':candidates.append({'text':original,'confidence':.96})
            result,reads=color_cases.LevelColorTests().scenario(['',margin,'85','85','85'],candidates)
            self.assertEqual(reads,5)
        return result,reader.call_count

    def test_secondary_is_required_and_must_agree(self):
        result,calls=self.scenario()
        self.assertEqual((result[0]['level0'],calls),('85',1))
        for secondary in ('15','',RuntimeError('OCR unavailable')):
            result,calls=self.scenario(secondary=secondary)
            with self.subTest(secondary=secondary):
                self.assertEqual((result[0]['level0'],calls),('',1))

    def test_original_complete_or_tracked_margin_conflict_never_calls_fallback(self):
        for margin,original in (('90','5'),('15','75')):
            result,calls=self.scenario(margin=margin,original=original)
            with self.subTest(margin=margin,original=original):
                self.assertEqual((result[0]['level0'],calls),('',0))


if __name__=='__main__':unittest.main()
