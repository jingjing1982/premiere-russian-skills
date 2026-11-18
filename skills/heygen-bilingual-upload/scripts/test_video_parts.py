import csv,json,tempfile,unittest
from pathlib import Path
from openpyxl import Workbook
import srt_to_heygen_csv as c

class VideoPartsTests(unittest.TestCase):
    def workbook(self,p):
        w=Workbook();s=w.active;s.append(c.HEADER)
        s.append(['speaker_0','00:00:00.000','00:00:10.000','','',''])
        s.append(['speaker_1','00:00:12.000','00:00:15.000','','','']);w.save(p)
    def test_review_can_correct_unflagged_missing_short_voice(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);s=d/'source.srt';x=d/'export.xlsx';o=d/'out.csv';self.workbook(x)
            s.write_text('1\n00:00:01,000 --> 00:00:02,000\nСпасибо.\n谢谢\n',encoding='utf-8')
            a=c.audit_speakers(s,x);self.assertFalse(a['blocking_cues'])
            review=d/'review.json';review.write_text(json.dumps({'context':a['context'],'reviews':[{'cue':'1','classification':'excel_label_error','speaker':'speaker_1','evidence':{'kind':'user_confirmation','reference':'Synthetic explicit test confirmation','observation':'Short offscreen host sentence omitted by Excel'}}]}),encoding='utf-8')
            c.convert(s,o,x,speaker_review=review)
            self.assertEqual(c.verify_csv(s,o,x,speaker_review=review)['speaker_assignments'][0]['speaker'],'speaker_1')
            with self.assertRaises(ValueError):c.verify_csv(s,o,x)
    def test_video_overlap_offset_is_not_cumulative_duration(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);s=d/'source.srt';x=d/'one.xlsx';y=d/'two.xlsx';self.workbook(x);self.workbook(y)
            s.write_text('1\n00:00:00,000 --> 00:00:01,000\nПривет.\n你好\n\n2\n00:00:10,500 --> 00:00:11,500\nСпасибо.\n谢谢\n',encoding='utf-8')
            m=d/'parts.json';m.write_text(json.dumps({'source':str(s),'parts':[
                {'source_start_ms':0,'source_end_ms':10000,'offset_ms':0,'template_xlsx':str(x),'destination':str(d/'one.csv')},
                {'source_start_ms':10000,'source_end_ms':None,'offset_ms':9980,'template_xlsx':str(y),'destination':str(d/'two.csv')}]}),encoding='utf-8')
            result=c.convert_parts(m);self.assertTrue(result['verified']);self.assertEqual(result['full_source_count'],2)
            with (d/'two.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            self.assertEqual(rows[0]['start_time'],'00:00:00.520');self.assertEqual(rows[0]['end_time'],'00:00:01.520')
            with self.assertRaises(ValueError):c.verify_csv(s,d/'two.csv',y,source_start_ms=10000,offset_ms=10000)
if __name__=='__main__':unittest.main()
