import importlib.util
from pathlib import Path
import unittest


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('PIL', 'cv2', 'numpy')),
                     '需要vision依赖')
class SlotVisionTests(unittest.TestCase):
    def test_initial_three_or_four_stats_classify_quality_but_later_four_do_not_override_purple(self):
        from PIL import Image
        from e7_assistant.slot_vision import inspect_slots
        root=Path(__file__).resolve().parents[1]
        with Image.open(root/'docs/assets/user-workflow-2026-11-09/17-batch-target.png') as image:
            image=image.convert('RGB').resize((1661,933))
        known={i:rarity for i,rarity in enumerate((
            'purple','red','red','purple','purple','purple','purple','red',
            'purple','red','purple','red','purple','purple','purple','red'))}
        initial=inspect_slots(image,registered_rarities=known,initial_indices=range(16))
        self.assertEqual([s['rarity'] for s in initial],list(known.values()))
        self.assertTrue(all(s['state']=='occupied' for s in initial))
        # 模拟紫装后续解锁第四条；同批登记仍为紫装，不再按四条改判。
        changed=image.copy()
        changed.paste(image.crop((461,296,491,321)),(144,296))
        self.assertEqual(inspect_slots(changed,registered_rarities=known)[0]['rarity'],'purple')
        with self.assertRaisesRegex(ValueError,'初始副词条数量'):
            inspect_slots(changed,registered_rarities=known,initial_indices={0})
        missing=image.copy();missing.paste((0,0,0),(144,296,174,321))
        self.assertEqual(inspect_slots(missing,registered_rarities=known,initial_indices={0})[0]['state'],'unknown')

    def test_blank_or_occluded_frame_is_unknown_not_empty(self):
        from PIL import Image
        from e7_assistant.slot_vision import inspect_slots
        for color in ('black', 'white', '#262626'):
            result = inspect_slots(Image.new('RGB', (1661, 933), color))
            self.assertTrue(all(slot['state'] == 'unknown' for slot in result))

    def test_real_occupied_cards_are_never_empty(self):
        from PIL import Image
        from e7_assistant.slot_vision import inspect_slots
        root = Path(__file__).resolve().parents[1] / 'docs/assets/user-workflow-2026-11-09'
        for name in ('17-batch-target.png', '18-batch-result.png', '19-deselect-rejected.png'):
            with Image.open(root / name) as image:
                result = inspect_slots(image.convert('RGB').resize((1661, 933)))
            self.assertEqual([slot['state'] for slot in result], ['occupied'] * 16)

    def test_tail_batch_keeps_ambiguous_slot_unknown(self):
        from PIL import Image
        from e7_assistant.slot_vision import inspect_slots
        path = Path(__file__).resolve().parents[1] / 'docs/assets/user-workflow-2026-11-09/25-batch-lock.png'
        with Image.open(path) as image:
            result = inspect_slots(image.convert('RGB'))
        self.assertEqual(result[0]['state'], 'occupied')
        self.assertEqual([slot['state'] for slot in result[1:15]], ['empty'] * 14)
        self.assertEqual(result[15]['state'], 'unknown')

    def test_wrong_geometry_is_rejected(self):
        from PIL import Image
        from e7_assistant.slot_vision import inspect_slots
        with self.assertRaises(ValueError):
            inspect_slots(Image.new('RGB', (500, 300)))
