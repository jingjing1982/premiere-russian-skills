"""Parse, assemble and verify Chinese/Russian SRT without translating it."""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys


TIME = re.compile(r'^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})([ \t]+-->[ \t]+)(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$')


@dataclass
class Cue:
    index: str
    timestamp: str
    lines: list

    @property
    def chinese(self):
        return ' '.join(self.lines)


def decode(path):
    data = Path(path).read_bytes()
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise ValueError(f'Unsupported text encoding: {path}')


def parse(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip('\n')
    if not text:
        raise ValueError('Empty SRT')
    cues = []
    seen = set()
    for n, block in enumerate(re.split(r'\n[ \t]*\n+', text), 1):
        lines = block.split('\n')
        if len(lines) < 3 or not re.fullmatch(r'\d+', lines[0]):
            raise ValueError(f'Malformed SRT block {n}')
        index, timestamp = lines[:2]
        m = TIME.fullmatch(timestamp)
        if not m:
            raise ValueError(f'Invalid timestamp in cue {index}: {timestamp}')
        a = tuple(map(int, m.group(1, 2, 3, 4)))
        b = tuple(map(int, m.group(6, 7, 8, 9)))
        if a >= b:
            raise ValueError(f'Start must precede end in cue {index}')
        if int(index) in seen:
            raise ValueError(f'Duplicate cue number: {index}')
        if not any(line.strip() for line in lines[2:]):
            raise ValueError(f'Empty cue: {index}')
        seen.add(int(index))
        cues.append(Cue(index, timestamp, lines[2:]))
    return cues


def read_cues(path):
    text, encoding = decode(path)
    return parse(text), encoding


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(data)


def verify(source_path, output_path):
    source, _ = read_cues(source_path)
    data = Path(output_path).read_bytes()
    if not data.startswith(b'\xef\xbb\xbf'):
        raise ValueError('Output must use UTF-8 BOM')
    body = data[3:].decode('utf-8')
    if '\n' in body.replace('\r\n', '') or '\r' in body.replace('\r\n', ''):
        raise ValueError('Output must use CRLF consistently')
    if not body.endswith('\r\n\r\n'):
        raise ValueError('Output must end with a cue separator')
    output = parse(body)
    if len(source) != len(output):
        raise ValueError(f'Cue count changed: {len(source)} -> {len(output)}')
    for src, out in zip(source, output):
        if src.index != out.index or src.timestamp != out.timestamp:
            raise ValueError(f'Number or timestamp changed near {src.index}')
        if len(out.lines) != 2:
            raise ValueError(f'Expected Russian/Chinese two lines in cue {src.index}')
        ru, cn = out.lines
        if not ru.strip() or ru != ru.strip() or '  ' in ru or '\t' in ru or '\u00a0' in ru:
            raise ValueError(f'Invalid Russian whitespace in cue {src.index}')
        if re.search(r'[\u3400-\u9fff]', ru) or not re.search(r'[А-Яа-яЁё]', ru):
            raise ValueError(f'Russian line contains Chinese or no Cyrillic in cue {src.index}')
        if re.search(r'<br\s*/?>', ru, re.I):
            raise ValueError(f'HTML line break in cue {src.index}')
        if cn != src.chinese:
            raise ValueError(f'Chinese changed beyond joining lines in cue {src.index}')
    return {'cues': len(output), 'numbers_and_timestamps_unchanged': True,
            'chinese_matches_source': True, 'text_lines_per_cue': 2,
            'encoding': 'UTF-8 BOM', 'newlines': 'CRLF',
            'linguistic_review_required': True,
            'sha256': hashlib.sha256(data).hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    subs = ap.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'build', 'check'):
        sub = subs.add_parser(name)
        sub.add_argument('--source', required=True, type=Path)
        sub.add_argument('--output', required=True, type=Path)
        if name == 'build':
            sub.add_argument('--translations', required=True, type=Path)
    args = ap.parse_args()
    if args.source.resolve() == args.output.resolve():
        raise ValueError('Source and output must be different files')
    if args.command == 'check':
        report = verify(args.source, args.output)
    else:
        cues, encoding = read_cues(args.source)
        if args.command == 'prepare':
            report = {'source': str(args.source.resolve()), 'source_encoding': encoding,
                      'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
                      'cue_count': len(cues),
                      'cues': [{'index': c.index, 'timestamp': c.timestamp,
                                'chinese': c.chinese} for c in cues]}
            write_new(args.output, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            report = {'prepared_cues': len(cues), 'output': str(args.output)}
        else:
            translations = json.loads(args.translations.read_text(encoding='utf-8-sig'))
            if not isinstance(translations, list) or len(translations) != len(cues):
                raise ValueError('Translations must be a JSON array matching all source cues')
            blocks = []
            for c, t in zip(cues, translations):
                if not isinstance(t, dict) or str(t.get('index')) != c.index:
                    raise ValueError(f'Translation cue mismatch near {c.index}')
                ru = t.get('ru')
                if not isinstance(ru, str) or '\n' in ru or '\r' in ru:
                    raise ValueError(f'Russian must be one physical line in cue {c.index}')
                blocks.append('\r\n'.join((c.index, c.timestamp, ru, c.chinese)))
            data = b'\xef\xbb\xbf' + ('\r\n\r\n'.join(blocks) + '\r\n\r\n').encode('utf-8')
            # Verify the complete in-memory candidate before writing the deliverable.
            candidate = parse(data[3:].decode('utf-8'))
            for c, out in zip(cues, candidate):
                ru = out.lines[0]
                if not ru.strip() or ru != ru.strip() or '  ' in ru or '\t' in ru or '\u00a0' in ru:
                    raise ValueError(f'Invalid Russian whitespace in cue {c.index}')
                if re.search(r'[\u3400-\u9fff]', ru) or not re.search(r'[А-Яа-яЁё]', ru) or re.search(r'<br\s*/?>', ru, re.I):
                    raise ValueError(f'Invalid Russian line in cue {c.index}')
            write_new(args.output, data)
            report = verify(args.source, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
