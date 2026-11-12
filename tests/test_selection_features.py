from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PIL import Image,ImageChops

from e7_assistant.workflow_screen import inspect_screen
from e7_assistant.inventory_vision import inspect_inventory
from e7_assistant.batch_selection import BatchSelectionDriver
from e7_assistant.selection_features import stationary_features

ROOT=Path(__file__).resolve().parents[1]


class SelectionFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=ROOT/'runs/full-workflow-1ea7be17'
        cls.before,cls.after=[inspect_inventory(inspect_screen(cls.folder/name),ignore_levels=True)
                              for name in ('workflow-0070.png','workflow-0074.png')]

    def test_live_animated_peer_has_stationary_distributed_features(self):
        proof=stationary_features(self.before['cards'][16],self.after['cards'][16])
        self.assertTrue(proof['matched'],proof)
        BatchSelectionDriver._verify_click(self.before,self.after,(2,3))

    def test_live_detail_header_reread_keeps_stationary_selected_card(self):
        folder=ROOT/'runs/full-workflow-2bb91d15'
        before,after=[inspect_inventory(inspect_screen(folder/name),ignore_levels=True)
                      for name in ('workflow-0028.png','workflow-0029.png')]
        BatchSelectionDriver._verify_unchanged({k:v for k,v in before.items() if k!='source'},
                                              {k:v for k,v in after.items() if k!='source'})

    def test_real_pixel_translation_is_not_a_stationary_feature_proof(self):
        old,new=self.before['cards'][16],deepcopy(self.after['cards'][16])
        box=old['tracking_box']
        with TemporaryDirectory() as folder:
            output=Path(folder)/'shifted.png'
            with Image.open(new['tracking_source']) as image:
                image=image.convert('RGB')
                image.paste(ImageChops.offset(image.crop(box),2,0),box)
                image.save(output)
            new['tracking_source']=str(output)
            self.assertFalse(stationary_features(old,new)['matched'])

    def test_different_art_or_blank_region_cannot_supply_identity(self):
        old=self.before['cards'][16]
        for blank in (False,True):
            with TemporaryDirectory() as folder:
                output=Path(folder)/'changed.png';new=deepcopy(self.after['cards'][16])
                with Image.open(new['tracking_source']) as image:
                    image=image.convert('RGB');box=old['tracking_box']
                    replacement=Image.new('RGB',(73,98),'gray') if blank else image.crop(self.before['cards'][0]['tracking_box'])
                    image.paste(replacement,box);image.save(output)
                new['tracking_source']=str(output)
                with self.subTest(blank=blank):self.assertFalse(stationary_features(old,new)['matched'])
