"""Merge only after binding plan cues to an independent saved-project extraction."""
import argparse, json, hashlib, re
from pathlib import Path

def validate_source(source,plan,mode):
    original=json.loads(Path(source).read_text(encoding='utf-8-sig'))
    p=json.loads(Path(plan).read_text(encoding='utf-8-sig'))
    if p.get('source_snapshot_sha256')!=hashlib.sha256(Path(source).read_bytes()).hexdigest():raise ValueError('Plan not bound to source snapshot')
    if len(original['cues'])!=len(p['cues']):raise ValueError('Source cue count mismatch')
    for a,b in zip(original['cues'],p['cues']):
        for key in ('id','start_ms','end_ms'):
            if a[key]!=b[key]:raise ValueError('Source identity/time mismatch')
        if 'ru' in a and 'zh' in a:ru,zh=a['ru'],a['zh']
        else:
            lines=a['text'].replace('\r\n','\n').replace('\r','\n').split('\n')
            # Read from a reviewed exact language boundary; no guessing Latin source lines.
            n=p.get('language_boundaries',{}).get(str(a['id']))
            if n is None and len(lines)==2 and re.search('[А-Яа-яЁё]',lines[0]) and not re.search('[\u3400-\u9fff]',lines[0]):n=1
            if type(n)!=int or not 0<n<len(lines):raise ValueError('Review exact Russian/Chinese line boundary')
            ru=' '.join(lines[:n]);zh=' '.join(lines[n:])
        flat=lambda s:s.replace('\r\n','\n').replace('\r','\n').replace('\n',' ')
        if (flat(ru),flat(zh))!=(b['ru'],b['zh']):raise ValueError('Plan text differs from independent source')
    if mode=='speaker' and p.get('mode')!='speaker_first_anchor':raise ValueError('Wrong grouping mode')
    if mode=='gaps' and p.get('mode') not in (None,'gaps'):raise ValueError('Wrong grouping mode')
    return p
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source_snapshot');a.add_argument('plan');a.add_argument('output');a.add_argument('--mode',choices=['gaps','speaker'],required=True);args=a.parse_args()
    plan=validate_source(args.source_snapshot,args.plan,args.mode)
    if args.mode=='speaker':from speaker_timing import export
    else:from gesture_timing import export
    export(plan,args.output)
    print(json.dumps({'source_text_verified':True,'output':str(Path(args.output).resolve()),'actual_audio_sync_verified':False},ensure_ascii=False))
