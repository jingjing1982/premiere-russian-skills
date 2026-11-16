import argparse, json, tempfile, unittest
from pathlib import Path
from handoff import register,check

class HandoffTests(unittest.TestCase):
    def test_changed_srt_and_project_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);s=d/'a.srt';pr=d/'preview.prproj';h=d/'handoff.json'
            raw='1\n00:00:01,000 --> 00:00:02,000\nПривет.\n你好\n'
            s.write_text(raw,encoding='utf-8');pr.write_bytes(b'baseline')
            args=argparse.Namespace(srt=str(s),output=str(h),stage='ready-for-upload',sequence_uid='external-task-test',fps='unknown',revision='r1',confirmation='Synthetic fixture, not real user approval',project=str(pr),video=None,parent=None,unresolved=None)
            registered=register(args);self.assertIsNone(registered['fps']);self.assertEqual(check(h,s)['cue_count'],1)
            s.write_text(raw.replace('01,000','00,000'),encoding='utf-8')
            with self.assertRaises(ValueError):check(h,s)
            s.write_text(raw,encoding='utf-8');pr.write_bytes(b'changed')
            with self.assertRaises(ValueError):check(h,s)
    def test_record_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);s=d/'a.srt';h=d/'handoff.json';s.write_text('1\n00:00:01,000 --> 00:00:02,000\nПривет.\n你好\n',encoding='utf-8')
            a=argparse.Namespace(srt=str(s),output=str(h),stage='merged-review',sequence_uid='synthetic',fps='50',revision='r1',confirmation='Synthetic',project=None,video=None,parent=None,unresolved=None)
            register(a);original=h.read_bytes()
            with self.assertRaises(FileExistsError):register(a)
            self.assertEqual(h.read_bytes(),original)
if __name__=='__main__':unittest.main()
