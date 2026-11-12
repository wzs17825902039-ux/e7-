import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_inventory_traversal import audit


class InventoryAuditTests(unittest.TestCase):
    def run_audit(self, scope='ignored', missing=False):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            result = {'state': 'end_observed', 'selection_inputs': 0,
                      'resource_confirmations': 0,
                      'evidence': {'top_verified': True, 'end_verified': True,
                                   'covered_full_rows': 1, 'covered_rows': 1}}
            cards = [{'row': 0, 'column': column, 'level': None,
                      'rarity': 'purple', 'enhancement': 3,
                      'selected': False, 'known': True} for column in range(7)]
            if missing:
                cards[0]['enhancement'] = None
            page = {'source': 'fixture.png', 'level_scope': scope, 'cards': cards}
            event = {'kind': 'traversal_page', 'page': 0, 'image': 'fixture.png',
                     'evidence': {'relative_row': 0}, 'time': '2026-11-10T10:00:00'}
            for name, value in [('result.json', result), ('page-0000.json', page)]:
                (folder / name).write_text(json.dumps(value), encoding='utf8')
            (folder / 'events.jsonl').write_text(json.dumps(event), encoding='utf8')
            summary = audit(folder)
            self.assertEqual(json.loads(json.dumps(summary)),
                             json.loads((folder / 'audit.json').read_text(encoding='utf8')))
            return summary

    def test_ignored_levels_do_not_claim_all_fields_read(self):
        result = self.run_audit()
        self.assertTrue(result['required_fields_verified'])
        self.assertFalse(result['all_fields_verified'])
        self.assertEqual(result['unread_level_count'], 7)

    def test_required_missing_field_still_fails(self):
        self.assertFalse(self.run_audit(missing=True)['required_fields_verified'])

    def test_strict_mode_still_requires_level(self):
        self.assertFalse(self.run_audit(scope='verified')['required_fields_verified'])
