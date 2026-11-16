"""Generate guarded native extract jobs and audit saved results; never calls PR itself.
Supports the deliberately narrow, validated offline model: continuous 1x V1/A1 with
one-to-one links, captions and point markers outside cuts. Complex projects stop.
"""
from pathlib import Path
from fractions import Fraction
import argparse, copy, hashlib, json, shutil
from saved_audit import load, records, link_pairs, graph
from extract_saved_captions import extract, TPS
from frame_plan import plan

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def non_item_graph(root,uid):
    """Compare target sequence/track attributes, excluding separately audited objects.
    Conservative: unknown serialization changes stop audit rather than being ignored.
    """
    r=copy.deepcopy(root)
    for ob in r:
        if ob.get('ObjectUID')==uid:
            for child in list(ob):
                if child.tag in ('MarkerOwner','PersistentGroupContainer'):ob.remove(child)
        for node in list(ob.iter()):
            if node.tag=='TrackItems':
                node.clear()
    ix={n.get('ObjectID'):n for n in r if n.get('ObjectID')}
    ux={n.get('ObjectUID'):n for n in r if n.get('ObjectUID')};ix.update(ux)
    return graph(ix,ux[uid])
def snapshot(path,uid):
    cap=extract(Path(path),uid);root,ix,ux=load(path);tpf=cap['ticks_per_frame']
    rec=records(ix,ux,uid,tpf);link_pairs(ix,ux,uid,rec)
    # Unsupported geometry/effects must not enter the simple expected-state model.
    for r,obj in rec:
        if r[1]!=0 or r[5]-r[4]!=r[3]-r[2]:raise ValueError('Requires continuous 1x V1/A1')
    for ref in ux[uid].findall('./TrackGroups/TrackGroup/Second'):
        group=ix[ref.get('ObjectRef')]
        if group.tag in ('VideoTrackGroup','AudioTrackGroup'):
            for tr in group.findall('./TrackGroup/Tracks/Track'):
                track=ux[tr.get('ObjectURef')]
                for n in track.iter():
                    if 'transition' in n.tag.lower() and (list(n) or (n.text or '').strip()):
                        raise ValueError('Transitions require separate supported audit; no automatic extract')
    return cap,root,ix,ux,rec
def prepare(args):
    source=Path(args.source).resolve();preview=Path(args.preview).resolve();out=Path(args.output).resolve()
    if source==preview:raise ValueError('Only an independent preview may be changed')
    if out.exists():raise ValueError('Job directory already exists')
    cap,root,ix,ux,rec=snapshot(preview,args.uid)
    src=extract(source,args.uid)
    if [(c['text'],c['start_ticks'],c['end_ticks']) for c in src['cues']]!=[(c['text'],c['start_ticks'],c['end_ticks']) for c in cap['cues']]:raise ValueError('Source/preview captions differ before task')
    sr,si,su=load(source)
    if [r for r,o in records(si,su,args.uid,cap['ticks_per_frame'])]!=[r for r,o in rec]:raise ValueError('Source/preview AV differ before task')
    fps=Fraction(cap['fps']);tpf=cap['ticks_per_frame']
    if fps.denominator!=1:raise ValueError('This native adapter currently requires integer fps; no approximate conversion')
    cuts=read(args.cuts)
    if not cuts.get('review_reference'):raise ValueError('Reviewed deletion evidence/reference required')
    if any(c['start_ticks']%tpf or c['end_ticks']%tpf for c in cap['cues']):raise ValueError('Subframe captions unsupported')
    duration=max(r[3] for r,o in rec)
    if max(t['maximum_end_ticks'] for t in cap['tracks'])!=duration*tpf:raise ValueError('Non-AV end exceeds supported duration')
    for marker in cap['markers']:
        a=int(marker['mStartTime']['ticks']);b=int(marker.get('mEndTime',marker['mStartTime'])['ticks'])
        if any((lo*tpf<=a<hi*tpf) or (a<hi*tpf and b>lo*tpf) for lo,hi in cuts['cuts']):
            raise ValueError('A point/range marker intersects a deletion; resolve explicitly before native queue')
    data={'fps':int(fps),'duration':duration,'rows':[r for r,o in rec],
      'cues':[[c['start_ticks']//tpf,c['end_ticks']//tpf] for c in cap['cues']],
      'protected':cuts.get('protected',[]),'cuts':cuts['cuts']}
    expected=plan(data)
    out.mkdir(parents=True);shutil.copy2(preview,out/'baseline.prproj')
    job={'schema':'native-extract/v1','source':str(source),'source_sha256':sha(source),'preview':str(preview),
      'baseline_sha256':sha(out/'baseline.prproj'),'uid':args.uid,'tpf':tpf,'fps':int(fps),
      'input':data,'expected':expected,'review_reference':cuts['review_reference'],'steps':[]}
    shape='''function shape(s){var out=[];for(var k=0;k<2;k++){var ts=k?s.audioTracks:s.videoTracks;for(var t=0;t<ts.numTracks;t++)for(var i=0;i<ts[t].clips.numItems;i++){var c=ts[t].clips[i];if(c.getSpeed()!==1||c.isSpeedReversed())throw Error("Unsupported speed");function fr(v){var n=Number(v.ticks)/TPF;if(n!==Math.round(n))throw Error("Subframe item");return n;}out.push([k,t,fr(c.start),fr(c.end),fr(c.inPoint),fr(c.outPoint),c.projectItem.getMediaPath()]);}}return out;}'''
    header='(function(){if(app.project.path!=='+json.dumps(str(preview))+')throw Error("Wrong preview");var TPF='+str(tpf)+';var s=null;for(var i=0;i<app.project.sequences.numSequences;i++){var z=app.project.sequences[i];if(z.sequenceID==='+json.dumps(args.uid)+')s=z;}if(!s||String(s.timebase)!=='+json.dumps(str(tpf))+')throw Error("Wrong sequence/timebase");'+shape
    prior=data['rows'];done=[]
    for i,(a,b) in enumerate(expected['cuts_descending'],1):
        done.append([a,b]);state=plan(dict(data,cuts=done));after=state['rows']
        # First snapshot, strict state gate, exact tick readback. No implicit save on failure.
        script=header+'if(JSON.stringify(shape(s))!==JSON.stringify('+json.dumps(prior)+'))throw Error("Timeline changed; inspect before retry");app.project.openSequence(s.sequenceID);for(var k=0;k<2;k++){var ts=k?s.audioTracks:s.videoTracks;for(var t=0;t<ts.numTracks;t++){if(ts[t].isLocked())throw Error("Locked track");ts[t].setTargeted(true,true);}}'
        script+=f's.setInPoint({a/int(fps)+.000001:.9f});s.setOutPoint({b/int(fps)+.000001:.9f});'
        script+='if(String(s.getInPointAsTime().ticks)!=='+json.dumps(str(a*tpf))+'||String(s.getOutPointAsTime().ticks)!=='+json.dumps(str(b*tpf))+')throw Error("Frame mark mismatch");if(!app.project.activeSequence||app.project.activeSequence.sequenceID!==s.sequenceID)throw Error("Target activation failed");app.enableQE();var qs=qe.project.getActiveSequence();function canonical(x){return String(x).replace(/[{}]/g,"").toLowerCase();}if(!qs||!qs.guid||canonical(qs.guid)!==canonical(s.sequenceID))throw Error("QE sequence identity unavailable or differs; do not extract");qs.extract();var actual=shape(s);if(JSON.stringify(actual)!==JSON.stringify('+json.dumps(after)+'))throw Error("Post-extract mismatch; stop and inspect");return JSON.stringify({rows:actual,saved:false});})()'
        name=f'cut-{i:03}.jsx';(out/name).write_text(script,encoding='utf-8')
        job['steps'].append({'n':i,'cut':[a,b],'before':prior,'after':after,'script':name,'sha256':sha(out/name)})
        prior=after
    (out/'read-live.jsx').write_text(header+'return JSON.stringify({rows:shape(s),path:app.project.path,sequence:s.sequenceID});})()',encoding='utf-8')
    (out/'save-preview.jsx').write_text(header+'app.project.save();return JSON.stringify({saved:true,path:app.project.path});})()',encoding='utf-8')
    write(out/'job.json',job)
    return {'prepared_steps':len(job['steps']),'pr_contacted':False,'job':str(out/'job.json')}
def audit(args):
    directory=Path(args.job).resolve().parent;job=read(args.job);n=args.done
    if not 0<=n<=len(job['steps']):raise ValueError('Invalid completed count')
    if sha(job['source'])!=job['source_sha256'] or sha(directory/'baseline.prproj')!=job['baseline_sha256']:raise ValueError('Source/baseline changed')
    cap,br,bi,bu,brec=snapshot(directory/'baseline.prproj',job['uid'])
    acap,ar,ai,au,arec=snapshot(job['preview'],job['uid'])
    selected=[s['cut'] for s in job['steps'][:n]];expected=plan(dict(job['input'],cuts=selected));tpf=job['tpf']
    if [r for r,o in arec]!=expected['rows']:raise ValueError('Saved AV state differs')
    def mapped(t):return t-sum(max(0,min(t,b*tpf)-a*tpf) for a,b in selected)
    if len(cap['cues'])!=len(acap['cues']):raise ValueError('Caption count changed')
    for before,after in zip(cap['cues'],acap['cues']):
        if before['text']!=after['text'] or [after[k] for k in ('start_ticks','end_ticks')]!=[mapped(before[k]) for k in ('start_ticks','end_ticks')]:raise ValueError('Caption text/timing mismatch')
        bo=copy.deepcopy(bi[before['source_object_id']]);ao=copy.deepcopy(ai[after['source_object_id']])
        for ob in (bo,ao):
            for tag in ('Start','End'):ob.find('.//TrackItem/'+tag).text='0'
        if graph(bi,bo)!=graph(ai,ao):raise ValueError('Caption style/reference mismatch')
    markers=copy.deepcopy(cap['markers'])
    for marker in markers:
        for key in ('mStartTime','mEndTime'):
            if key in marker:marker[key]['ticks']=mapped(int(marker[key]['ticks']))
    if markers!=acap['markers']:raise ValueError('Marker mapping mismatch')
    for row,obj in arec:
        old=[o for r,o in brec if r[:2]==row[:2] and r[6]==row[6] and r[4]<=row[4]<row[5]<=r[5]]
        if len(old)!=1:raise ValueError('Ambiguous retained source mapping')
        path='./ClipTrackItem/ComponentOwner/Components'
        if graph(bi,old[0].find(path))!=graph(ai,obj.find(path)):raise ValueError('Effect/keyframe mismatch')
    if non_item_graph(br,job['uid'])!=non_item_graph(ar,job['uid']):
        raise ValueError('Target sequence/track attributes changed outside audited items; inspect before claiming preservation')
    for uid,ob in bu.items():
        if ob.tag=='Sequence' and uid!=job['uid'] and (uid not in au or graph(bi,ob)!=graph(ai,au[uid])):raise ValueError('Unrelated sequence changed')
    result={'verified_steps':n,'captions':len(acap['cues']),'markers':len(markers),'av_items':len(arec),
       'source_unchanged':True,'audio_listened':False,'visual_review':False,'preview_sha256':sha(job['preview'])}
    write(args.output,result);return result
def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('prepare')
    for x in ('source','preview','uid','cuts','output'):a.add_argument('--'+x,required=True)
    a=sub.add_parser('audit');a.add_argument('--job',required=True);a.add_argument('--done',type=int,required=True);a.add_argument('--output',required=True)
    args=p.parse_args();print(json.dumps(prepare(args) if args.cmd=='prepare' else audit(args),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
