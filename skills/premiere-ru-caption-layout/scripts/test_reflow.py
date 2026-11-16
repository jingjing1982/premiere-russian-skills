"""Regression cases for exact text measurement, per-cue widths and timing."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import reflow_srt as r


class ReflowTests(unittest.TestCase):
    def test_preferred_examples(self):
        for text, tail in [
            ('Мне кажется, бедствия берут начало в трёх ядах человеческого ума.', 'ядах человеческого ума.'),
            ('Большое спасибо кхенпо Содаргье за глубокое объяснение темы бедствий.', 'объяснение темы бедствий.')]:
            self.assertEqual(r.best_two_lines(text, 60, 2)[1], tail)

    def test_spaces_punctuation_and_nbsp_are_measured_verbatim(self):
        text='Очень  длинная первая часть: слова из\u00a0трёх слов.'
        seen=[]
        def measure(s): seen.append(s); return len(s)
        result=r.best_two_lines(text, 42, 2, measure)
        self.assertIsNotNone(result)
        self.assertEqual(' '.join(result), text)
        self.assertTrue(any('Очень  длинная' in s for s in seen))
        self.assertTrue(any('\u00a0' in s for s in seen))

    def test_punctuation_is_not_a_tail_word(self):
        text='очень длинная первая замечательная часть о достоинствах Будды —'
        self.assertEqual(r.best_two_lines(text, 55, 2)[1], 'о достоинствах Будды —')

    def test_manifest_unknown_cue_and_gap_audit_preserve_times(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); src=d/'in.srt';out=d/'out.srt';report=d/'report.csv';manifest=d/'widths.json'
            text='Очень  длинная первая строка из этих слов.'
            src.write_text(f'1\n00:00:00,000 --> 00:00:01,000\n{text}\n中文原样\n\n2\n00:00:02,000 --> 00:00:03,000\nОставить как есть.\n中文\n\n3\n00:00:06,001 --> 00:00:07,000\nСпасибо!\n谢谢\n',encoding='utf-8')
            manifest.write_text(json.dumps({'input_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'cues':{'1':{'max_width':29,'profile':'narrow'},'3':{'max_width':29,'profile':'narrow'}}}),encoding='utf-8')
            subprocess.run([sys.executable,str(Path(r.__file__)),str(src),str(out),'--report',str(report),'--cue-widths',str(manifest)],check=True,capture_output=True)
            blocks=out.read_text(encoding='utf-8').split('\n\n')
            self.assertEqual(blocks[0].splitlines()[1],'00:00:00,000 --> 00:00:01,000')
            self.assertEqual(' '.join(blocks[0].splitlines()[2:-1]),text)
            self.assertIn('00:00:02,000 --> 00:00:03,000\nОставить как есть.',blocks[1])
            with report.with_name('report_layout.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
            self.assertEqual(rows[1]['action'],'unknown_width_preserved')
            self.assertTrue(all(x['PR_visual_status']=='unverified' for x in rows))
            with report.with_name('report_gaps.csv').open(encoding='utf-8-sig') as f: gaps=list(csv.DictReader(f))
            self.assertEqual([g['处理'] for g in gaps], ['open_le_2s', 'keep_gt_2s'])
            self.assertEqual(gaps[0]['前条结束时间'], '00:00:01,000')
            self.assertEqual(gaps[0]['后条开始时间'], '00:00:02,000')

    def test_gap_boundaries_overlaps_and_closed_pairs_are_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);src=d/'in.srt';out=d/'out.srt';report=d/'report.csv'
            times=[('00:00:00,000','00:00:01,000'),
                   ('00:00:01,001','00:00:02,000'),
                   ('00:00:04,000','00:00:05,000'),
                   ('00:00:07,001','00:00:09,000'),
                   ('00:00:08,000','00:00:10,000'),
                   ('00:00:10,000','00:00:11,000')]
            text='Мне кажется, бедствия берут начало в трёх ядах человеческого ума.'
            raw=('\ufeff'+'\r\n\r\n'.join(f'{i}\r\n{a} --> {b}\r\n{text}\r\n中文，原样！'
                  for i,(a,b) in enumerate(times,1))+'\r\n').encode('utf8')
            src.write_bytes(raw)
            result=subprocess.run([sys.executable,str(Path(r.__file__)),str(src),str(out),'--report',str(report),'--max-chars','60'],check=True,capture_output=True,text=True)
            self.assertEqual(src.read_bytes(),raw)
            source=src.read_text(encoding='utf-8-sig').strip().split('\n\n')
            output=out.read_text(encoding='utf-8-sig').strip().split('\n\n')
            self.assertEqual(len(source),len(output))
            self.assertNotEqual(source[0],output[0])  # Layout really changed.
            for a,b in zip(source,output):
                self.assertEqual(r.signature(a),r.signature(b))
                self.assertEqual(a.splitlines()[1],b.splitlines()[1])
            with report.with_name('report_gaps.csv').open(encoding='utf-8-sig') as f: gaps=list(csv.DictReader(f))
            self.assertEqual([g['间隙秒数'] for g in gaps],['0.001','2.000','2.001','-1.000'])
            self.assertEqual([g['处理'] for g in gaps],['open_le_2s','open_le_2s','keep_gt_2s','overlap_report_only'])
            self.assertEqual([(g['前一条序号'],g['后一条序号']) for g in gaps],[('1','2'),('2','3'),('3','4'),('4','5')])
            self.assertIn('timing changes 0',result.stdout)

    def test_legacy_close_gaps_flag_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);src=d/'in.srt';src.write_text('1\n00:00:00,000 --> 00:00:01,000\nСпасибо!\n谢谢\n',encoding='utf8')
            before=src.read_bytes()
            result=subprocess.run([sys.executable,str(Path(r.__file__)),str(src),str(d/'out.srt'),'--report',str(d/'report.csv'),'--close-gaps'],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(src.read_bytes(),before)
            self.assertEqual(set(d.iterdir()),{src})

    def test_report_source_collision_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);src=d/'in.srt';src.write_text('1\n00:00:00,000 --> 00:00:01,000\nСпасибо!\n谢谢\n',encoding='utf8')
            before=src.read_bytes()
            result=subprocess.run([sys.executable,str(Path(r.__file__)),str(src),str(d/'out.srt'),'--report',str(src)],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(src.read_bytes(),before)
            self.assertEqual(set(d.iterdir()),{src})

    def test_existing_destinations_and_generated_path_collisions_are_rejected(self):
        for which in ['out.srt','report.csv','report_gaps.csv','report_layout.csv','collision']:
            with self.subTest(which=which), tempfile.TemporaryDirectory() as d:
                d=Path(d);src=d/'in.srt';src.write_text('1\n00:00:00,000 --> 00:00:01,000\nСпасибо!\n谢谢\n',encoding='utf8')
                if which!='collision': (d/which).write_bytes(b'preserve existing bytes')
                before={p.name:p.read_bytes() for p in d.iterdir()}
                out=d/('report_gaps.csv' if which=='collision' else 'out.srt')
                result=subprocess.run([sys.executable,str(Path(r.__file__)),str(src),str(out),'--report',str(d/'report.csv')],capture_output=True)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual({p.name:p.read_bytes() for p in d.iterdir()},before)


if __name__=='__main__': unittest.main()
