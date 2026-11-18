import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nonoverlap import schedule,validate,validate_srt,validate_turn_continuity
import speaker_timing as st
import gesture_timing as gt
from test_speaker_guard import fixture

def row(i,start,duration,pinned=False):
    return dict(group=i,start_ms=start,end_ms=start+duration,
                primary_anchor_id=f'a{i}' if pinned else None)

class NonOverlapTests(unittest.TestCase):
    def test_free_question_before_fixed_answer(self):
        rows=[row(1,1000,2000,True),row(2,4000,3000),row(3,6000,1000,True)]
        moves=schedule(rows,10000,20)
        self.assertEqual([r['start_ms'] for r in rows],[1000,3000,6000])
        self.assertEqual(moves[0]['shift_ms'],-1000)

    def test_free_reply_moves_forward_without_changing_duration(self):
        rows=[row(1,0,3000),row(2,2000,2000),row(3,8000,1000,True)]
        schedule(rows,10000,20)
        self.assertEqual([r['start_ms'] for r in rows],[0,3000,8000])
        self.assertEqual(rows[1]['end_ms']-rows[1]['start_ms'],2000)

    def test_cascade_fit_and_contact(self):
        rows=[row(1,0,1000,True),row(2,4000,2000),row(3,5000,2000),row(4,6000,1000,True)]
        schedule(rows,8000,20)
        self.assertEqual([r['start_ms'] for r in rows],[0,2000,4000,6000])
        validate(rows)

    def test_infeasible_pins_reject_without_partial_mutation(self):
        for rows in ([row(1,0,3000,True),row(2,2000,1000,True)],
                     [row(1,0,1000,True),row(2,1000,4000),row(3,3000,1000,True)],
                     [row(1,-20,1000,True)]):
            before=copy.deepcopy(rows)
            with self.assertRaises(ValueError):schedule(rows,10000,20)
            self.assertEqual(rows,before)

    def test_global_check_same_speaker_or_out_of_order(self):
        with self.assertRaises(ValueError):validate([row(1,2000,1000),row(2,1000,500)])
        with self.assertRaises(ValueError):validate_srt('1\n00:00:00,000 --> 00:00:02,000\nа\n甲\n\n2\n00:00:01,980 --> 00:00:03,000\nб\n乙\n')

    def test_both_exporters_block_even_if_solver_regresses(self):
        bad=dict(groups=[row(1,0,2000),row(2,1000,2000)],status='review_conflicts')
        for module in (st,gt):
            with tempfile.TemporaryDirectory() as d,patch.object(module,'solve',return_value=bad):
                with self.assertRaisesRegex(ValueError,'Overlap'):module.export({},d)
                self.assertEqual(list(Path(d).iterdir()),[])

    def test_timeline_capacity(self):
        rows=[row(1,8000,3000)]
        schedule(rows,10000,20)
        self.assertEqual(rows[0]['start_ms'],7000)
        with self.assertRaises(ValueError):schedule([row(1,0,11000)],10000,20)

    def test_explicit_anchor_exception_and_recomputed_error(self):
        p=fixture();p['anchors']=[dict(id='a',cue_id=2,char_offset=0,target_ru='Спасибо',time_ms=2000,evidence='synthetic')]
        p['approved_anchor_shifts']=[dict(anchor_id='a',shift_ms=500,authorization='synthetic explicit confirmation')]
        r=st.solve(p)
        self.assertEqual(r['groups'][1]['start_ms'],2500)
        self.assertEqual(r['anchors'][0]['marker_ms'],2000)
        self.assertEqual(r['anchors'][0]['error_ms'],500)
        p['approved_anchor_shifts'][0].pop('authorization')
        with self.assertRaisesRegex(ValueError,'explicit recorded'):st.solve(p)

    def test_unanchored_turn_backfills_end_instead_of_leaving_tail(self):
        p=fixture();r=st.solve(p)
        self.assertEqual(r['groups'][0]['end_ms'],2000)
        self.assertEqual(r['groups'][1]['end_ms'],4000)
        self.assertGreater(r['groups'][0]['start_ms'],0)

    def test_same_turn_multiple_groups_pack_without_gap(self):
        p=fixture();p['turns']=[dict(id='t1',speaker='s1',cue_ids=[1,2])]
        p['groups']=[dict(turn_id='t1',cue_ids=[1]),dict(turn_id='t1',cue_ids=[2])]
        p['speaker_review']['attribution'][1]['turn_id']='t1'
        p['speaker_review']['boundaries']=[]
        r=st.solve(p)
        self.assertEqual(r['groups'][0]['end_ms'],r['groups'][1]['start_ms'])
        self.assertEqual(r['groups'][1]['end_ms'],4000)

    def test_avoidable_gaps_blocked_but_one_fixed_seam_allowed(self):
        rows=[dict(row(1,0,1000),turn_id='t'),dict(row(2,2000,1000),turn_id='t')]
        with self.assertRaisesRegex(ValueError,'Avoidable'):validate_turn_continuity(rows)
        rows[0]['primary_anchor_id']='a';rows[1]['primary_anchor_id']='b'
        validate_turn_continuity(rows)
        rows.insert(1,dict(row(3,1500,200),turn_id='t'))
        with self.assertRaisesRegex(ValueError,'Fragmented'):validate_turn_continuity(rows)

if __name__=='__main__':unittest.main()
