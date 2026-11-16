"""Package final bilingual SRT using a required, inspected HeyGen Excel export.

Supports only the known six-field schema. Header matching does not establish
the video's identity or verify successful upload. No timing/text adjustments.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile

HEADER = ['speaker', 'start_time', 'end_time', 'original_subtitles',
          'translated_subtitles', 'notes']
TIME = r'\d{2}:[0-5]\d:[0-5]\d[,.]\d{3}'
TIMELINE = re.compile(rf'({TIME})[ \t]+-->[ \t]+({TIME})')
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
CYR = re.compile(r'[А-Яа-яЁё]')


def milliseconds(value):
    if not isinstance(value, str) or not re.fullmatch(TIME, value):
        raise ValueError(f'Unsupported time value: {value!r}')
    h, m, s, milli = map(int, re.split(r'[:,.]', value))
    return ((h * 60 + m) * 60 + s) * 1000 + milli


def read_turns(template):
    from openpyxl import load_workbook
    book = load_workbook(template['path'], read_only=True, data_only=True, keep_links=False)
    records = []
    try:
        ws = book[template['sheet']]
        for number, values in enumerate(ws.iter_rows(min_row=template['header_row'] + 1,
                                                    values_only=True), template['header_row'] + 1):
            record = dict(zip(template['fields'], values))
            fields = [record.get(k) for k in ('speaker', 'start_time', 'end_time')]
            if all(v is None for v in fields):
                continue
            speaker, start, end = fields
            if not isinstance(speaker, str) or not speaker.strip():
                raise ValueError(f'Missing/invalid Excel speaker on row {number}')
            start, end = milliseconds(start), milliseconds(end)
            if end <= start:
                raise ValueError(f'Invalid Excel speaker interval on row {number}')
            records.append((start, end, speaker, number))
    finally:
        book.close()
    records.sort(key=lambda r: r[0])
    turns = []
    for start, end, speaker, number in records:
        if turns and turns[-1]['speaker'] == speaker:
            turns[-1]['end_ms'] = end
            turns[-1]['excel_rows'].append(number)
        else:
            turns.append(dict(speaker=speaker, start_ms=start, end_ms=end, excel_rows=[number]))
    if not turns:
        raise ValueError('No Excel speaker intervals')
    return turns


def assign_speaker(start, end, turns):
    candidates = [t for t in turns if t['start_ms'] - 500 <= start and end <= t['end_ms'] + 500]
    involved = [t for t in turns if max(start, t['start_ms']) < min(end, t['end_ms'])]
    if len(candidates) == 1:
        chosen = candidates[0]
        case = 1 if chosen['start_ms'] <= start and end <= chosen['end_ms'] else '2/3'
        return dict(speaker=chosen['speaker'], case=case, involved_speakers=[chosen['speaker']])
    # Doubled integer midpoint avoids any rounding at half-millisecond boundaries.
    mid2 = start + end
    at_mid = [t for t in turns if 2*t['start_ms'] <= mid2 <= 2*t['end_ms']]
    case = 4
    if not at_mid:
        case = 5
        distances = [max(2*t['start_ms']-mid2, mid2-2*t['end_ms'], 0) for t in turns]
        nearest = min(distances)
        at_mid = [t for t, d in zip(turns, distances) if d == nearest]
    labels = list(dict.fromkeys(t['speaker'] for t in at_mid))
    if len(labels) != 1:
        raise ValueError(f'Unresolved midpoint overlap/equidistant speakers: {labels}')
    return dict(speaker=labels[0], case=case, midpoint_ms=mid2/2,
                involved_speakers=list(dict.fromkeys(t['speaker'] for t in involved)),
                tolerance_candidates=[t['speaker'] for t in candidates])


def parse_srt(text):
    # Normalize only structural newlines, never Unicode text or whitespace.
    lines = text.removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    rows, ids, multiline, reversed_ids, source_ok_ids = [], [], [], [], []
    i = 0
    while i < len(lines):
        if lines[i] == '':
            i += 1
            continue
        cue_id = lines[i]
        if not re.fullmatch(r'\d+', cue_id) or i + 1 >= len(lines):
            raise ValueError(f'Invalid cue header at physical line {i + 1}')
        match = TIMELINE.fullmatch(lines[i + 1])
        if not match:
            raise ValueError(f'Invalid timecode: cue {cue_id}')
        i += 2
        body = []
        while i < len(lines) and lines[i] != '':
            body.append(lines[i])
            i += 1
        if len(body) < 2:
            raise ValueError(f'Expected at least two text lines: cue {cue_id}')
        translation, chinese = ' '.join(body[:-1]), body[-1]
        if len(body) > 2:
            multiline.append(cue_id)
            if (len(body) % 2 == 0
                    and all(CYR.search(s) and not HAN.search(s) for s in body[::2])
                    and all(HAN.search(s) and not CYR.search(s) for s in body[1::2])):
                translation, chinese = '\n'.join(body[::2]), '\n'.join(body[1::2])
            elif any(HAN.search(s) for s in body[:-1]):
                raise ValueError(f'Ambiguous multilingual lines: cue {cue_id}')
        elif HAN.search(translation) and not HAN.search(chinese) and CYR.search(chinese) and not CYR.search(translation):
            translation, chinese = chinese, translation
            reversed_ids.append(cue_id)
        # A Chinese source track can contain the literal utterance "OK".
        # Keep it verbatim in the second/source field; this exception does not
        # accept arbitrary non-Han text or infer a speaker identity.
        source_ok = (len(body) == 2 and chinese == 'OK'
                     and CYR.search(translation) and not HAN.search(translation))
        if source_ok:
            source_ok_ids.append(cue_id)
        if (not HAN.search(chinese) and not source_ok) or not CYR.search(translation):
            raise ValueError(f'Russian/Chinese assignment requires review: cue {cue_id}')
        rows.append(['', match[1].replace(',', '.'), match[2].replace(',', '.'),
                     chinese, translation, ''])
        ids.append(cue_id)
    if not rows:
        raise ValueError('No subtitle cues found')
    return rows, {'language': 'Russian', 'count': len(rows), 'cue_ids': ids,
                  'multiline_cues': multiline, 'reversed_cues': reversed_ids,
                  'literal_source_ok_cues': source_ok_ids}


def inspect_template(path, sheet=None):
    from openpyxl import load_workbook
    path = Path(path)
    if path.suffix.lower() not in ('.xlsx', '.xlsm'):
        raise ValueError('Read the actual Excel format; supported here: .xlsx/.xlsm')
    raw = path.read_bytes()
    book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    matches = []
    try:
        if sheet is not None and sheet not in book.sheetnames:
            raise ValueError('Requested worksheet does not exist')
        for ws in book.worksheets:
            if sheet is not None and ws.title != sheet:
                continue
            for number, values in enumerate(ws.iter_rows(min_row=1, max_row=30,
                                                          values_only=True), 1):
                fields = list(values)
                while fields and fields[-1] is None:
                    fields.pop()
                if len(fields) == len(HEADER) and all(isinstance(x, str) for x in fields) and set(fields) == set(HEADER):
                    matches.append({'sheet': ws.title, 'header_row': number,
                                    'fields': fields})
    finally:
        book.close()
    if len(matches) != 1:
        raise ValueError(f'Expected one verified six-field header; found {len(matches)}. Inspect the real workbook/mapping; do not fabricate a template.')
    return {**matches[0], 'path': str(path.resolve()),
            'sha256': hashlib.sha256(raw).hexdigest()}


def serialize(rows, header):
    def quote(value):
        return '"' + value.replace('"', '""') + '"'
    records = [','.join(header)]
    ordered = []
    for row in rows:
        values = dict(zip(HEADER, row))
        ordered.append([values[field] for field in header])
        records.append(','.join(values[field] if field in ('start_time', 'end_time')
                                else quote(values[field]) for field in header))
    result = '\r\n'.join(records) + '\r\n'
    parsed = list(csv.reader(io.StringIO(result, newline='')))
    if parsed != [header] + ordered:
        raise ValueError('CSV round-trip mismatch')
    return result


def shifted_time(value, offset_ms):
    value = milliseconds(value) - offset_ms
    if value < 0:
        raise ValueError('Confirmed part offset produces a negative time')
    h, value = divmod(value, 3600000)
    m, value = divmod(value, 60000)
    s, milli = divmod(value, 1000)
    return f'{h:02}:{m:02}:{s:02}.{milli:03}'


def source_part(source, source_start_ms=0, source_end_ms=None, offset_ms=0):
    if any(type(v) is not int or v < 0 for v in (source_start_ms, offset_ms)):
        raise ValueError('Part boundaries/offset must be nonnegative integer milliseconds')
    if source_end_ms is not None and (type(source_end_ms) is not int or source_end_ms <= source_start_ms):
        raise ValueError('Invalid part end')
    rows, report = parse_srt(Path(source).read_bytes().decode('utf-8-sig'))
    if len(set(report['cue_ids'])) != len(rows):
        raise ValueError('Duplicate SRT cue identifiers')
    selected, ids = [], []
    for ident, row in zip(report['cue_ids'], rows):
        start, end = milliseconds(row[1]), milliseconds(row[2])
        for edge in (source_start_ms, source_end_ms):
            if edge is not None and min(start, end) < edge < max(start, end):
                raise ValueError(f'Cue {ident} crosses part boundary; no automatic splitting')
        if start < source_start_ms or (source_end_ms is not None and start >= source_end_ms):
            continue
        row[1:3] = [shifted_time(v, offset_ms) for v in row[1:3]]
        selected.append(row)
        ids.append(ident)
    if not selected:
        raise ValueError('Part contains no SRT cues')
    report.update(count=len(selected), cue_ids=ids,
                  multiline_cues=[i for i in report['multiline_cues'] if i in ids],
                  reversed_cues=[i for i in report['reversed_cues'] if i in ids],
                  literal_source_ok_cues=[i for i in report['literal_source_ok_cues'] if i in ids])
    return selected, report


def audit_speakers(source, template_xlsx, sheet=None, source_start_ms=0,
                   source_end_ms=None, offset_ms=0, speaker_review=None):
    template = inspect_template(template_xlsx, sheet)
    turns = read_turns(template)
    rows, meta = source_part(source, source_start_ms, source_end_ms, offset_ms)
    context = dict(source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                   template_sha256=template['sha256'], source_start_ms=source_start_ms,
                   source_end_ms=source_end_ms, offset_ms=offset_ms)
    reviews = {}
    if speaker_review:
        document = json.loads(Path(speaker_review).read_text(encoding='utf-8-sig'))
        if document.get('context') != context:
            raise ValueError('Stale speaker content review: source/template/part differs')
        for entry in document.get('reviews', []):
            ident = str(entry['cue'])
            if ident in reviews or ident not in meta['cue_ids']:
                raise ValueError('Duplicate/unknown content review cue')
            reviews[ident] = entry
    assignments, blocked = [], []
    for ident, row in zip(meta['cue_ids'], rows):
        a = assign_speaker(milliseconds(row[1]), milliseconds(row[2]), turns)
        # Containment tolerance can choose one label even while a short second
        # voice overlaps. Screen the actual intervals independently of that choice.
        start, end = milliseconds(row[1]), milliseconds(row[2])
        a['involved_speakers'] = list(dict.fromkeys(t['speaker'] for t in turns
            if max(start, t['start_ms']) < min(end, t['end_ms'])))
        suspect = len(a['involved_speakers']) > 1 or a['case'] == 5 or len(a.get('tolerance_candidates', [])) > 1
        r = reviews.get(ident)
        state = 'no_cross_speaker_flag'
        if r:
            state = r.get('classification', 'unresolved')
            e = r.get('evidence', {})
            valid_evidence = (e.get('kind') in ('audio_review', 'visual_dialogue_review', 'user_confirmation')
                              and str(e.get('reference', '')).strip() and str(e.get('observation', '')).strip())
            if state in ('mixed_speakers', 'unresolved'):
                blocked.append(dict(cue=ident, reason=state))
            elif state in ('timing_only', 'excel_label_error') and valid_evidence:
                if r.get('speaker') not in {t['speaker'] for t in turns}:
                    raise ValueError(f'Content review speaker absent from Excel: {ident}')
                a['automatic_speaker'] = a['speaker']
                a['speaker'] = r['speaker']
                a['content_review'] = r
            else:
                blocked.append(dict(cue=ident, reason='missing_valid_content_evidence'))
        elif suspect:
            state = 'unreviewed'
            blocked.append(dict(cue=ident, reason='speaker_boundary_needs_content_review'))
        assignments.append(dict(cue=ident, start_time=row[1], end_time=row[2],
                                 content_status=state, **a))
    return dict(context=context, count=len(rows), speaker_assignments=assignments,
                blocking_cues=blocked, speaker_gate_passed=not blocked,
                scope='Excel boundary screening and recorded content reviews; not automatic voice verification')


def verify_csv(source, destination, template_xlsx, sheet=None,
               source_start_ms=0, source_end_ms=None, offset_ms=0, speaker_review=None):
    """Read source SRT, real Excel and written CSV afresh; never trust the build report."""
    template = inspect_template(template_xlsx, sheet)
    turns = read_turns(template)
    audit = audit_speakers(source, template_xlsx, sheet, source_start_ms, source_end_ms, offset_ms, speaker_review)
    if audit['blocking_cues']:
        raise ValueError('Speaker content gate blocked: ' + json.dumps(audit['blocking_cues'], ensure_ascii=False))
    reviewed = {a['cue']: a for a in audit['speaker_assignments']}
    expected, report = source_part(source, source_start_ms, source_end_ms, offset_ms)
    raw = Path(destination).read_bytes()
    if not raw.startswith(b'\xef\xbb\xbf'):
        raise ValueError('CSV must be UTF-8 BOM')
    with Path(destination).open(encoding='utf-8-sig', newline='') as file:
        data = list(csv.reader(file, strict=True))
    if not data or data[0] != template['fields'] or len(data)-1 != len(expected):
        raise ValueError('CSV header or row count mismatch')
    labels = {t['speaker'] for t in turns}
    assignments = []
    for ident, expected_row, fields in zip(report['cue_ids'], expected, data[1:]):
        if len(fields) != len(HEADER):
            raise ValueError(f'CSV field count mismatch: cue {ident}')
        record = dict(zip(data[0], fields))
        speaker = record['speaker']
        if not speaker.strip() or speaker not in labels:
            raise ValueError(f'Blank or unknown speaker: cue {ident}')
        if [record[k] for k in HEADER[1:]] != expected_row[1:]:
            raise ValueError(f'Text/time/notes mismatch: cue {ident}')
        assignment = {k: v for k, v in reviewed[ident].items() if k != 'cue'}
        if speaker != assignment['speaker']:
            raise ValueError(f'Incorrect speaker for Excel interval: cue {ident}')
        assignments.append(dict(cue=ident, **assignment))
    return dict(verified=True, speaker_gate_passed=True, count=len(expected), cue_ids=report['cue_ids'],
                speaker_assignments=assignments, speaker_empty_count=0,
                speaker_review_cues=[a['cue'] for a in assignments if a['case'] in (4, 5)])


def convert(source, destination, template_xlsx, sheet=None,
            source_start_ms=0, source_end_ms=None, offset_ms=0, speaker_review=None):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite: {destination}')
    template = inspect_template(template_xlsx, sheet)
    header = template['fields']
    original = source.read_bytes()
    rows, report = source_part(source, source_start_ms, source_end_ms, offset_ms)
    turns = read_turns(template)
    audit = audit_speakers(source, template_xlsx, sheet, source_start_ms, source_end_ms, offset_ms, speaker_review)
    if audit['blocking_cues']:
        raise ValueError('Speaker content gate blocked: ' + json.dumps(audit['blocking_cues'], ensure_ascii=False))
    reviewed = {a['cue']: a for a in audit['speaker_assignments']}
    assignments = []
    for cue_id, row in zip(report['cue_ids'], rows):
        assignment = {k: v for k, v in reviewed[cue_id].items() if k != 'cue'}
        row[0] = assignment['speaker']
        assignments.append(dict(cue=cue_id, **assignment))
    if len(set(report['cue_ids'])) != len(report['cue_ids']):
        raise ValueError('Duplicate SRT cue identifiers need review')
    def ms(value):
        h, m, s = value.split(':')
        seconds, milli = s.split('.')
        return ((int(h)*60 + int(m))*60 + int(seconds))*1000 + int(milli)
    issues = []
    previous_end = 0
    for cue_id, row in zip(report['cue_ids'], rows):
        start, end = ms(row[1]), ms(row[2])
        if end <= start:
            issues.append({'cue': cue_id, 'issue': 'nonpositive_duration'})
        if end-start > 90000:
            issues.append({'cue': cue_id, 'issue': 'over_90_seconds'})
        if start < previous_end:
            issues.append({'cue': cue_id, 'issue': 'overlap_or_reverse_order'})
        previous_end = end
    # Pure conversion: preserve validly parsed timing values and report conflicts.
    result = serialize(rows, header)
    if hashlib.sha256(Path(template_xlsx).read_bytes()).hexdigest() != template['sha256']:
        raise ValueError('Excel changed during inspection')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # An invalid build is never promoted to the requested deliverable path.
    with tempfile.TemporaryDirectory(prefix='heygen-verify-', dir=destination.parent) as temp:
        pending = Path(temp) / 'pending.csv'
        with pending.open('x', encoding='utf-8-sig', newline='') as file:
            file.write(result)
        checked = verify_csv(source, pending, template_xlsx, sheet,
                             source_start_ms, source_end_ms, offset_ms, speaker_review)
        if source.read_bytes() != original or hashlib.sha256(Path(template_xlsx).read_bytes()).hexdigest() != template['sha256']:
            raise ValueError('Source changed during conversion')
        with destination.open('xb') as file:
            file.write(pending.read_bytes())
    verify_csv(source, destination, template_xlsx, sheet, source_start_ms, source_end_ms, offset_ms, speaker_review)
    report.update(speaker_turns=turns, speaker_assignments=assignments, timing_issues=issues,
                  speaker_review_cues=[a['cue'] for a in assignments if a['case'] in (4, 5)],
                  source_sha256=hashlib.sha256(original).hexdigest(),
                  source=str(source.resolve()), template=template,
                  output=str(destination.resolve()), verified=checked['verified'], speaker_empty_count=0,
                  speaker_gate_passed=True, speaker_content_audit=audit,
                  source_start_ms=source_start_ms, source_end_ms=source_end_ms, offset_ms=offset_ms,
                  video_identity_verified_by_tool=False, heygen_upload_tested=False)
    return report


def convert_parts(manifest_path):
    """Explicitly confirmed parts of one SRT; require exactly-once full coverage."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    def path(value):
        p = Path(value)
        return p.resolve() if p.is_absolute() else (manifest_path.parent / p).resolve()
    source = path(manifest['source'])
    _, full = parse_srt(source.read_bytes().decode('utf-8-sig'))
    jobs, selected, targets = [], [], set()
    for part in manifest['parts']:
        dest = path(part['destination'])
        template = path(part['template_xlsx'])
        if dest in targets or dest.exists() or dest in (source, template):
            raise ValueError('Duplicate/existing output or source overwrite')
        targets.add(dest)
        options = dict(sheet=part.get('sheet'), source_start_ms=part['source_start_ms'],
                       source_end_ms=part.get('source_end_ms'), offset_ms=part['offset_ms'],
                       speaker_review=path(part['speaker_review']) if part.get('speaker_review') else None)
        _, meta = source_part(source, options['source_start_ms'], options['source_end_ms'], options['offset_ms'])
        selected.extend(meta['cue_ids'])
        jobs.append((dest, template, options))
    if selected != full['cue_ids'] or len(set(selected)) != len(selected):
        raise ValueError('Parts must cover every source cue exactly once in order')
    reports = []
    with tempfile.TemporaryDirectory(prefix='heygen-parts-') as temp:
        for i, (dest, template, options) in enumerate(jobs):
            pending = Path(temp) / f'{i}.csv'
            reports.append(convert(source, pending, template, **options))
        for i, (dest, template, options) in enumerate(jobs):
            verify_csv(source, Path(temp) / f'{i}.csv', template, **options)
        for i, (dest, template, options) in enumerate(jobs):
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open('xb') as f:
                f.write((Path(temp) / f'{i}.csv').read_bytes())
            verify_csv(source, dest, template, **options)
            reports[i]['output'] = str(dest)
    return dict(verified=True, full_source_count=len(selected), parts=reports)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?')
    parser.add_argument('destination', nargs='?')
    parser.add_argument('--template-xlsx')
    parser.add_argument('--parts-manifest', help='Confirmed partition JSON, complete one-SRT coverage')
    parser.add_argument('--sheet')
    parser.add_argument('--source-start-ms', type=int, default=0)
    parser.add_argument('--source-end-ms', type=int)
    parser.add_argument('--offset-ms', type=int, default=0)
    parser.add_argument('--verify-only', action='store_true', help='Independently verify an existing CSV; writes nothing')
    parser.add_argument('--audit-speakers', action='store_true', help='Screen speaker boundaries; JSON report only, no CSV')
    parser.add_argument('--speaker-review', help='Content review JSON bound to source, Excel and part')
    args = parser.parse_args()
    if args.parts_manifest:
        if args.source or args.destination or args.template_xlsx or args.verify_only or args.audit_speakers or args.speaker_review or args.sheet or args.source_start_ms or args.source_end_ms is not None or args.offset_ms:
            parser.error('Use only --parts-manifest for batch conversion')
        result = convert_parts(args.parts_manifest)
    elif args.audit_speakers:
        if not args.source or not args.template_xlsx or args.destination or args.verify_only:
            parser.error('--audit-speakers needs source and --template-xlsx only (plus optional part/review)')
        result = audit_speakers(args.source, args.template_xlsx, args.sheet,
                               args.source_start_ms, args.source_end_ms, args.offset_ms, args.speaker_review)
    else:
        if not all((args.source, args.destination, args.template_xlsx)):
            parser.error('source, destination and --template-xlsx are required')
        operation = verify_csv if args.verify_only else convert
        result = operation(args.source, args.destination, args.template_xlsx, args.sheet,
                           args.source_start_ms, args.source_end_ms, args.offset_ms, args.speaker_review)
    print(json.dumps(result, ensure_ascii=False, indent=2))
