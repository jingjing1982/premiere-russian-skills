import copy
import tempfile
import unittest
from pathlib import Path
import speaker_timing as st
import gesture_timing as gt
from speaker_guard import cue_fingerprint


def fixture():
    cues=[dict(id=1,start_ms=0,end_ms=2000,ru='Добро пожаловать.',zh='欢迎。'),
          dict(id=2,start_ms=2000,end_ms=4000,ru='Спасибо.',zh='谢谢。')]
    review=dict(cue_sha256=cue_fingerprint(cues),
      evidence=[dict(id='test',kind='user_confirmation',reference='synthetic two-speaker fixture',observation='cue 1 host, cue 2 guest')],
      attribution=[dict(cue_id=i,turn_id=f't{i}',status='confirmed',evidence_id='test') for i in (1,2)],
      boundaries=[dict(before_cue=1,after_cue=2,translation_status='separable',evidence_id='test')])
    return dict(mode='speaker_first_anchor',cues=cues,turns=[dict(id=f't{i}',speaker=f's{i}',cue_ids=[i]) for i in (1,2)],
                groups=[dict(turn_id=f't{i}',cue_ids=[i]) for i in (1,2)],speaker_review=review)


class GuardTests(unittest.TestCase):
    def test_two_people_stay_separate_in_both_modes(self):
        for solve in (st.solve,gt.solve):
            result=solve(fixture())
            self.assertEqual([g['cue_ids'] for g in result['groups']],[[1],[2]])
            self.assertTrue(result['speaker_attribution_checked'])

    def test_cross_person_group_rejected_in_both_modes(self):
        p=fixture();p['groups']=[dict(turn_id='t1',cue_ids=[1,2])]
        for solve in (st.solve,gt.solve):
            with self.assertRaisesRegex(ValueError,'crosses reviewed speaker'):solve(p)

    def test_wrong_original_turn_plan_rejected(self):
        p=fixture();p['turns']=[dict(id='t1',speaker='host',cue_ids=[1,2])]
        with self.assertRaisesRegex(ValueError,'disagrees'):st.solve(p)

    def test_missing_stale_and_unresolved_do_not_export(self):
        variants=[]
        p=fixture();p.pop('speaker_review');variants.append(p)
        p=fixture();p['cues'][0]['ru']='Изменено.';variants.append(p)
        for status in ('unresolved','mixed'):
            p=fixture();p['speaker_review']['attribution'][0]['status']=status;variants.append(p)
        for p in variants:
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):st.export(p,d)
                self.assertEqual(list(Path(d).iterdir()),[])

    def test_cross_person_translation_or_missing_boundary_rejected(self):
        for change in ('cross_speaker_sentence','unresolved','missing'):
            p=fixture()
            if change=='missing':p['speaker_review']['boundaries']=[]
            else:p['speaker_review']['boundaries'][0]['translation_status']=change
            with self.assertRaises(ValueError):st.solve(p)

    def test_text_guess_is_not_audio_evidence(self):
        p=fixture();p['speaker_review']['evidence'][0]['kind']='text_guess'
        with self.assertRaises(ValueError):st.solve(p)


if __name__=='__main__':unittest.main()
