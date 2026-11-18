"""Preserve pinned groups and durations; never export intersecting SRT intervals."""
import re


def validate(rows):
    for i, r in enumerate(rows):
        if r['start_ms'] < 0 or r['end_ms'] <= r['start_ms']:
            raise ValueError(f'Invalid output interval at group {i+1}')
        if i and rows[i-1]['end_ms'] > r['start_ms']:
            raise ValueError(f'Overlap blocked: groups {i}/{i+1}, '
                             f"{rows[i-1]['end_ms']-r['start_ms']}ms; no SRT may be delivered")


def schedule(rows, video_end_ms=None, grid_ms=1):
    """Forward fit, then backward fit before fixed barriers. No pin is moved.

    Original placements remain unchanged where possible; this is deterministic,
    not a claim of globally minimum motion or a substitute for picture editing.
    All work is provisional until every bounded span has adequate capacity.
    """
    starts=[r['start_ms'] for r in rows]
    durations=[r['end_ms']-r['start_ms'] for r in rows]
    pins=[i for i,r in enumerate(rows) if r.get('primary_anchor_id')]
    ceiling=None if video_end_ms is None else video_end_ms//grid_ms*grid_ms
    for i in pins:
        if starts[i]<0 or (ceiling is not None and starts[i]+durations[i]>ceiling):
            raise ValueError(f'Fixed anchor outside timeline: group {i+1}; resolve before SRT export')
    for left,right in zip([-1]+pins,pins+[len(rows)]):
        lo=0 if left<0 else starts[left]+durations[left]
        hi=starts[right] if right<len(rows) else ceiling
        needed=sum(durations[left+1:right])
        if hi is not None and lo+needed>hi:
            raise ValueError(f'No non-overlap schedule between fixed boundaries '
                             f'{left+1}/{right+1}: missing {lo+needed-hi}ms; '
                             'keep anchors/text/speed, report conflict, export no SRT')
        edge=lo
        for i in range(left+1,right):
            starts[i]=max(starts[i],edge)
            edge=starts[i]+durations[i]
        if hi is not None:
            edge=hi
            for i in range(right-1,left,-1):
                starts[i]=min(starts[i],edge-durations[i])
                edge=starts[i]
    trial=[dict(r,start_ms=starts[i],end_ms=starts[i]+durations[i]) for i,r in enumerate(rows)]
    validate(trial)
    changes=[]
    for old,new in zip(rows,trial):
        if old['start_ms']!=new['start_ms']:
            assert not old.get('primary_anchor_id')
            changes.append({'group':old['group'],'before_start_ms':old['start_ms'],
                            'before_end_ms':old['end_ms'],'start_ms':new['start_ms'],
                            'end_ms':new['end_ms'],'shift_ms':new['start_ms']-old['start_ms'],
                            'reason':'避免重叠/越界，仅整体移动无锚点段；原时长、文字、顺序不变'})
    for old,new in zip(rows,trial):
        old['start_ms']=new['start_ms'];old['end_ms']=new['end_ms']
    return changes


def validate_srt(text):
    rows=[]
    for block in re.split(r'\r?\n\s*\r?\n',text.strip('\ufeff\r\n')):
        lines=block.splitlines()
        m=re.fullmatch(r'(\d+):(\d{2}):(\d{2}),(\d{3}) --> (\d+):(\d{2}):(\d{2}),(\d{3})',lines[1])
        if not m:raise ValueError('Invalid SRT time during overlap readback')
        v=list(map(int,m.groups()))
        ms=lambda a:((a[0]*60+a[1])*60+a[2])*1000+a[3]
        rows.append({'start_ms':ms(v[:4]),'end_ms':ms(v[4:])})
    validate(rows)


def validate_turn_continuity(rows):
    """A movable run cannot introduce gaps; between pinned groups allow one seam."""
    turns=list(dict.fromkeys(r['turn_id'] for r in rows))
    for turn in turns:
        rr=[r for r in rows if r['turn_id']==turn]
        pins=[i for i,r in enumerate(rr) if r.get('primary_anchor_id')]
        gaps=[i for i in range(len(rr)-1) if rr[i+1]['start_ms']>rr[i]['end_ms']]
        for i in gaps:
            if not any(p<=i for p in pins) or not any(p>i for p in pins):
                raise ValueError(f'Avoidable gap inside speaker turn {turn}: groups '
                                 f"{rr[i]['group']}/{rr[i+1]['group']}; pack movable run")
        for a,b in zip(pins,pins[1:]):
            if sum(a<=i<b for i in gaps)>1:
                raise ValueError(f'Fragmented gaps between fixed anchors in {turn}; consolidate seam')
