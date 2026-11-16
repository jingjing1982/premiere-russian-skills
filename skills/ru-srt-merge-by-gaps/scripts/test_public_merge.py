import copy,json,hashlib,tempfile,unittest
from pathlib import Path
from test_speaker_guard import fixture
from speaker_timing import solve,export
from merge_checked import validate_source

class PublicMergeTests(unittest.TestCase):
    def test_source_rewrite_is_rejected_even_when_plan_review_is_rebound(self):
        p=fixture()
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);s=d/'source.json';plan=d/'plan.json';s.write_text(json.dumps({'cues':p['cues']},ensure_ascii=False),encoding='utf-8')
            p['source_snapshot_sha256']=hashlib.sha256(s.read_bytes()).hexdigest();plan.write_text(json.dumps(p),encoding='utf-8')
            validate_source(s,plan,'speaker')
            p['cues'][0]['zh']+='改字';plan.write_text(json.dumps(p),encoding='utf-8')
            with self.assertRaises(ValueError):validate_source(s,plan,'speaker')
    def test_duration_cap_override_is_enforced(self):
        p=fixture();p['max_duration_ms']=1
        with self.assertRaises(ValueError):solve(p)
    def test_string_fps_report_works(self):
        p=fixture();p['source']={'fps':'50'}
        with tempfile.TemporaryDirectory() as d:export(p,Path(d)/'result')
    def test_fractional_fps_is_not_falsely_labeled_drop_frame(self):
        p=fixture();p['source']={'fps':'30000/1001'}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'result';export(p,out)
            self.assertIn('非DF', (out/'定位报告.md').read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
