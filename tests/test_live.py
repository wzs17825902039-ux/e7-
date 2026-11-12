import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from e7_assistant.live import EnhancementDriver, parse_amount, powder_checkbox_checked
from e7_assistant.tasks import TaskControl


class LiveParsingTests(unittest.TestCase):
    def test_white_border_is_not_checked(self):
        image = Image.new("RGB", (1280, 720), (24, 30, 30))
        ImageDraw.Draw(image).rectangle((968, 268, 984, 283), outline="white", width=2)
        self.assertFalse(powder_checkbox_checked(image))

    def test_green_mark_is_checked(self):
        image = Image.new("RGB", (1280, 720), (24, 30, 30))
        ImageDraw.Draw(image).line([(970, 275), (975, 280), (983, 270)], fill=(100, 203, 1), width=3)
        self.assertTrue(powder_checkbox_checked(image))

    def test_resource_ocr_punctuation_and_labels(self):
        self.assertEqual(parse_amount("数量96712,"), 96712)
        self.assertEqual(parse_amount("346734324,,"), 346734324)

    def test_ambiguous_resource_is_rejected(self):
        for text in ("9O12", "", "-12", "123(-4)"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_amount(text)
        self.assertEqual(parse_amount("123(-4)", preview_remaining=True), 123)

    def test_prepared_cost_and_count_are_reread_without_guessing(self):
        report = {"page": "enhancement", "issues": [], "identity": "weapon-1", "fields": {
            "rarity": "purple", "slot": "weapon", "level": 85, "enhancement": 0,
            "stats": {"speed": 3, "cdmg": 6, "hp_pct": 4}, "game_score": 21}}
        driver = EnhancementDriver(None, ".", TaskControl(), None, True)
        raw = {"gold": "346734324", "powder": "96696(-16)", "lesser_stone": "0",
               "greater_stone": "0", "epic_stone": "0", "cost": "2玩600", "registered_count": ""}
        with patch.object(driver, "_capture", return_value="frame.png"), \
                patch("e7_assistant.live.inspect_image", return_value=report), \
                patch("e7_assistant.live.read_regions", side_effect=[raw, {"cost": "25,600"},
                                                                     {"registered_count": "16"}]) as ocr:
            snapshot = driver._read(prepared=True)
        self.assertEqual(driver.last_cost, 25600)
        self.assertEqual(driver.last_count, "16")
        self.assertEqual(snapshot.resources["powder"], 96696)
        self.assertEqual(ocr.call_args_list[1].kwargs["language"], "en-US")

    def test_failed_numeric_reread_stops(self):
        report = {"page": "enhancement", "issues": [], "identity": "weapon-1", "fields": {
            "rarity": "purple", "slot": "weapon", "level": 85, "enhancement": 0,
            "stats": {"speed": 3, "cdmg": 6, "hp_pct": 4}, "game_score": 21}}
        driver = EnhancementDriver(None, ".", TaskControl(), None, True)
        raw = dict.fromkeys(("gold", "powder", "lesser_stone", "greater_stone", "epic_stone"), "0")
        raw.update(cost="2玩600", registered_count="")
        with patch.object(driver, "_capture", return_value="frame.png"), \
                patch("e7_assistant.live.inspect_image", return_value=report), \
                patch("e7_assistant.live.read_regions", side_effect=[raw, {"cost": "25O00"}]):
            with self.assertRaises(ValueError):
                driver._read(prepared=True)


if __name__ == "__main__":
    unittest.main()
