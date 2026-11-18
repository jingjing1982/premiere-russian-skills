"""Read-only-source gesture timing planner. Semantic decisions are input, not inferred."""
import argparse
import csv
import io
import json
import re
from fractions import Fraction as F
from math import ceil, floor
from pathlib import Path
from speaker_guard import validate_speakers,check_group
from nonoverlap import validate as validate_nonoverlap,validate_srt

VOWELS = set('аеёиоуыэюяАЕЁИОУЫЭЮЯ')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def flat(text):
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', ' ')


def count(text):
    require(not re.search(r'[0-9A-Za-z]|[А-ЯЁ]{2,}', text),
            'Unresolved number, Latin text or uppercase abbreviation: ' + text)
    return sum(c in VOWELS for c in text)


def spoken(cue, upto=None):
    text = cue['ru']
    upto = len(text) if upto is None else upto
    require(0 <= upto <= len(text), 'Target offset out of range')
    pieces, pos = [], 0
    for r in sorted(cue.get('readings', []), key=lambda x: x['start']):
        a, b = r['start'], r['end']
        require(pos <= a < b <= len(text), 'Invalid/overlapping reading spans')
        if a >= upto:
            break
        require(b <= upto, 'Target inside a reading expansion; choose a word boundary')
        pieces.extend([text[pos:a], r['spoken']])
        pos = b
    pieces.append(text[pos:upto])
    return ''.join(pieces)


def fmt(ms):
    require(ms >= 0, 'Negative SRT time')
    h, rem = divmod(int(ms), 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f'{h:02}:{m:02}:{s:02},{milli:03}'


def rounded(value, grid):
    return floor(value / grid + F(1, 2)) * grid


def solve(plan):
    speed = F(str(plan.get('speed', '5.2')))
    max_ms = plan.get('max_duration_ms', 90000)
    require(type(max_ms) is int and max_ms > 0, 'Invalid duration cap')
    require(plan.get('extra_pause_ms', 0) == 0, 'Extra pauses are unsupported')
    grid = plan.get('grid_ms', 1)
    require(speed > 0 and isinstance(grid, int) and grid > 0, 'Invalid speed/grid')
    cues, groups, anchors = plan['cues'], plan['groups'], plan.get('anchors', [])
    require(bool(cues) and bool(groups), 'Empty input')
    attribution = validate_speakers(plan)
    ids = [c['id'] for c in cues]
    require(len(ids) == len(set(ids)), 'Duplicate source cue ID')
    require([i for g in groups for i in g['cue_ids']] == ids,
            'Groups must allocate all source cues once, in order')
    cmap = {c['id']: c for c in cues}
    counts = {}
    for n, c in enumerate(cues):
        require(c['start_ms'] >= 0 and c['end_ms'] > c['start_ms'], 'Bad source time')
        require(bool(c.get('ru')) and bool(c.get('zh')) and
                re.search('[А-Яа-яЁё]', c['ru']), 'Missing Russian/Chinese text')
        if n:
            require(c['start_ms'] >= cues[n-1]['end_ms'], 'Source cues overlap')
        counts[c['id']] = count(spoken(c))
    require(len({a['id'] for a in anchors}) == len(anchors), 'Duplicate anchor ID')
    for a in anchors:
        require(a['cue_id'] in cmap and a['time_ms'] >= 0, 'Invalid anchor source')
        c, off, target = cmap[a['cue_id']], a['char_offset'], a['target_ru']
        require(0 <= off <= len(c['ru']) and c['ru'][off:off+len(target)] == target,
                f"Anchor {a['id']}: target text mismatch")
        require(target or a.get('alignment_basis'), 'Empty target needs word-end basis')
        require(a.get('evidence'), 'Anchor mapping needs evidence description')
        require(0 <= a.get('tolerance_ms', 2000) <= 2000, 'Tolerance must be 0..2000ms')
        if 'window_ms' in a:
            lo, hi = a['window_ms']
            require(lo <= a['time_ms'] <= hi and a.get('window_evidence'),
                    'Gesture window must contain marker and have observed evidence')
    rows = []
    for gi, g in enumerate(groups, 1):
        check_group(g['cue_ids'], attribution)
        cs = [cmap[i] for i in g['cue_ids']]
        require(bool(cs), 'Empty group')
        for before, after in zip(cs, cs[1:]):
            require(after['start_ms'] == before['end_ms'], 'Group crosses positive source gap')
        require(cs[-1]['end_ms'] - cs[0]['start_ms'] <= max_ms, 'Raw span exceeds configured duration cap')
        n = sum(counts[c['id']] for c in cs)
        duration = ceil(F(n * 1000, 1) / speed / grid) * grid
        require(0 < duration <= max_ms, f'Group {gi}: calculated duration outside configured duration cap')
        aa = []
        preceding = 0
        for c in cs:
            for a in anchors:
                if a['cue_id'] != c['id']:
                    continue
                prefix = preceding + count(spoken(c, a['char_offset']))
                offset = F(prefix * 1000, 1) / speed
                ideal = F(a['time_ms']) - offset
                winlo, winhi = a.get('window_ms', [a['time_ms'], a['time_ms']])
                tol = a.get('tolerance_ms', 2000)
                aa.append({'source': a, 'prefix': prefix, 'offset': offset, 'ideal': ideal,
                           'low': F(winlo-tol)-offset, 'high': F(winhi+tol)-offset})
            preceding += counts[c['id']]
        primary = None
        if aa:
            low, high = max(F(0), max(a['low'] for a in aa)), min(a['high'] for a in aa)
            feasible = ceil(low/grid)*grid <= floor(high/grid)*grid
            if not feasible:
                primary = g.get('primary_anchor_id')
                require(primary is not None and g.get('split_review') and g.get('primary_reason'),
                        f'Group {gi}: anchors incompatible; review semantic split or declare primary')
                selected = [a for a in aa if a['source']['id'] == primary]
                require(len(selected) == 1, 'Primary anchor not in this group')
                low, high = max(F(0), selected[0]['low']), selected[0]['high']
                preference = selected[0]['ideal']
            else:
                preference = (min(a['ideal'] for a in aa)+max(a['ideal'] for a in aa))/2
            lo, hi = ceil(low/grid)*grid, floor(high/grid)*grid
            require(lo <= hi, f'Group {gi}: anchor requires negative/infeasible time')
        else:
            lo, hi, preference = ceil(F(cs[0]['start_ms'],grid))*grid, None, F(cs[0]['start_ms'])
        rows.append({'group': gi, 'turn_id': attribution[cs[0]['id']], 'cue_ids': g['cue_ids'], 'source_start_ms': cs[0]['start_ms'],
                     'source_end_ms': cs[-1]['end_ms'], 'syllables': n, 'duration_ms': duration,
                     'low': lo, 'high': hi, 'preference': preference, 'anchors': aa,
                     'primary': primary, 'split_review': g.get('split_review'),
                     'primary_reason': g.get('primary_reason'),
                     'ru': ' '.join(flat(c['ru']) for c in cs),
                     'zh': ' '.join(flat(c['zh']) for c in cs)})
    # A source-continuous interval is one scheduling unit, even when split for 90s.
    # All offsets use rounded output durations, so SRT boundaries join exactly.
    chains = []
    for r in rows:
        if not chains or r['source_start_ms'] != chains[-1]['members'][-1]['source_end_ms'] or r['turn_id'] != chains[-1]['members'][-1]['turn_id']:
            chains.append({'members': [], 'duration_ms': 0})
        chain = chains[-1]
        r['interval_id'] = len(chains)
        r['interval_offset_ms'] = chain['duration_ms']
        chain['members'].append(r)
        chain['duration_ms'] += r['duration_ms']
    for ci, chain in enumerate(chains, 1):
        members = chain['members']
        anchored = [r for r in members if r['anchors']]
        if anchored:
            low = max(0, max(r['low']-r['interval_offset_ms'] for r in anchored))
            high = min(r['high']-r['interval_offset_ms'] for r in anchored)
            ideals = [a['ideal']-r['interval_offset_ms'] for r in anchored
                      for a in r['anchors']
                      if r['primary'] is None or a['source']['id'] == r['primary']]
            preference = (min(ideals)+max(ideals))/2
            require(low <= high, f'Interval {ci}: continuous placement conflicts with anchors; '
                    'review grouping/primary anchor, do not insert a gap')
            if len(members) > 1 and len(anchored) == 1:
                # Preserve the anchor-bearing group's own chosen placement. Move
                # its unanchored siblings, not the anchor, to close internal gaps.
                pivot = anchored[0]
                pivot_start = min(pivot['high'], max(pivot['low'], rounded(pivot['preference'], grid)))
                base = pivot_start-pivot['interval_offset_ms']
                require(base >= 0, f'Interval {ci}: backfill before zero; anchor left unchanged')
                low = high = base
                preference = F(base)
        else:
            low = ceil(F(members[0]['source_start_ms'], grid))*grid
            high, preference = None, F(members[0]['source_start_ms'])
        chain.update(group=ci, low=low, high=high, preference=preference)
    # Prefer fitting the current video when feasible within all existing anchor bounds.
    # An impossible tail cap remains a reported overflow, never a speed/text change.
    if 'video_end_ms' in plan:
        earliest_end = 0
        can_fit = True
        for r in chains:
            earliest_start = max(earliest_end, r['low'])
            if r['high'] is not None and earliest_start > r['high']:
                can_fit = False
            earliest_end = earliest_start+r['duration_ms']
        cap = floor(F(plan['video_end_ms']-chains[-1]['duration_ms'],grid))*grid
        if can_fit and earliest_end <= plan['video_end_ms']:
            chains[-1]['high'] = cap if chains[-1]['high'] is None else min(chains[-1]['high'], cap)
    # Latest-start propagation protects future anchors from greedy earlier placement.
    for i in range(len(chains)-2, -1, -1):
        next_hi = chains[i+1]['high']
        if next_hi is not None:
            cap = next_hi - chains[i]['duration_ms']
            chains[i]['high'] = cap if chains[i]['high'] is None else min(chains[i]['high'], cap)
    prev_end = 0
    for r in chains:
        lo, hi = max(prev_end, r['low']), r['high']
        require(hi is None or lo <= hi, f"Interval {r['group']}: neighbor capacity conflict; regroup")
        start = max(lo, rounded(r['preference'], grid))
        if hi is not None:
            start = min(start, hi)
        r['start_ms'], r['end_ms'] = start, start+r['duration_ms']
        prev_end = r['end_ms']
        for member in r['members']:
            member['start_ms'] = start+member['interval_offset_ms']
            member['end_ms'] = member['start_ms']+member['duration_ms']
            member['shift_from_independent_preference_ms'] = member['start_ms']-rounded(member['preference'], grid)
    joins = []
    for before, after in zip(rows, rows[1:]):
        same = before['interval_id'] == after['interval_id']
        gap = after['start_ms']-before['end_ms']
        require(gap >= 0 and (not same or gap == 0), 'Output continuity invariant failed')
        joins.append({'before_group': before['group'], 'after_group': after['group'],
                      'same_source_interval': same, 'output_gap_ms': gap,
                      'source_gap_ms': after['source_start_ms']-before['source_end_ms']})
    anchor_rows = []
    for r in rows:
        for a in r['anchors']:
            src = a['source']
            predicted = F(r['start_ms'])+a['offset']
            winlo, winhi = src.get('window_ms', [src['time_ms'], src['time_ms']])
            distance = max(F(winlo)-predicted, predicted-F(winhi), F(0))
            alternative = rounded(a['ideal'], grid)
            anchor_rows.append({'id': src['id'], 'group': r['group'], 'cue_id': src['cue_id'],
                                'marker_ms': src['time_ms'], 'target_ru': src['target_ru'],
                                'prefix_syllables': a['prefix'], 'predicted_ms': float(predicted),
                                'error_ms': float(predicted-src['time_ms']),
                                'distance_from_window_ms': float(distance),
                                'within_tolerance': distance <= src.get('tolerance_ms',2000),
                                'primary': r['primary'] == src['id'],
                                'alternative_start_ms': alternative,
                                'alternative_end_ms': alternative+r['duration_ms'],
                                'shift_ms': alternative-r['start_ms'],
                                'alternative_requires_neighbor_check': True,
                                'evidence': src['evidence']})
    clean = [{k:v for k,v in r.items() if k not in ('low','high','preference','anchors')} for r in rows]
    overflow = max(0, prev_end-plan['video_end_ms']) if 'video_end_ms' in plan else None
    conflicts = [a['id'] for a in anchor_rows if not a['within_tolerance']]
    return {'source': plan.get('source'), 'speaker_review': plan['speaker_review'],
            'speaker_attribution_checked': True, 'speed': str(speed), 'grid_ms': grid,
            'status': 'review_conflicts' if conflicts or overflow else 'estimated_not_audio_verified',
            'groups': clean, 'anchors': anchor_rows, 'conflicting_anchor_ids': conflicts,
            'joins': joins, 'continuous_intervals_verified': len(chains),
            'video_overflow_ms': overflow, 'max_duration_ms': max(r['duration_ms'] for r in clean)}


def export(plan, output):
    result = solve(plan)
    validate_nonoverlap(result["groups"])
    suffix = '_核对稿' if result['status'] == 'review_conflicts' else '_规划稿'
    output = Path(output)
    files = [output/('合并字幕'+suffix+'.srt'), output/'计算与锚点核对.json', output/'锚点定位.csv']
    require(not any(p.exists() for p in files), 'Output exists; choose a new directory')
    text = '\n\n'.join(f"{r['group']}\n{fmt(r['start_ms'])} --> {fmt(r['end_ms'])}\n{r['ru']}\n{r['zh']}"
                       for r in result['groups'])+'\n'
    output.mkdir(parents=True, exist_ok=True)
    files[0].write_bytes(b'\xef\xbb\xbf'+text.replace('\n','\r\n').encode('utf-8'))
    saved = files[0].read_text('utf-8-sig')
    validate_srt(saved)
    require(saved == text, 'SRT readback mismatch')
    files[1].write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    buf = io.StringIO(newline='')
    if result['anchors']:
        writer = csv.DictWriter(buf,fieldnames=list(result['anchors'][0]))
        writer.writeheader()
        writer.writerows(result['anchors'])
    files[2].write_bytes(b'\xef\xbb\xbf'+buf.getvalue().encode('utf-8'))
    return files, result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('plan')
    parser.add_argument('output_directory')
    args = parser.parse_args()
    paths, result = export(json.loads(Path(args.plan).read_text('utf-8-sig')), args.output_directory)
    print(json.dumps({'files':[str(p.resolve()) for p in paths], 'status':result['status']},ensure_ascii=False))
