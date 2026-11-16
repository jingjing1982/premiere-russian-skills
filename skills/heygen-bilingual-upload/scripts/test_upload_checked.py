import argparse,json,tempfile,unittest,subprocess,sys
from pathlib import Path
from openpyxl import Workbook
from handoff import register

class PublicUploadTests(unittest.TestCase):
    def test_overlong_srt_never_published_as_final_upload(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);s=d/'source.srt';h=d/'handoff.json';x=d/'template.xlsx';out=d/'upload.csv';report=d/'report.json'
            s.write_text('1\n00:00:00,000 --> 00:01:40,000\nЭто жизнь.\n这是生命。\n',encoding='utf-8')
            w=Workbook();ws=w.active;ws.append(['speaker','start_time','end_time','original_subtitles','translated_subtitles','notes']);ws.append(['speaker_0','00:00:00.000','00:03:00.000','这是生命。','','']);w.save(x)
            register(argparse.Namespace(srt=str(s),output=str(h),stage='ready-for-upload',sequence_uid='synthetic',fps='unknown',revision='r1',confirmation='Synthetic fixture, not actual approval',project=None,video=None,parent=None,unresolved=None))
            p=subprocess.run([sys.executable,str(Path(__file__).with_name('upload_checked.py')),str(s),str(out),'--template-xlsx',str(x),'--handoff',str(h),'--report',str(report)],capture_output=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(out.exists());self.assertFalse(report.exists())
if __name__=='__main__':unittest.main()
