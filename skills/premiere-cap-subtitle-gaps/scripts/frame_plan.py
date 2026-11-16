"""Offline expected-state planner. Never contacts or edits Premiere."""
import json
import sys
from pathlib import Path

def plan(data):
    fps, end = data['fps'], data['duration']
    if type(fps) is not int or fps <= 0 or type(end) is not int or end <= 0:
        raise ValueError('Positive integer fps and duration required')
    def intervals(items):
        out = sorted(items)
        for a,b in out:
            if type(a) is not int or type(b) is not int or not 0<=a<b<=end:
                raise ValueError('Invalid frame range')
        return out
    cuts = intervals(data['cuts'])
    if any(b>c for (a,b),(c,d) in zip(cuts,cuts[1:])):
        raise ValueError('Deletion intervals overlap')
    protected=intervals(data['protected'])+intervals(data['cues'])
    if any(a<d and b>c for a,b in cuts for c,d in protected):
        raise ValueError('Deletion intersects a caption or protected content')
    if sum(b-a for a,b in cuts)>=end:
        raise ValueError('Cannot delete the whole sequence')
    rows=sorted(data['rows'])
    for r in rows:
        if len(r)!=7 or any(type(x) is not int for x in r[:6]):
            raise ValueError('Invalid AV row')
        k,tr,a,b,si,so,media=r
        if k not in (0,1) or tr!=0 or not 0<=a<b<=end or si<0 or so-si!=b-a or not media:
            raise ValueError('Only simple single-track 1x media supported')
    video=[r for r in rows if r[0]==0];audio=[r for r in rows if r[0]==1]
    if not video or [r[1:] for r in video]!=[r[1:] for r in audio]:
        raise ValueError('AV ranges differ')
    if video[0][2]!=0 or video[-1][3]!=end or any(a[3]!=b[2] for a,b in zip(video,video[1:])):
        raise ValueError('AV timeline must be continuous without overlaps')
    def mapped(t):return t-sum(max(0,min(t,b)-a) for a,b in cuts)
    result=[]
    for k,tr,a,b,si,so,media in rows:
        segments=[(a,b)]
        for c,d in cuts:
            new=[]
            for x,y in segments:
                if d<=x or c>=y:new.append((x,y))
                else:
                    if x<c:new.append((x,c))
                    if d<y:new.append((d,y))
            segments=new
        for x,y in segments:result.append([k,tr,mapped(x),mapped(y),si+x-a,si+y-a,media])
    return {'rows':sorted(result),'cues':[[mapped(a),mapped(b)] for a,b in data['cues']],
            'duration':mapped(end),'cuts_descending':list(reversed(cuts)),
            'deleted_frames':sum(b-a for a,b in cuts),'premiere_contacted':False}

if __name__=='__main__':
    data=json.loads(Path(sys.argv[1]).read_text('utf-8-sig'))
    result=plan(data)
    with Path(sys.argv[2]).open('x',encoding='utf8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
