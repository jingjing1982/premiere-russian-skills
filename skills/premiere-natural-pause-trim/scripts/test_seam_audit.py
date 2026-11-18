import copy
import unittest
from seam_audit import audit


class SeamAuditTests(unittest.TestCase):
    def setUp(self):
        # Actual source endpoints: 1054.94, 1064.36, 1064.48 seconds at 50 fps.
        self.data = dict(fps=50, duration=54000, cuts=[[52747, 53218]], shots=[
            dict(id='outgoing', start=52000, end=53224, evidence='reviewed outgoing speaker'),
            dict(id='incoming', start=53224, end=54000, evidence='reviewed questioner')])

    def test_six_frame_tail_is_unresolved(self):
        r = audit(self.data)
        self.assertFalse(r['passed'])
        self.assertEqual(r['short_fragments'][0]['source'], [53218, 53224])
        self.assertEqual(len(r['unresolved']), 1)

    def test_cut_to_scene_boundary_removes_tail(self):
        self.data['cuts'][0][1] = 53224
        r = audit(self.data)
        self.assertTrue(r['passed'])
        self.assertFalse(r['short_fragments'])

    def test_unreviewed_image_range_cannot_pass(self):
        self.data['shots'] = self.data['shots'][1:]
        r = audit(self.data)
        self.assertFalse(r['passed'])
        self.assertTrue(r['coverage_issues'])

    def test_short_shot_can_be_kept_with_evidence(self):
        self.data['reviews'] = {'outgoing:53218:53224':
            dict(action='retain', reason='Explicitly protected reaction', evidence='Reviewed full reaction')}
        self.assertTrue(audit(self.data)['passed'])
        self.assertEqual(len(audit(self.data)['short_fragments']), 1)

    def test_prior_short_original_shot_is_not_auto_deleted(self):
        self.data['cuts'] = [[52600, 52700]]
        self.data['shots'] = [
            dict(id='a', start=52000, end=52700, evidence='reviewed'),
            dict(id='short-original', start=52700, end=52710, evidence='reviewed'),
            dict(id='b', start=52710, end=54000, evidence='reviewed')]
        r = audit(self.data)
        self.assertTrue(r['passed'])
        self.assertEqual(r['fragments'][1]['shot_id'], 'short-original')

    def test_frame_ranges_and_input_preserved(self):
        before = copy.deepcopy(self.data)
        audit(self.data)
        self.assertEqual(self.data, before)
        self.data['cuts'] = [[52747, 53218], [53200, 53250]]
        with self.assertRaises(ValueError):
            audit(self.data)


if __name__ == '__main__':
    unittest.main()
