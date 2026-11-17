import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import preflight
import srt_tool as s


class SubtitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / '中文.srt'
        self.out = self.root / '俄中.srt'
        self.tr = self.root / '译文.json'
        self.src.write_bytes('3\n00:00:01,000 --> 00:00:03,000\n今天我们\n继续学习\n\n8\n00:00:03,000 --> 00:00:04,000\n这个内容。\n'.encode('utf-8'))
        self.trans = [{'index': '3', 'ru': 'Сегодня мы продолжим изучать'},
                      {'index': '8', 'ru': 'эту тему.'}]

    def build(self, translations=None, output=None):
        self.tr.write_text(json.dumps(self.trans if translations is None else translations, ensure_ascii=False), 'utf-8')
        return subprocess.run([sys.executable, str(Path(s.__file__)), 'build', '--source', str(self.src),
                               '--translations', str(self.tr), '--output', str(output or self.out)], capture_output=True)

    def test_roundtrip_nonconsecutive_numbers_and_exact_chinese(self):
        original = self.src.read_bytes()
        self.assertEqual(self.build().returncode, 0)
        self.assertTrue(s.verify(self.src, self.out)['chinese_matches_source'])
        self.assertEqual(self.src.read_bytes(), original)
        self.assertEqual(s.read_cues(self.out)[0][0].lines[1], '今天我们 继续学习')
        self.assertTrue(self.out.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_reject_overwrite(self):
        self.out.write_bytes(b'preserve me')
        self.assertNotEqual(self.build().returncode, 0)
        self.assertEqual(self.out.read_bytes(), b'preserve me')

    def test_reject_source_as_output(self):
        original = self.src.read_bytes()
        self.assertNotEqual(self.build(output=self.src).returncode, 0)
        self.assertEqual(self.src.read_bytes(), original)

    def test_missing_translation(self):
        self.assertNotEqual(self.build(self.trans[:1]).returncode, 0)
        self.assertFalse(self.out.exists())

    def test_reordered_translation(self):
        self.assertNotEqual(self.build(self.trans[::-1]).returncode, 0)

    def test_invalid_russian_rejected_before_write(self):
        for ru in ['第一句', 'Привет\nдруг', 'Привет<br>друг', 'Привет  друг', '']:
            with self.subTest(ru=ru):
                self.assertNotEqual(self.build([{'index': '3', 'ru': ru}, self.trans[1]]).returncode, 0)
                self.assertFalse(self.out.exists())

    def test_tampered_output_detected(self):
        self.assertEqual(self.build().returncode, 0)
        original = self.out.read_bytes()
        for old, new in [('这个内容。', '这个内容'), ('00:00:04,000', '00:00:05,000'), ('\r\n8\r\n', '\r\n9\r\n')]:
            self.out.write_bytes(original.replace(old.encode('utf-8'), new.encode('utf-8')))
            with self.assertRaises(ValueError):
                s.verify(self.src, self.out)

    def test_invalid_source(self):
        for text in ['1\n00:00:01,000 --> 00:00:01,000\n中文', '1\n00:00:01,000 --> 00:00:02,000\n',
                     '1\n00:00:01,000 --> 00:00:02,000\n甲\n\n1\n00:00:02,000 --> 00:00:03,000\n乙']:
            with self.assertRaises(ValueError):
                s.parse(text)

    def test_gb18030(self):
        self.src.write_bytes(self.src.read_text('utf-8').encode('gb18030'))
        self.assertEqual(self.build().returncode, 0)

    def test_overlapping_times_preserved(self):
        self.src.write_bytes(self.src.read_bytes().replace(b'00:00:03,000 --> 00:00:04,000', b'00:00:02,000 --> 00:00:04,000'))
        self.assertEqual(self.build().returncode, 0)
        self.assertTrue(s.verify(self.src, self.out)['numbers_and_timestamps_unchanged'])

    def test_bundled_glossary(self):
        self.assertEqual(preflight.inspect()['entry_count'], 800)

    def test_explicit_missing_glossary_does_not_fallback(self):
        with self.assertRaises(FileNotFoundError):
            preflight.inspect(self.root / 'missing.txt')

    def test_custom_glossary(self):
        p = self.root / 'custom.txt'
        p.write_text('佛法：Дхарма\n', 'utf-8')
        self.assertTrue(preflight.inspect(p)['custom_glossary'])


if __name__ == '__main__':
    unittest.main()
