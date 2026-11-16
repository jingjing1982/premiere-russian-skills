import unittest,tempfile,subprocess,json,sys
from pathlib import Path
from plan_gaps import plan

class GapCapTests(unittest.TestCase):
    def test_internal_tail_and_head_policy(self):
        p=plan([[50,100],[1100,1200],[1400,1500]],2500,50)
        self.assertEqual(p['execution_order'],[[2000,2500],[350,850]])
        self.assertEqual(p['cues_after'],[[50,100],[600,700],[900,1000]])
        self.assertEqual(p['duration_after'],1500)
    def test_exact_cap_unchanged_and_custom_cap(self):
        self.assertEqual(plan([[0,100],[600,700]],1200,50)['execution_order'],[])
        self.assertEqual(plan([[0,100],[600,700]],1200,50,4)['cap_frames'],200)
    def test_failed_cli_leaves_no_empty_output(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);src=d/'in.json';out=d/'out.json';src.write_text(json.dumps({'cues':[[0,100],[1000,1100]],'duration':1500,'fps':'30000/1001'}))
            r=subprocess.run([sys.executable,str(Path(__file__).with_name('plan_gaps.py')),str(src),str(out)],capture_output=True)
            self.assertNotEqual(r.returncode,0);self.assertFalse(out.exists())
if __name__=='__main__':unittest.main()
