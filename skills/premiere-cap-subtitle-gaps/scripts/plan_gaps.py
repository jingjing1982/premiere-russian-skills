"""Read-only integer-frame planner. Does not connect to or modify Premiere."""
import json
from fractions import Fraction
from pathlib import Path
import argparse

def plan(cues, duration, fps, cap_seconds=10):
    rate = Fraction(str(fps))
    cap = rate * Fraction(str(cap_seconds))
    if rate <= 0 or cap <= 0 or cap.denominator != 1 or int(cap) % 2:
        raise ValueError('Cap and equal half margins must be exactly representable in whole frames; confirm an alternative instead of rounding')
    cap = int(cap)
    if not cues:
        raise ValueError('No merged captions; cannot identify gaps')
    if type(duration) is not int or duration <= 0:
        raise ValueError('duration must be positive integer frames')
    merged=[]
    for s,e in sorted(cues):
        if type(s) is not int or type(e) is not int or not 0 <= s < e <= duration:
            raise ValueError('Invalid cue frame bounds')
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(e,merged[-1][1])
        else:
            merged.append([s,e])
    gaps=[]
    for left,right in zip(merged,merged[1:]):
        a,b=left[1],right[0]
        if b-a > cap:
            keep_left=cap//2;keep_right=cap-keep_left
            gaps.append({'kind':'internal','gap':[a,b],'cut':[a+keep_left,b-keep_right]})
    if duration-merged[-1][1] > cap:
        a=merged[-1][1]
        gaps.append({'kind':'tail','gap':[a,duration],'cut':[a+cap,duration]})
    cuts=[g['cut'] for g in gaps]
    def mapped(t):return t-sum(max(0,min(t,b)-a) for a,b in cuts)
    return {'fps':str(rate),'cap_frames':cap,'head_unchanged':True,'gaps':gaps,
            'delete_frames':sum(b-a for a,b in cuts),'duration_after':mapped(duration),
            'cues_after':[[mapped(s),mapped(e)] for s,e in cues],
            'execution_order':list(reversed(cuts))}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('output');a=ap.parse_args()
    data=json.loads(Path(a.input).read_text('utf8'));out=Path(a.output)
    result=plan(data['cues'],data['duration'],data['fps'],data.get('cap_seconds',10))
    with out.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
