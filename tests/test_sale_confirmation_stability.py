from dataclasses import replace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image,ImageDraw
from e7_assistant.batch_sale_vision import SaleConfirmation,sale_confirmation_unchanged


class SaleConfirmationStabilityTests(unittest.TestCase):
    def test_real_mixed_sale_ignores_only_animated_backdrop(self):
        root=Path(__file__).resolve().parents[1]/'docs/assets'
        before,after=[self.proof(root/name) for name in ('mixed-sale-frame-a.png','mixed-sale-frame-b.png')]
        self.assertNotEqual(before.digest,after.digest)
        self.assertTrue(sale_confirmation_unchanged(before,after))

    def proof(self,path):
        with Image.open(path) as image:
            digest=hashlib.sha256(image.convert('RGB').crop((400,140,880,570)).tobytes()).hexdigest()
        return SaleConfirmation(12,306300,772,digest,str(path),355)

    def pair(self):
        root=Path(__file__).resolve().parents[1]/'runs/selected-inventory-resume-56c85dc5'
        return self.proof(root/'workflow-0067.png'),self.proof(root/'workflow-0068.png')

    def test_real_dialog_two_level_render_noise_is_stable(self):
        before,after=self.pair()
        self.assertNotEqual(before.digest,after.digest)
        self.assertTrue(sale_confirmation_unchanged(before,after))

    def test_every_income_field_must_match_even_with_same_digest(self):
        before,after=self.pair()
        for field in ('count','gold','powder','jewelry_powder'):
            self.assertFalse(sale_confirmation_unchanged(before,replace(before,**{field:getattr(before,field)+1})))

    def test_changed_dialog_pixels_cannot_be_accepted_by_same_income(self):
        before,after=self.pair()
        with TemporaryDirectory() as directory,Image.open(after.image) as image:
            ImageDraw.Draw(image).rectangle((620,395,635,410),fill='black')
            path=Path(directory)/'changed.png';image.save(path)
            self.assertFalse(sale_confirmation_unchanged(before,self.proof(path)))

    def test_each_transaction_foreground_region_remains_strict(self):
        before,after=self.pair()
        for box in ((600,170,680,200),(510,250,750,280),
                    (620,395,635,410),(700,510,790,550)):
            with self.subTest(box=box),TemporaryDirectory() as directory,Image.open(after.image) as image:
                ImageDraw.Draw(image).rectangle(box,fill='black')
                path=Path(directory)/'changed.png';image.save(path)
                self.assertFalse(sale_confirmation_unchanged(before,self.proof(path)))

    def test_missing_or_forged_image_proof_is_rejected(self):
        before,after=self.pair()
        self.assertFalse(sale_confirmation_unchanged(before,replace(after,image='missing-sale-proof.png')))
        self.assertFalse(sale_confirmation_unchanged(before,replace(after,digest='forged')))


if __name__=='__main__':unittest.main()
