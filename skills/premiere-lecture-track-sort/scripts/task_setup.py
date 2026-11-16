"""Inspect a saved project or make byte-identical independent copies; never contacts PR."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from saved_audit import load, records, link_pairs
from track_sort import check_rows, TICKS_PER_SECOND


def inspect(path):
    root,ix,ux=load(path)
    seqs=[]
    for uid,s in ux.items():
        if s.tag!='Sequence':continue
        groups=[ix[r.get('ObjectRef')] for r in s.findall('./TrackGroups/TrackGroup/Second')]
        times={int(g.findtext('./TrackGroup/FrameRate','0')) for g in groups if g.tag in ('VideoTrackGroup','AudioTrackGroup')}
        seqs.append({'uid':uid,'name':s.findtext('Name'),'timebases':sorted(times)})
    return {'project':str(Path(path).resolve()),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'sequences':seqs,'live_state_checked':False}


def setup(source,uid,fps,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if fps not in (25,50):raise ValueError('Only integer 25/50 fps supported')
    state=inspect(source)
    found=[s for s in state['sequences'] if s['uid']==uid]
    tpf=TICKS_PER_SECOND//fps
    if len(found)!=1 or found[0]['timebases']!=[tpf]:raise ValueError('Saved sequence/timebase mismatch')
    root,ix,ux=load(source);recs=records(ix,ux,uid,tpf);rows=[r for r,o in recs]
    check_rows(rows);link_pairs(ix,ux,uid,recs)
    for ref in ux[uid].findall('./TrackGroups/TrackGroup/Second'):
        group=ix[ref.get('ObjectRef')]
        if group.tag in ('AudioTrackGroup','VideoTrackGroup'):
            for tr in group.findall('./TrackGroup/Tracks/Track'):
                track=ux[tr.get('ObjectURef')]
                if any('transition' in e.tag.lower() and (len(e) or (e.text or '').strip()) for e in track.iter()):
                    raise ValueError('Transitions require a separately verified method')
    output.mkdir(parents=True,exist_ok=False)
    frozen=output/'source-snapshot.prproj';preview=output/'track-sort-preview.prproj'
    shutil.copy2(source,frozen);shutil.copy2(source,preview)
    if any(hashlib.sha256(p.read_bytes()).hexdigest()!=state['sha256'] for p in (source,frozen,preview)):
        raise ValueError('Source changed during snapshot; do not use these copies')
    config={'main_project':str(source),'source_snapshot':str(frozen),'preview':str(preview),
            'uid':uid,'fps':fps,'tpf':tpf,'review':str(output/'review.json'),'cuts':[],'moves':[],'baseline':rows}
    review={'source_sha256':state['sha256'],'uid':uid,'fps':fps,'mode':'audience_only','spans':[], 'cut_reviews':[]}
    for r in rows:
        if r[0]==0:
            review['spans'].append({'video_track':r[1],'start':r[2],'end':r[3],'label':'uncertain','reviewed':False,
                                   'visual_evidence':[],'audio_role':'not_checked','audio_evidence':[]})
    for name,obj in [('config.json',config),('review.json',review),('source-identity.json',state)]:
        (output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'preview':str(preview),'source_snapshot':str(frozen),'sequence':found[0], 'video_clips':sum(r[0]==0 for r in rows),'premiere_contacted':False}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    i=sub.add_parser('inspect');i.add_argument('project')
    p=sub.add_parser('prepare');p.add_argument('project');p.add_argument('--uid',required=True);p.add_argument('--fps',type=int,required=True)
    p.add_argument('--output',required=True);p.add_argument('--latest-saved-verified',action='store_true')
    args=ap.parse_args()
    if args.command=='inspect': result=inspect(args.project)
    else:
        if not args.latest_saved_verified:ap.error('Verify latest saved state before creating preview')
        result=setup(args.project,args.uid,args.fps,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
