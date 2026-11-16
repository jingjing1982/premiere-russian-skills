import copy
import unittest
from frame_plan import plan

class FramePlanTests(unittest.TestCase):
    def setUp(self):
        self.data={'fps':50,'duration':200,'rows':[
            [0,0,0,100,50,150,'source.mp4'],[0,0,100,200,150,250,'source.mp4'],
            [1,0,0,100,50,150,'source.mp4'],[1,0,100,200,150,250,'source.mp4']],
            'cues':[[20,40],[150,180]],'protected':[[40,50]],'cuts':[[0,10],[60,80],[190,200]]}
    def test_head_middle_tail_source_offsets_and_manual_cut_preserved(self):
        result=plan(self.data)
        self.assertEqual(result['duration'],160)
        self.assertEqual(result['cues'],[[10,30],[120,150]])
        self.assertEqual([r[2:6] for r in result['rows'] if r[0]==0],
                         [[0,50,60,110],[50,70,130,150],[70,160,150,240]])
        self.assertEqual([r[1:] for r in result['rows'] if r[0]==0],
                         [r[1:] for r in result['rows'] if r[0]==1])
    def test_protected_handoff_cannot_be_removed(self):
        self.data['cuts']=[[45,55]]
        with self.assertRaises(ValueError):plan(self.data)
    def test_caption_overlap_rejected(self):
        self.data['cuts']=[[15,25]]
        with self.assertRaises(ValueError):plan(self.data)
    def test_whole_sequence_delete_rejected(self):
        self.data.update(cuts=[[0,200]],cues=[],protected=[])
        with self.assertRaises(ValueError):plan(self.data)
    def test_overlapping_deletions_rejected(self):
        self.data['cuts']=[[60,80],[70,90]]
        with self.assertRaises(ValueError):plan(self.data)
    def test_mismatched_audio_rejected(self):
        self.data['rows'][2][4:6]=[51,151]
        with self.assertRaises(ValueError):plan(self.data)
    def test_original_input_unchanged(self):
        before=copy.deepcopy(self.data);plan(self.data)
        self.assertEqual(self.data,before)

if __name__=='__main__':unittest.main()
