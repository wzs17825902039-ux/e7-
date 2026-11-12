import unittest

from e7_assistant.vision import parse_panel


def line(text, x, y, width=40):
    # 以原图位置构造外部OCR返回的文字框，模拟空格/全角符号。
    return {"words": [{"text": text, "x": x * 3, "y": y * 3,
                       "width": width * 3, "height": 15 * 3}]}


def panel():
    return [line("强化装备", 65, 20, 95), line("英雄铠甲", 140, 110, 70),
            line("85", 45, 99, 20), line("+9", 101, 84, 28),
            line("装备分数", 41, 405, 72), line("52（+29）", 280, 405, 72),
            line("防御力（1）", 41, 278, 85), line("16%（+8%）", 264, 278, 90),
            line("速度（2）", 41, 303, 85), line("9（+6）", 293, 303, 47),
            line("暴击率", 41, 328, 55), line("3%", 275, 328, 28),
            line("强化+12时获得", 41, 353, 130)]


class VisionBoundaries(unittest.TestCase):
    def test_current_values_are_not_cumulative_increments(self):
        report = parse_panel(panel())
        self.assertEqual(report["fields"]["game_score"], 52)
        self.assertEqual(report["fields"]["stats"], {"def_pct": 16, "speed": 9, "crit": 3})
        self.assertEqual(report["fields"]["roll_counts"], {"def_pct": 1, "speed": 2})
        self.assertFalse(report["automation_ready"])

    def test_wrong_page_does_not_produce_equipment(self):
        result = parse_panel([line("背包", 65, 20, 50)])
        self.assertEqual(result["page"], "unknown")
        self.assertEqual(result["fields"], {})

    def test_unreadable_badge_is_not_assumed_zero(self):
        rows = [r for r in panel() if r["words"][0]["text"] != "+9"]
        self.assertIsNone(parse_panel(rows)["fields"]["enhancement"])

    def test_missing_percentage_does_not_become_valid_crit(self):
        rows = panel()
        rows[-2] = line("3", 275, 328, 15)
        report = parse_panel(rows)
        self.assertNotIn("crit", report["fields"]["stats"])
        self.assertTrue(report["issues"])

    def test_missing_score_is_unknown(self):
        rows = [r for r in panel() if r["words"][0]["text"] != "52（+29）"]
        report = parse_panel(rows)
        self.assertIsNone(report["fields"]["game_score"])
        self.assertTrue(report["issues"])


if __name__ == "__main__":
    unittest.main()
