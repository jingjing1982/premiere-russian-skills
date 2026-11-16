import csv
import json
from pathlib import Path
import tempfile
import unittest
from openpyxl import Workbook
import srt_to_heygen_csv as c


class ConversionTests(unittest.TestCase):
    def test_literal_source_ok_is_preserved_without_relaxing_unknown_language(self):
        self.srt.write_text('1\n00:00:00,000 --> 00:00:02,000\nПонятно.\nOK\n',encoding='utf-8')
        report=self.produce()
        self.assertEqual(report['literal_source_ok_cues'],['1'])
        with self.csv.open(encoding='utf-8-sig',newline='') as f:
            row=list(csv.DictReader(f))[0]
        self.assertEqual(row['original_subtitles'],'OK')
        self.assertEqual(row['translated_subtitles'],'Понятно.')
        self.assertTrue(c.verify_csv(self.srt,self.csv,self.xlsx)['verified'])
        with self.assertRaises(ValueError):
            c.parse_srt('1\n00:00:00,000 --> 00:00:02,000\nПонятно.\nUnknown English sentence\n')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.srt = self.root / 'source.srt'
        self.xlsx = self.root / 'source.xlsx'
        self.csv = self.root / 'output.csv'
        self.srt.write_text('1\n00:00:00,000 --> 00:00:02,000\nПривет, «мир»!\n你好\n\n'
                            '2\n00:00:10,000 --> 00:00:12,000\nСпасибо.\n谢谢\n', encoding='utf-8')
        book = Workbook(); ws = book.active; ws.append(c.HEADER)
        ws.append(['speaker_A', '00:00:00.000', '00:00:09.000', 'source', 'source', None])
        ws.append(['speaker_B', '00:00:09.000', '00:00:20.000', 'source', 'source', None])
        book.save(self.xlsx); book.close()

    def produce(self):
        return c.convert(self.srt, self.csv, self.xlsx)

    def corrupt(self, change):
        with self.csv.open(encoding='utf-8-sig', newline='') as f: rows = list(csv.reader(f))
        change(rows)
        with self.csv.open('w', encoding='utf-8-sig', newline='') as f: csv.writer(f).writerows(rows)

    def test_correct_conversion(self):
        report = self.produce()
        self.assertEqual([a['speaker'] for a in report['speaker_assignments']], ['speaker_A', 'speaker_B'])
        self.assertEqual(c.verify_csv(self.srt, self.csv, self.xlsx)['speaker_empty_count'], 0)

    def test_blank_unknown_and_wrong_known_speaker_rejected(self):
        self.produce()
        for label in ['', 'speaker_invented', 'speaker_B']:
            with self.subTest(label=label):
                self.corrupt(lambda rows: rows[1].__setitem__(0, label))
                with self.assertRaises(ValueError): c.verify_csv(self.srt, self.csv, self.xlsx)

    def test_bad_build_not_published(self):
        from unittest.mock import patch
        real = c.serialize
        def faulty(rows, header):
            rows[0][0] = ''
            return real(rows, header)
        with patch.object(c, 'serialize', faulty):
            with self.assertRaises(ValueError): self.produce()
        self.assertFalse(self.csv.exists())

    def test_changed_time_text_and_missing_row_rejected(self):
        self.produce(); original = self.csv.read_bytes()
        for change in [lambda r: r[1].__setitem__(1, '00:00:00.020'),
                       lambda r: r[1].__setitem__(4, 'Изменено.'), lambda r: r.pop()]:
            self.csv.write_bytes(original); self.corrupt(change)
            with self.assertRaises(ValueError): c.verify_csv(self.srt, self.csv, self.xlsx)

    def test_offset_before_assignment(self):
        report = c.convert(self.srt, self.csv, self.xlsx, source_start_ms=10000, offset_ms=10000)
        self.assertEqual(report['speaker_assignments'][0]['speaker'], 'speaker_A')
        with self.assertRaises(ValueError):
            c.verify_csv(self.srt, self.csv, self.xlsx, source_start_ms=10000, offset_ms=9980)

    def test_crossing_boundary_rejected(self):
        with self.assertRaises(ValueError): c.convert(self.srt, self.csv, self.xlsx, source_end_ms=1000)
        self.assertFalse(self.csv.exists())

    def cross_speaker_source(self):
        self.srt.write_text('1\n00:00:08,000 --> 00:00:11,000\nПривет. Спасибо.\n你好 谢谢\n',encoding='utf-8')

    def review(self,classification):
        audit=c.audit_speakers(self.srt,self.xlsx)
        path=self.root/'review.json'
        path.write_text(json.dumps(dict(context=audit['context'],reviews=[dict(cue='1',classification=classification,speaker='speaker_A',
          evidence=dict(kind='user_confirmation',reference='synthetic test decision',observation='Test-only single speaker, shifted timing'))])),encoding='utf-8')
        return path

    def test_cross_speaker_default_blocks_upload_and_reports_candidate(self):
        self.cross_speaker_source()
        audit=c.audit_speakers(self.srt,self.xlsx)
        self.assertFalse(audit['speaker_gate_passed'])
        self.assertEqual(audit['blocking_cues'][0]['cue'],'1')
        with self.assertRaisesRegex(ValueError,'content gate blocked'):self.produce()
        self.assertFalse(self.csv.exists())

    def test_confirmed_mixed_speakers_never_pass_midpoint(self):
        self.cross_speaker_source()
        for status in ('mixed_speakers','unresolved'):
            with self.assertRaisesRegex(ValueError,'content gate blocked'):
                c.convert(self.srt,self.csv,self.xlsx,speaker_review=self.review(status))
        self.assertFalse(self.csv.exists())

    def test_reviewed_timing_shift_preserves_text_and_time(self):
        self.cross_speaker_source();review=self.review('timing_only')
        result=c.convert(self.srt,self.csv,self.xlsx,speaker_review=review)
        self.assertTrue(result['speaker_gate_passed'])
        self.assertEqual(result['speaker_assignments'][0]['speaker'],'speaker_A')
        self.assertTrue(c.verify_csv(self.srt,self.csv,self.xlsx,speaker_review=review)['verified'])
        with self.assertRaises(ValueError):c.verify_csv(self.srt,self.csv,self.xlsx)

    def test_stale_review_rejected(self):
        self.cross_speaker_source();review=self.review('timing_only')
        self.srt.write_text(self.srt.read_text(encoding='utf-8').replace('Привет.','Здравствуйте.'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Stale'):c.convert(self.srt,self.csv,self.xlsx,speaker_review=review)

    def test_short_second_voice_not_hidden_by_half_second_tolerance(self):
        self.srt.write_text('1\n00:00:08,800 --> 00:00:11,000\nПривет. Спасибо.\n你好 谢谢\n',encoding='utf-8')
        audit=c.audit_speakers(self.srt,self.xlsx)
        self.assertEqual(audit['speaker_assignments'][0]['case'],'2/3')
        self.assertFalse(audit['speaker_gate_passed'])

    def test_alternating_bilingual_lines(self):
        self.srt.write_text('1\n00:00:00,000 --> 00:00:02,000\nПривет.\n你好\nСпасибо.\n谢谢\n',encoding='utf-8')
        self.produce()
        with self.csv.open(encoding='utf-8-sig',newline='') as f: row=list(csv.DictReader(f))[0]
        self.assertEqual(row['translated_subtitles'], 'Привет.\nСпасибо.')
        self.assertEqual(row['original_subtitles'], '你好\n谢谢')

    def test_batch_coverage_and_missing_or_duplicate_parts(self):
        manifest = self.root / 'parts.json'
        one = dict(source_start_ms=0,source_end_ms=10000,offset_ms=0,template_xlsx=str(self.xlsx),destination=str(self.root/'one.csv'))
        two = dict(source_start_ms=10000,source_end_ms=None,offset_ms=10000,template_xlsx=str(self.xlsx),destination=str(self.root/'two.csv'))
        for parts in [[one], [one,dict(one,destination=str(self.root/'duplicate.csv')),two]]:
            manifest.write_text(json.dumps(dict(source=str(self.srt),parts=parts)),encoding='utf-8')
            with self.assertRaises(ValueError): c.convert_parts(manifest)
            self.assertFalse((self.root/'one.csv').exists())
        manifest.write_text(json.dumps(dict(source=str(self.srt),parts=[one,two])),encoding='utf-8')
        result=c.convert_parts(manifest)
        self.assertEqual(result['full_source_count'],2)


if __name__ == '__main__':
    unittest.main()
