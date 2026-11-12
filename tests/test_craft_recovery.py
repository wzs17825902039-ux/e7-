from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock,patch
import json
import unittest

from e7_assistant.craft_recovery import settle_full_craft
from e7_assistant.disposal_guard import CraftSessionGuard
from e7_assistant.forge_loop import ForgePreview
from e7_assistant.tasks import Ledger,Limits,TaskControl,Journal
from e7_assistant.workflow import WorkflowOptions


class CraftRecoveryTests(unittest.TestCase):
    def test_full_session_reconciles_actual_material_before_continuing_without_crafting(self):
        for case in ('valid','unobserved_commit','missing_full','wrong_material'):
            with self.subTest(case=case),TemporaryDirectory() as root:
                runs=Path(root)/'runs';original=runs/'original';original.mkdir(parents=True)
                guard=CraftSessionGuard(runs/'craft-pending','test')
                operation=guard.begin('craft',{'resources':{'craft_material':5000},
                    'cost':{'craft_material':400},'slot':'helmet','count':10,'source_index':0},{},original)
                events=[{'kind':'craft_session_started','operation_id':operation},
                        {'kind':'craft_commit_intent'},{'kind':'craft_result_observed','accounting':{'confirmed_attempts':1}},
                        {'kind':'craft_commit_intent'},{'kind':'craft_result_observed','accounting':{'confirmed_attempts':2}}]
                if case=='unobserved_commit':events.pop()
                if case!='missing_full':events.append({'kind':'workflow_screen','page':'inventory_full'})
                events.append({'kind':'finished','state':'failed','steps':0,'spent':dict(Ledger(Limits()).spent)})
                (original/'events.jsonl').write_text('\n'.join(map(json.dumps,events)),encoding='utf8')
                task=SimpleNamespace(craft_guard=guard,enhancement_guard=Mock(),disposal_guard=Mock(),
                    navigator=SimpleNamespace(directory=runs/'new',last_image='live.png',read=Mock()),
                    ledger=Ledger(Limits(craft_material=2000)),options=WorkflowOptions(),
                    control=TaskControl(),journal=Journal(runs/'new'),completed_batches=0,
                    enhancement_statistics=SimpleNamespace(snapshot=lambda:{}),finish_inventory_round=Mock())
                material=4199 if case=='wrong_material' else 4200
                preview=ForgePreview({'craft_material':material},{'craft_material':400},'helmet',10,0,'live.png')
                with patch('e7_assistant.craft_recovery.LiveForgeLoop') as forge:
                    forge.return_value.settlement_preview.return_value=preview
                    forge.return_value.preview.return_value=preview
                    if case in ('unobserved_commit','missing_full'):
                        with self.assertRaises(ValueError):settle_full_craft(task)
                        forge.assert_not_called()
                    else:
                        result=settle_full_craft(task)
                        self.assertEqual(result['state'],'complete' if case=='valid' else 'failed')
                        if case=='valid':
                            task.finish_inventory_round.assert_called_once()
                            self.assertEqual((task.ledger.steps,task.ledger.spent['craft_material']),(2,800))
                        else:task.finish_inventory_round.assert_not_called()
                self.assertEqual(guard.read() is None,case=='valid')
