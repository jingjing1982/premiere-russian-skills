"""Offline visible-shot residual audit. Does not infer shots or edit Premiere."""
import json
import math
import sys
from pathlib import Path


def audit(data):
    fps, duration = data['fps'], data['duration']
    if type(fps) is not int or fps <= 0 or type(duration) is not int or duration <= 0:
        raise ValueError('Positive integer fps and duration required')
    short = data.get('short_seconds', .5)
    review = data.get('review_seconds', 1)
    if not isinstance(short, (int, float)) or not math.isfinite(short) or short <= 0:
        raise ValueError('Positive finite short_seconds required')
    if not isinstance(review, (int, float)) or not math.isfinite(review) or review < 1:
        raise ValueError('review_seconds must be at least 1')
    def ranges(items):
        result = sorted(items)
        for a, b in result:
            if type(a) is not int or type(b) is not int or not 0 <= a < b <= duration:
                raise ValueError('Invalid frame interval')
        if any(b > c for (a, b), (c, d) in zip(result, result[1:])):
            raise ValueError('Overlapping intervals')
        return result
    cuts = ranges(data['cuts'])
    shots = data['shots']
    if not shots or len({s['id'] for s in shots}) != len(shots):
        raise ValueError('Unique visible-shot identities required')
    ranges([(s['start'], s['end']) for s in shots])
    if any(not isinstance(s.get('evidence'), str) or not s['evidence'].strip() for s in shots):
        raise ValueError('Visual evidence is required for each shot')
    def mapped(t):
        return t - sum(max(0, min(t, b) - a) for a, b in cuts)
    final_end = mapped(duration)
    if final_end <= 0:
        raise ValueError('Cannot remove the whole sequence')
    fragments = []
    for s in shots:
        pieces = [(s['start'], s['end'])]
        for a, b in cuts:
            pieces = [(l, r) for x, y in pieces
                      for l, r in ([(x, y)] if b <= x or a >= y
                                   else [(x, min(y, a)), (max(x, b), y)]) if l < r]
        for a, b in pieces:
            fragments.append(dict(key=f"{s['id']}:{a}:{b}", shot_id=s['id'],
                                  source=[a, b], output=[mapped(a), mapped(b)],
                                  trimmed=(a != s['start'] or b != s['end']),
                                  evidence=s['evidence']))
    fragments.sort(key=lambda s: s['output'])
    seams = sorted({mapped(a) for a, b in cuts})
    issues = []
    windows = []
    for seam in seams:
        lo, hi = max(0, seam - math.ceil(review * fps)), min(final_end, seam + math.ceil(review * fps))
        cursor = lo
        visible = []
        for f in fragments:
            a, b = f['output']
            if b <= lo or a >= hi:
                continue
            visible.append(f['key'])
            if a > cursor:
                issues.append(dict(seam=seam, missing=[cursor, min(a, hi)]))
            cursor = max(cursor, min(b, hi))
        if cursor < hi:
            issues.append(dict(seam=seam, missing=[cursor, hi]))
        windows.append(dict(seam=seam, range=[lo, hi], visible_fragments=visible))
    flagged = [f for f in fragments if f['trimmed'] and
               f['source'][1] - f['source'][0] <= short * fps]
    reviews = data.get('reviews', {})
    unresolved = []
    for f in flagged:
        decision = reviews.get(f['key'], {})
        accepted = (decision.get('action') == 'retain' and
                    all(isinstance(decision.get(k), str) and decision[k].strip()
                        for k in ('reason', 'evidence')))
        f['review'] = decision if accepted else None
        if not accepted:
            unresolved.append(f['key'])
    return dict(passed=not issues and not unresolved, duration=final_end,
                review_windows=windows, fragments=fragments,
                short_fragments=flagged, unresolved=unresolved,
                coverage_issues=issues, premiere_contacted=False)


if __name__ == '__main__':
    result = audit(json.loads(Path(sys.argv[1]).read_text('utf-8-sig')))
    with Path(sys.argv[2]).open('x', encoding='utf8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ('passed', 'unresolved', 'coverage_issues')}))
    sys.exit(0 if result['passed'] else 2)
