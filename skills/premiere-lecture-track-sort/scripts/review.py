"""Validate classification coverage and its relationship to a non-destructive plan.

Evidence records attest what the reviewing agent inspected, not classification accuracy.
This module never performs image recognition, transcription, or Premiere calls.
"""
import hashlib
import json
from pathlib import Path


def validate_review(cfg, rows):
    review = json.loads(Path(cfg['review']).read_text(encoding='utf-8-sig'))
    if (review.get('source_sha256') != hashlib.sha256(Path(cfg['source_snapshot']).read_bytes()).hexdigest()
            or review.get('uid') != cfg['uid'] or review.get('fps') != cfg['fps']):
        raise ValueError('Classification belongs to a different source/sequence/timebase')
    mode = review.get('mode')
    if mode not in ('audience_only', 'audience_and_interpreter'):
        raise ValueError('Choose audience_only or audience_and_interpreter')
    spans = review.get('spans', [])
    def evidence(value):
        return isinstance(value, list) and bool(value) and all(isinstance(v,str) and v.strip() for v in value)
    allowed = {'audience','interpreter','speaker','host','questioner','uncertain','protected'}
    for span in spans:
        if any(type(span.get(k)) is not int for k in ('start','end','video_track')):
            raise ValueError('Classification coordinates must be integer frames')
        if span['label'] not in allowed or span.get('reviewed') is not True or not evidence(span.get('visual_evidence')):
            raise ValueError('Missing visual review or unsupported classification')
        if span['label']=='interpreter':
            if mode=='audience_only' or span.get('audio_role')!='interpreter' or not evidence(span.get('audio_evidence')):
                raise ValueError('Interpreter assignment requires actual audio evidence and interpreter mode')
        parents=[r for r in rows if r[0]==0 and r[1]==span['video_track'] and r[2]<=span['start']<span['end']<=r[3]]
        if len(parents)!=1:
            raise ValueError('Classification must map inside exactly one original video clip')
    for r in rows:
        if r[0]!=0:continue
        parts=sorted([s for s in spans if s['video_track']==r[1] and r[2]<=s['start']<s['end']<=r[3]],key=lambda s:s['start'])
        if not parts or parts[0]['start']!=r[2] or parts[-1]['end']!=r[3] or any(a['end']!=b['start'] for a,b in zip(parts,parts[1:])):
            raise ValueError('Classification must cover every video clip once, including uncertain/retained regions')
    moved=set()
    for m in cfg['moves']:
        hits=[s for s in spans if all(s[k]==m[k] for k in ('start','end','video_track'))]
        if len(hits)!=1:raise ValueError('Move lacks one exact reviewed range')
        s=hits[0];target={'audience':1,'interpreter':2}.get(s['label'])
        if target!=m['target_track'] or s.get('overlapping_protected_speech') and target==2:
            raise ValueError('Move conflicts with visual/audio category or protected speech')
        moved.add((s['video_track'],s['start'],s['end']))
    for s in spans:
        dest={'audience':1,'interpreter':2}.get(s['label'])
        if dest is not None and s['video_track']!=dest and (s['video_track'],s['start'],s['end']) not in moved:
            if not isinstance(s.get('retained_reason'),str) or not s['retained_reason'].strip():
                raise ValueError('Confirmed but unimplemented classification needs a retained_reason')
    cr=review.get('cut_reviews',[])
    for cut in cfg['cuts']:
        hits=[c for c in cr if all(c.get(k)==cut[k] for k in ('frame','video_track','audio_track'))]
        if len(hits)!=1 or hits[0].get('reviewed') is not True or not evidence(hits[0].get('evidence')):
            raise ValueError('Every new cut requires an exact reviewed boundary')
        if not any(m['video_track']==cut['video_track'] and cut['frame'] in (m['start'],m['end']) for m in cfg['moves']):
            raise ValueError('Cut does not isolate a requested move; preserve manual edits')
    return {'mode':mode,'reviewed_spans':len(spans), 'uncertain_spans':sum(s['label']=='uncertain' for s in spans),
            'classification_verified_automatically':False}
