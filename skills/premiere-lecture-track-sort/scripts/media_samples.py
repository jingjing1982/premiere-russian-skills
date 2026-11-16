"""Cached source-frame sampling/contact sheets. No automatic visual classification."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time


def samples(cfg,pass_name,selected=None):
    fps=cfg['fps'];out=[]
    if fps not in (25,50):raise ValueError('Unsupported timebase')
    for row in cfg['baseline']:
        k,tr,a,b,si,so,media=row
        if k:continue
        key=f'V{tr+1}:{a}-{b}'
        if selected is not None and key not in selected:continue
        offsets=[(b-a-1)//2] if pass_name=='screen' else sorted({0,(b-a-1)//2,b-a-1})
        for offset in offsets:
            out.append({'clip_id':key,'sequence_frame':a+offset,'source_frame_at_sequence_fps':si+offset,
                        'source_seconds':(si+offset)/fps,'media':media,'pass':pass_name})
    if selected is not None and set(selected)-{s['clip_id'] for s in out}:raise ValueError('Unknown selected clip IDs')
    return out


def render(config,out,cache,pass_name,selected=None,workers=2):
    from PIL import Image,ImageDraw
    cfg=json.loads(Path(config).read_text(encoding='utf-8-sig'))
    todo=samples(cfg,pass_name,selected)
    if not todo:raise ValueError('No frames requested')
    if not 1<=workers<=4:raise ValueError('Use 1 to 4 extraction workers')
    binary=shutil.which('ffmpeg')
    if not binary:raise ValueError('ffmpeg is not available')
    out=Path(out);cache=Path(cache);started=time.perf_counter()
    if out.exists():raise ValueError('Use a new report directory')
    # Verify media before creating output; never open or rewrite source media.
    stats={}
    for s in todo:
        p=Path(s['media']).resolve();st=p.stat()
        stats[s['media']]=[str(p),st.st_size,st.st_mtime_ns]
    out.mkdir(parents=True);cache.mkdir(parents=True,exist_ok=True)
    def extract(s):
        token=json.dumps([stats[s['media']],s['source_seconds'],320,180,'samples-v1'])
        key=hashlib.sha256(token.encode()).hexdigest();dest=cache/(key+'.jpg')
        cached=dest.exists()
        if not cached:
            tmp=cache/(key+'.tmp.jpg')
            subprocess.run([binary,'-nostdin','-v','error','-ss',str(s['source_seconds']),'-i',s['media'],
                            '-frames:v','1','-vf','scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2',
                            '-y',str(tmp)],check=True,capture_output=True,timeout=60)
            with Image.open(tmp) as im:im.verify()
            tmp.replace(dest)
        return {**s,'image':str(dest.resolve()),'cache_hit':cached,'media_identity':stats[s['media']]}
    # Deduplicate matching source samples before parallel extraction to prevent
    # two repeated timeline instances writing the same cache entry concurrently.
    unique={}
    for s in todo:unique.setdefault((s['media'],s['source_seconds']),s)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        done=list(pool.map(extract,unique.values()))
    lookup={(s['media'],s['source_seconds']):s for s in done}
    results=[{**lookup[(s['media'],s['source_seconds'])],**s} for s in todo]
    for media,old in stats.items():
        st=Path(media).stat()
        if [str(Path(media).resolve()),st.st_size,st.st_mtime_ns]!=old:raise ValueError('Media changed during sampling')
    sheets=[]
    for offset in range(0,len(results),24):
        subset=results[offset:offset+24];sheet=Image.new('RGB',(1280,210*((len(subset)+3)//4)),(28,28,28));draw=ImageDraw.Draw(sheet)
        for n,s in enumerate(subset):
            x=(n%4)*320;y=(n//4)*210
            with Image.open(s['image']) as im:sheet.paste(im,(x,y))
            draw.text((x+4,y+182),f"{s['clip_id']} F{s['sequence_frame']}",fill='white')
        dest=out/f'contact-{offset//24+1:03}.jpg';sheet.save(dest,quality=90);sheets.append(str(dest.resolve()))
    report={'schema':'track-sort-samples/v1','fps':cfg['fps'],'source_sha256':hashlib.sha256(Path(cfg['source_snapshot']).read_bytes()).hexdigest(),
            'samples':results,'sheets':sheets,'elapsed_seconds':time.perf_counter()-started,
            'visual_review_completed':False,'audio_review_completed':False}
    (out/'samples.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'images':len(results),'sheets':sheets,'cache_hits':sum(d['cache_hit'] for d in done),'elapsed_seconds':report['elapsed_seconds']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('config');p.add_argument('--output',required=True);p.add_argument('--cache',required=True)
    p.add_argument('--pass',dest='pass_name',choices=['screen','candidate'],default='screen');p.add_argument('--clips',nargs='+');p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();print(json.dumps(render(a.config,a.output,a.cache,a.pass_name,a.clips,a.workers),ensure_ascii=False,indent=2))
