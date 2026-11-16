import copy
import tempfile
import unittest
from pathlib import Path
from gesture_timing import count, export as raw_export, solve as raw_solve
from speaker_guard import cue_fingerprint


def reviewed_fixture(plan):
    # These existing timing-only fixtures explicitly model one speaker.
    p=copy.deepcopy(plan)
    p['speaker_review']={'cue_sha256':cue_fingerprint(p['cues']),
      'evidence':[{'id':'test','kind':'user_confirmation','reference':'synthetic timing fixture','observation':'All fixture cues belong to one speaker'}],
      'attribution':[{'cue_id':c['id'],'turn_id':'test-turn','status':'confirmed','evidence_id':'test'} for c in p['cues']],
      'boundaries':[]}
    return p


def solve(plan):return raw_solve(reviewed_fixture(plan))
def export(plan,path):return raw_export(reviewed_fixture(plan),path)


def cue(i, start=0, end=10000, ru='Это жизнь.'):
    return dict(id=i,start_ms=start,end_ms=end,ru=ru,zh='这是生命。')


def anchor(i, c, time, **extra):
    return dict(id=i,cue_id=c,char_offset=0,target_ru='Это',time_ms=time,evidence='Test mapping',**extra)


class TimingTests(unittest.TestCase):
    def test_90s_split_backfills_without_moving_later_anchor(self):
        p={'cues':[cue(1,0,80000,'а '*416),cue(2,80000,140000)],
           'groups':[{'cue_ids':[1]},{'cue_ids':[2]}],
           'anchors':[anchor(1,2,150000)],'grid_ms':20}
        with tempfile.TemporaryDirectory() as d:
            paths,r=export(p,d)
            first,second=r['groups']
            self.assertEqual((first['start_ms'],first['end_ms']),(70000,150000))
            self.assertEqual(second['start_ms'],150000)
            self.assertEqual(first['duration_ms'],80000)
            self.assertEqual(r['anchors'][0]['error_ms'],0)
            blocks=paths[0].read_text('utf-8-sig').strip().split('\n\n')
            self.assertEqual(blocks[0].splitlines()[1].split(' --> ')[1],
                             blocks[1].splitlines()[1].split(' --> ')[0])
            self.assertEqual(blocks[0].splitlines()[2],p['cues'][0]['ru'])

    def test_chain_backfill_and_suffix_use_rounded_durations(self):
        p={'cues':[cue(i,i*10000,(i+1)*10000) for i in range(1,5)],
           'groups':[{'cue_ids':[i]} for i in range(1,5)],
           'anchors':[anchor(1,3,50000)],'grid_ms':20}
        r=solve(p)
        self.assertEqual([g['start_ms'] for g in r['groups']],
                         [48840,49420,50000,50580])
        self.assertTrue(all(j['output_gap_ms']==0 for j in r['joins']))
        self.assertEqual([g['cue_ids'] for g in r['groups']],[[1],[2],[3],[4]])

    def test_unanchored_continuous_chain_only_first_uses_source_start(self):
        p={'cues':[cue(1,1000,10000),cue(2,10000,20000)],
           'groups':[{'cue_ids':[1]},{'cue_ids':[2]}],'grid_ms':20}
        r=solve(p)['groups']
        self.assertEqual((r[0]['start_ms'],r[1]['start_ms']),(1000,1580))

    def test_positive_source_gap_is_not_closed_between_intervals(self):
        p={'cues':[cue(1,0,10000),cue(2,10001,20000)],
           'groups':[{'cue_ids':[1]},{'cue_ids':[2]}],
           'anchors':[anchor(1,2,15000)],'grid_ms':20}
        r=solve(p)
        self.assertEqual(r['groups'][0]['start_ms'],0)
        self.assertEqual(r['groups'][1]['start_ms'],15000)
        self.assertFalse(r['joins'][0]['same_source_interval'])
        self.assertGreater(r['joins'][0]['output_gap_ms'],0)

    def test_incompatible_chain_anchors_do_not_export_internal_gap(self):
        p={'cues':[cue(1),cue(2,10000,20000)],
           'groups':[{'cue_ids':[1]},{'cue_ids':[2]}],
           'anchors':[anchor(1,1,3000),anchor(2,2,20000)]}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'continuous placement conflicts'):
                export(p,d)
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_backfill_neighbor_conflict_does_not_move_single_anchor(self):
        p={'cues':[cue(1,0,10000,'а '*52),cue(2,10001,20000),cue(3,20000,30000)],
           'groups':[{'cue_ids':[1]},{'cue_ids':[2]},{'cue_ids':[3]}],
           'anchors':[anchor(1,3,10000)]}
        with self.assertRaisesRegex(ValueError,'neighbor capacity conflict'):solve(p)

    def test_fixed_chain_overflow_reported_without_moving_anchor(self):
        p={'cues':[cue(1),cue(2,10000,20000)],
           'groups':[{'cue_ids':[1]},{'cue_ids':[2]}],
           'anchors':[anchor(1,2,5000)],'video_end_ms':5200,'grid_ms':20}
        r=solve(p)
        self.assertEqual(r['groups'][1]['start_ms'],5000)
        self.assertEqual(r['groups'][0]['end_ms'],5000)
        self.assertEqual(r['video_overflow_ms'],380)
        self.assertEqual(r['status'],'review_conflicts')

    def test_count_and_unexpanded_numbers(self):
        self.assertEqual(count('две тысячи двадцать шесть'),7)
        with self.assertRaises(ValueError): count('2026')

    def test_exact_anchor_and_duration(self):
        p={'cues':[cue(1)],'groups':[{'cue_ids':[1]}], 'anchors':[anchor(1,1,3000)],'grid_ms':20}
        r=solve(p)
        self.assertEqual(r['groups'][0]['start_ms'],3000)
        self.assertEqual(r['groups'][0]['duration_ms'],580)
        self.assertEqual(r['anchors'][0]['error_ms'],0)

    def test_preserves_text_and_refuses_overwrite(self):
        p={'cues':[cue(1,ru='Это (жизнь).')],'groups':[{'cue_ids':[1]}]}
        with tempfile.TemporaryDirectory() as d:
            paths,r=export(p,d)
            self.assertIn('Это (жизнь).',paths[0].read_text('utf-8-sig'))
            self.assertIn(b'\r\n',paths[0].read_bytes())
            with self.assertRaises(ValueError): export(p,d)

    def test_any_positive_gap_is_boundary(self):
        p={'cues':[cue(1,0,1000),cue(2,1001,2000)],'groups':[{'cue_ids':[1,2]}]}
        with self.assertRaises(ValueError):solve(p)

    def test_missing_or_duplicate_cue(self):
        for grouped in ([1],[1,1,2]):
            with self.assertRaises(ValueError):
                solve({'cues':[cue(1),cue(2,10000,20000)],'groups':[{'cue_ids':grouped}]})

    def test_raw_and_speech_90(self):
        for c in (cue(1,0,90001),cue(1,ru='а '*469)):
            with self.assertRaises(ValueError):solve({'cues':[c],'groups':[{'cue_ids':[1]}]})
        r=solve({'cues':[cue(1,ru='а '*468)],'groups':[{'cue_ids':[1]}]})
        self.assertEqual(r['max_duration_ms'],90000)

    def test_compromise_and_primary_conflict(self):
        p={'cues':[cue(1)],'groups':[{'cue_ids':[1]}], 'anchors':[anchor(1,1,3000),anchor(2,1,5000)]}
        self.assertEqual(solve(p)['groups'][0]['start_ms'],4000)
        p['anchors'][1]['time_ms']=9000
        with self.assertRaises(ValueError):solve(p)
        p['groups'][0].update(primary_anchor_id=1,split_review='Same indivisible cue',primary_reason='Explicit gesture')
        r=solve(p)
        self.assertEqual(r['conflicting_anchor_ids'],[2])
        self.assertEqual(r['anchors'][1]['shift_ms'],6000)

    def test_neighbor_conflict_not_silent_anchor_push(self):
        p={'cues':[cue(1,0,10000,'а '*52),cue(2,10000,20000)],
           'groups':[{'cue_ids':[1]},{'cue_ids':[2]}], 'anchors':[anchor(1,2,1000)]}
        with self.assertRaises(ValueError):solve(p)

    def test_backwards_capacity_preserves_future_anchor(self):
        p={'cues':[cue(1),cue(2,10000,20000)],'groups':[{'cue_ids':[1]},{'cue_ids':[2]}],
           'anchors':[anchor(1,1,3000),anchor(2,2,3000,tolerance_ms=0)]}
        r=solve(p)['groups']
        self.assertEqual(r[1]['start_ms'],3000)
        self.assertEqual(r[0]['end_ms'],3000)

    def test_reading_expansion_and_target_prefix(self):
        c=cue(1,ru='2026. Это жизнь.')
        c['readings']=[dict(start=0,end=4,spoken='две тысячи двадцать шесть')]
        a=anchor(1,1,3000);a['char_offset']=6
        p={'cues':[c],'groups':[{'cue_ids':[1]}],'anchors':[a]}
        r=solve(p)
        self.assertEqual(r['anchors'][0]['prefix_syllables'],7)
        self.assertEqual(r['groups'][0]['ru'],c['ru'])

    def test_chinese_only_rejected(self):
        with self.assertRaises(ValueError):solve({'cues':[cue(1,ru='')],'groups':[{'cue_ids':[1]}]})

    def test_observed_window_required_and_video_overflow_reported(self):
        a=anchor(1,1,3000,window_ms=[2500,4000])
        p={'cues':[cue(1)],'groups':[{'cue_ids':[1]}],'anchors':[a],'video_end_ms':3000}
        with self.assertRaises(ValueError):solve(p)
        a['window_evidence']='Measured footage interval'
        r=solve(p)
        self.assertEqual(r['video_overflow_ms'],0)
        self.assertEqual(r['status'],'estimated_not_audio_verified')
        a['tolerance_ms']=0
        a['window_ms']=[3000,3000]
        r=solve(p)
        self.assertGreater(r['video_overflow_ms'],0)
        self.assertEqual(r['status'],'review_conflicts')

    def test_tail_cap_moves_previous_anchor_within_tolerance(self):
        p={'cues':[cue(1),cue(2,10000,20000)],'groups':[{'cue_ids':[1]},{'cue_ids':[2]}],
           'anchors':[anchor(1,1,3000),anchor(2,2,3500)],'video_end_ms':3800,'grid_ms':20}
        r=solve(p)
        self.assertEqual(r['video_overflow_ms'],0)
        self.assertEqual(r['groups'][-1]['end_ms'],3800)
        self.assertLessEqual(r['groups'][0]['end_ms'],r['groups'][1]['start_ms'])
        self.assertTrue(all(a['within_tolerance'] for a in r['anchors']))


if __name__=='__main__':unittest.main()
