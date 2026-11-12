from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from PIL import Image,ImageDraw
from e7_assistant.batch_sale_vision import inspect_sale_confirmation,verify_sale_survivors
from e7_assistant.initial_cleanup import inspect_inventory
from e7_assistant.workflow_screen import inspect_screen


class LiveSaleResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets=Path(__file__).resolve().parents[1]/'docs/assets/sale-preview-2026-11-10'
        cls.after=inspect_screen(cls.assets/'after-twelve-sale.png')
        cls.items=[SimpleNamespace(token=str(i),locked=False,
                                   equipment=SimpleNamespace(enhancement_bonus=False,rarity='red')) for i in range(16)]
        cls.rejected={str(i) for i in range(16) if i not in (4,6,7,10)}

    def test_unequal_mixed_rewards_map_to_correct_materials(self):
        receipt=inspect_sale_confirmation(inspect_screen(self.assets/'twelve-sale-dialog.png'))
        self.assertEqual((receipt.count,receipt.gold,receipt.powder,receipt.jewelry_powder),(12,285880,226,35))

    def test_reversed_powder_icons_are_classified_by_image(self):
        screen=inspect_screen(self.assets/'four-sale-reversed-icons.png')
        receipt=inspect_sale_confirmation(screen)
        self.assertEqual((receipt.count,receipt.gold,receipt.powder,receipt.jewelry_powder),(4,102100,10,10))
        words=tuple({**w,'text':'11' if 595<=w['center'][0]<686 and 390<=w['center'][1]<425
                     else '22' if 703<=w['center'][0]<794 and 390<=w['center'][1]<425 else w['text']} for w in screen.words)
        unequal=inspect_sale_confirmation(replace(screen,words=words))
        self.assertEqual((unequal.powder,unequal.jewelry_powder),(11,22))

    def test_sparse_survivors_and_deleted_slots_are_verified(self):
        verify_sale_survivors(self.after,self.assets/'before-twelve-sale.png',self.items,self.rejected)
        with TemporaryDirectory() as directory,Image.open(self.after.source) as image:
            for box in ((110,160+129,185,182+129),(110,190,170,240)):
                changed=image.copy();ImageDraw.Draw(changed).rectangle(box,fill='black')
                path=Path(directory)/'changed.png';changed.save(path)
                with self.assertRaises(ValueError):
                    verify_sale_survivors(replace(self.after,source=str(path)),self.assets/'before-twelve-sale.png',self.items,self.rejected)

    def test_inventory_gold_has_independent_crop_consensus(self):
        state=inspect_inventory(inspect_screen(self.assets/'after-sale-inventory.png'))
        self.assertEqual((state.count,state.capacity,state.gold),(1037,1200,336544559))
