import unittest

from e7_assistant.inventory_scan import scroll_distance


def view(top=200,pitch=133):
    return {'cards':[{'row':row,'column':col,'center':(188+99*col,top+50+row*pitch)}
                     for row in range(3) for col in range(7)]}


class ScrollDistanceTests(unittest.TestCase):
    def test_long_run_corrects_sampling_error_without_losing_complete_rows(self):
        # 实测手势距离约比内容位移大11px；模拟每次±3px采样误差及持续2px偏差。
        for errors in ((-3,0,3),(2,)):
            top=161
            for index in range(150):
                distance=scroll_distance(view(top))
                self.assertTrue(60<=distance<=160)
                actual_motion=distance-11+errors[index%len(errors)]
                top+=133-actual_motion
                self.assertTrue(197<=top<=203)
                self.assertLessEqual(top+2*133+98,604)

    def test_target_position_uses_measured_pitch_and_bounded_gesture(self):
        self.assertEqual(scroll_distance(view(200)),144)
        self.assertEqual(scroll_distance(view(161)),105)
        self.assertEqual(scroll_distance(view(260,pitch=120)),160)

    def test_incomplete_or_invalid_geometry_never_produces_a_gesture(self):
        for case in ('two_rows','partial','duplicate_column','nan','bool','reversed','mixed_y','pitch','outside'):
            report=view()
            if case=='two_rows':report['cards']=report['cards'][:14]
            if case=='partial':report['cards'].pop()
            if case=='duplicate_column':report['cards'][1]['column']=0
            if case=='nan':report['cards'][0]['center']=(188,float('nan'))
            if case=='bool':report['cards'][0]['center']=(188,True)
            if case=='reversed':report['cards'][1]['center']=(100,250)
            if case=='mixed_y':report['cards'][1]['center']=(287,253)
            if case=='pitch':report=view(pitch=110)
            if case=='outside':report=view(top=300)
            with self.subTest(case=case),self.assertRaises(ValueError):scroll_distance(report)
