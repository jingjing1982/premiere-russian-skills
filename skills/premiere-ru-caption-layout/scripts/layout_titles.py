"""Exact-text layout candidates with explicit title spans and per-cue font profiles.
Never edits PR; all rendered fit statuses remain unverified until checked in PR.
"""
import argparse, hashlib, json, re
from pathlib import Path
from PIL import ImageFont

def choose(text,width,measure,titles,preferred=3,ratio=.8,allow_scripture=True):
    spans=sorted((t['start'],t['end']) for t in titles)
    if any(a[1]>b[0] for a,b in zip(spans,spans[1:])):raise ValueError('Overlapping title spans need review')
    for title in titles:
        a,b=title['start'],title['end']
        if not (0<=a<b<=len(text)) or text[a:b]!=title['text'] or title['kind'] not in ('scripture','treatise','book'):
            raise ValueError('Invalid or stale protected title span')
    if measure(text)<=width:return [text],'one_line',[]
    options=[]
    for m in re.finditer(' ',text):
        pos=m.start();left,right=text[:pos],text[pos+1:]
        # Do not cut a word, split repeated space runs, or detach punctuation.
        if not left or not right or left[-1].isspace() or right[0].isspace():continue
        if left[-1] in '«“([{—' or right[0] in '»”)]},.;:!?—':continue
        lw,rw=measure(left),measure(right)
        if max(lw,rw)>width:continue
        tail=sum(any(c.isalnum() for c in t) for t in right.split())
        if tail<2:continue
        broken=[t for t in titles if t['start']<=pos<t['end']]
        rank=0 if tail==preferred else 1 if tail==2 else 2 if tail>preferred else 3
        options.append({'rows':[left,right],'broken':broken,'lw':lw,'rw':rw,'tail':tail,'rank':rank})
    safe=[o for o in options if not o['broken']]
    def select(opts):
        longer=[o for o in opts if o['lw']>o['rw']]
        if longer:
            first=sorted(longer,key=lambda o:(o['rank'],o['tail']))[0]
            two=[o for o in longer if o['tail']==2]
            if first['tail']==preferred and first['rw']/first['lw']>=ratio and two:return two[0]
            return first
        return min(opts,key=lambda o:(o['rank'],o['tail'])) if opts and titles else None
    picked=select(safe)
    if picked:return picked['rows'],'title_safe' if titles else 'two_lines',[]
    # Only scripture titles have this explicitly defined exception.
    if allow_scripture:
        permitted=[o for o in options if o['broken'] and all(t['kind']=='scripture' for t in o['broken'])]
        picked=select(permitted)
        if picked:return picked['rows'],'long_scripture_wrap',[t['text'] for t in picked['broken']]
    return None,'unresolved',[]

def process(source,manifest,output,report):
    source,manifest,output,report=map(Path,(source,manifest,output,report))
    if len({p.resolve() for p in (source,manifest,output,report)})!=4 or output.exists() or report.exists():raise ValueError('Distinct new output/report required')
    raw=source.read_bytes();spec=json.loads(manifest.read_text(encoding='utf-8-sig'))
    if spec['input_sha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('Stale layout manifest')
    prefs=spec.get('preferences',{});tail=prefs.get('preferred_tail_words',3);ratio=prefs.get('near_balance_ratio',.8)
    if type(tail)!=int or tail<2 or not 0<ratio<=1:raise ValueError('Invalid layout preferences')
    s=raw.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
    blocks=re.split(r'\n[ \t]*\n',s.rstrip('\n'));result=[];checks=[];times=[];fonts={}
    for b in blocks:
        lines=b.split('\n');cid=lines[0]
        if len(lines)<4 or not cid.isdigit():raise ValueError('Invalid cue')
        match=re.fullmatch(r'(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3}) --> (\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})',lines[1])
        if not match:raise ValueError('Invalid time')
        v=list(map(int,match.groups()));times.append((cid,*[((v[k]*60+v[k+1])*60+v[k+2])*1000+v[k+3] for k in (0,4)]))
        setting=spec['cues'].get(cid);status='unreviewed_preserved';exceptions=[];newlines=lines[:]
        if setting and setting.get('title_reviewed') is True and setting.get('calibration_reference'):
            n=setting['ru_line_count']
            if type(n)!=int or not 1<=n<len(lines)-2:raise ValueError('Invalid Russian line boundary')
            ru=' '.join(lines[2:2+n]);ch=lines[2+n:]
            if not re.search('[А-Яа-яЁё]',ru) or re.search('[\u3400-\u9fff]',ru):raise ValueError('Ambiguous Russian source boundary')
            prof=spec['profiles'][setting['profile']]
            if prof.get('mixed_styles'):status='mixed_style_preserved'
            else:
                fontpath=Path(prof['font_file']);fontpath=fontpath if fontpath.is_absolute() else manifest.parent/fontpath
                if hashlib.sha256(fontpath.read_bytes()).hexdigest()!=prof['font_sha256']:raise ValueError('Font file changed')
                size=prof['font_size_px'];width=setting['max_width_px'];scale=prof.get('horizontal_scale',1);tracking=prof.get('tracking_px',0)
                if size<=0 or width<=0 or scale<=0:raise ValueError('Invalid measured geometry')
                key=(str(fontpath),size,prof.get('font_index',0))
                if key not in fonts:fonts[key]=ImageFont.truetype(str(fontpath),size,index=key[2])
                font=fonts[key]
                measure=lambda t:(font.getlength(t)+max(0,len(t)-1)*tracking)*scale
                rows,status,exceptions=choose(ru,width,measure,setting['titles'],tail,ratio,prefs.get('long_scripture_exception',True))
                if rows is not None:
                    if ' '.join(rows)!=ru or len(rows)>2:raise ValueError('Text/line invariant failed')
                    newlines=lines[:2]+rows+ch
            if newlines[:2]!=lines[:2] or newlines[-len(ch):]!=ch:raise ValueError('Chinese/timing changed')
        result.append('\n'.join(newlines));checks.append({'cue':cid,'time':lines[1],'status':status,'changed':newlines!=lines,
          'title_exceptions':exceptions,'PR_visual_status':'unverified'})
    if len({t[0] for t in times})!=len(times):raise ValueError('Duplicate cue IDs')
    gaps=[{'before':a[0],'after':b[0],'gap_ms':b[1]-a[2],
      'class':'overlap' if b[1]<a[2] else 'open_le_2s' if b[1]-a[2]<=2000 else 'keep_gt_2s'} for a,b in zip(times,times[1:]) if b[1]!=a[2]]
    if source.read_bytes()!=raw:raise ValueError('Source changed')
    with output.open('xb') as f:f.write(b'\xef\xbb\xbf'+('\r\n\r\n'.join(b.replace('\n','\r\n') for b in result)+'\r\n').encode())
    got=re.split(r'\n[ \t]*\n',output.read_text(encoding='utf-8-sig').rstrip('\n'))
    if got!=result:raise ValueError('Readback mismatch')
    data={'source_sha256':hashlib.sha256(raw).hexdigest(),'text_time_verified':True,'premiere_verified':False,'cues':checks,'gaps':gaps}
    with report.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    return data
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('manifest');p.add_argument('output');p.add_argument('report');a=p.parse_args()
    d=process(a.source,a.manifest,a.output,a.report);print(json.dumps({'cues':len(d['cues']),'text_time_verified':True,'premiere_verified':False},ensure_ascii=False))
