"""Version-bound SRT handoff. Hashes detect changed files, not human approval or video identity."""
import argparse, hashlib, json, re, uuid
from pathlib import Path
from datetime import datetime, timezone
from fractions import Fraction

def fingerprint(path):
    p=Path(path).resolve()
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def cues(path):
    raw=Path(path).read_text(encoding='utf-8-sig').replace('\r\n','\n').replace('\r','\n')
    blocks=re.split(r'\n[ \t]*\n',raw.rstrip('\n')); out=[]
    for b in blocks:
        lines=b.split('\n')
        if len(lines)<3 or not re.fullmatch(r'\d+',lines[0]):raise ValueError('Invalid or empty SRT cue')
        m=re.fullmatch(r'(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3}) --> (\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})',lines[1])
        if not m:raise ValueError('Invalid SRT time')
        v=list(map(int,m.groups())); ts=[((v[i]*60+v[i+1])*60+v[i+2])*1000+v[i+3] for i in (0,4)]
        if ts[1]<=ts[0]:raise ValueError('Nonpositive cue duration')
        out.append({'id':lines[0],'start_ms':ts[0],'end_ms':ts[1],'text':'\n'.join(lines[2:])})
    if not out or len({x['id'] for x in out})!=len(out):raise ValueError('Empty/duplicate cue IDs')
    return out
def check(record, srt=None):
    d=json.loads(Path(record).read_text(encoding='utf-8-sig'))
    if d.get('schema')!='ru-video-handoff/v1':raise ValueError('Unknown handoff schema')
    for key in ('srt','project','video'):
        f=d.get(key)
        if f and fingerprint(f['path'])!=f:raise ValueError('Changed or missing '+key+'; obtain current version and renew handoff')
    if srt and fingerprint(srt)['sha256']!=d['srt']['sha256']:raise ValueError('SRT is not the handoff version')
    return d
def register(args):
    rows=cues(args.srt)
    parent=check(args.parent) if args.parent else None
    if not args.confirmation.strip():raise ValueError('Record the actual user confirmation or inspection reference')
    if args.fps!='unknown' and Fraction(args.fps)<=0:raise ValueError('Invalid fps')
    d={'schema':'ru-video-handoff/v1','id':str(uuid.uuid4()),'created_utc':datetime.now(timezone.utc).isoformat(),
       'stage':args.stage,'sequence_uid':args.sequence_uid,'fps':None if args.fps=='unknown' else str(Fraction(args.fps)),
       'timeline_origin':'sequence_zero','srt':fingerprint(args.srt),
       'project':fingerprint(args.project) if args.project else None,
       'video':fingerprint(args.video) if args.video else None,
       'identity_evidence':args.confirmation,'video_identity_verified_by_tool':False,
       'parent_id':parent['id'] if parent else None,'cue_count':len(rows),
       'cue_text_sha256':hashlib.sha256(json.dumps([(r['id'],r['text']) for r in rows],ensure_ascii=False).encode()).hexdigest(),
       'timeline_revision':args.revision,'unresolved':args.unresolved or []}
    with Path(args.output).open('x',encoding='utf-8') as f:json.dump(d,f,ensure_ascii=False,indent=2)
    return d
def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('register');a.add_argument('--srt',required=True);a.add_argument('--output',required=True)
    a.add_argument('--stage',choices=['merged-review','timeline-reviewed','ready-for-upload','final-layout','final-trim'],required=True)
    a.add_argument('--sequence-uid',required=True);a.add_argument('--fps',required=True);a.add_argument('--revision',required=True)
    a.add_argument('--project');a.add_argument('--video');a.add_argument('--parent');a.add_argument('--confirmation',required=True)
    a.add_argument('--unresolved',action='append')
    a=sub.add_parser('check');a.add_argument('record');a.add_argument('--srt')
    args=p.parse_args();d=register(args) if args.command=='register' else check(args.record,args.srt)
    print(json.dumps(d,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
