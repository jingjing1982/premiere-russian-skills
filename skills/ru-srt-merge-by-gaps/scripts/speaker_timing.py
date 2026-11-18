"""Speaker-turn mode: minimum cue groups, first marker fixed, explicit seam reports."""
import argparse,json,re,hashlib
from fractions import Fraction as F
from math import ceil
from pathlib import Path
from gesture_timing import require,flat,count,spoken,fmt,rounded
from speaker_guard import validate_speakers,check_group
from nonoverlap import schedule,validate as validate_nonoverlap,validate_srt,validate_turn_continuity

def make_groups(cues,turns,speed,grid,forbidden_cuts=(),max_ms=90000):
    cmap={c['id']:c for c in cues};out=[]
    for turn in turns:
        cs=[cmap[i] for i in turn['cue_ids']];n=len(cs);prefix=[0]
        for c in cs:prefix.append(prefix[-1]+count(spoken(c)))
        sentence=lambda j:j==n or bool(re.search(r'[.!?…][»”"\)\]]*\s*$',cs[j-1]['ru']))
        # Try complete sentence endings first. Only if impossible permit cue cuts.
        for relaxed in (False,True):
            dp=[None]*(n+1);dp[0]=((0,0,0),[])
            for j in range(1,n+1):
                if j<n and cs[j-1]['id'] in forbidden_cuts:continue
                if not relaxed and not sentence(j):continue
                for i in range(j-1,-1,-1):
                    duration=ceil(F((prefix[j]-prefix[i])*1000)/speed/grid)*grid
                    raw=cs[j-1]['end_ms']-cs[i]['start_ms']
                    if raw>max_ms or duration>max_ms:break
                    if not dp[i] or duration<=0:continue
                    old,path=dp[i];cost=(old[0]+1,old[1]+int(not sentence(j)),old[2]+duration*duration)
                    if dp[j] is None or cost<dp[j][0]:dp[j]=(cost,path+[(i,j)])
            if dp[n] is not None:break
        require(dp[n] is not None,'A single cue exceeds configured cap; do not split text silently')
        for i,j in dp[n][1]:out.append({'turn_id':turn['id'],'cue_ids':[c['id'] for c in cs[i:j]],'sentence_end':sentence(j),'sentence_split_exception':not sentence(j)})
    return out

def solve(plan):
    max_ms=plan.get("max_duration_ms",90000)
    require(type(max_ms) is int and max_ms>0,"Invalid duration cap")
    require(plan.get("extra_pause_ms",0)==0,"Extra pauses are unsupported")
    require(plan.get('mode')=='speaker_first_anchor','Explicit speaker_first_anchor mode required')
    speed=F(str(plan.get('speed','5.2')));grid=plan.get('grid_ms',1)
    require(speed>0 and isinstance(grid,int) and grid>0,'Bad speed/grid')
    cues=plan['cues'];turns=plan['turns'];anchors=plan.get('anchors',[])
    ids=[c['id'] for c in cues];require(cues and len(ids)==len(set(ids)),'Empty/duplicate source cues')
    attribution=validate_speakers(plan)
    require([i for t in turns for i in t['cue_ids']]==ids,'Turns must cover every cue once in order')
    require(len({t['id'] for t in turns})==len(turns),'Duplicate turn IDs')
    cmap={c['id']:c for c in cues};tmap={t['id']:t for t in turns};counts={};source_issues=[]
    for j,c in enumerate(cues):
        require(c['start_ms']>=0 and c['end_ms']>c['start_ms'],'Bad source time')
        require(c['end_ms']-c['start_ms']<=max_ms,'A single cue exceeds configured cap; do not split text silently')
        require(not j or c['start_ms']>=cues[j-1]['start_ms'],'Source cues out of chronological order')
        require(c.get('ru') and c.get('zh') and re.search('[А-Яа-яЁё]',c['ru']),'Missing bilingual source')
        require('\n' not in flat(c['ru']) and '\n' not in flat(c['zh']),'Bad source lines')
        counts[c['id']]=count(spoken(c))
        if j and c['start_ms']<cues[j-1]['end_ms']:source_issues.append({'before':cues[j-1]['id'],'after':c['id'],'overlap_ms':cues[j-1]['end_ms']-c['start_ms']})
    require(len({a['id'] for a in anchors})==len(anchors),'Duplicate anchor IDs')
    for a in anchors:
        require(a['cue_id'] in cmap and a['time_ms']>=0,'Invalid anchor source')
        c=cmap[a['cue_id']];o=a['char_offset'];target=a['target_ru']
        require(0<=o<=len(c['ru']) and c['ru'][o:o+len(target)]==target,'Anchor text/offset mismatch: '+a['id'])
        require((target or a.get('alignment_basis')) and a.get('evidence'),'Anchor lacks basis/evidence')
    groups=plan.get('groups') or make_groups(cues,turns,speed,grid,plan.get('forbidden_cut_after',[]),max_ms)
    require([i for g in groups for i in g['cue_ids']]==ids,'Groups must cover every cue once in order')
    rows=[]
    for gi,g in enumerate(groups,1):
        check_group(g['cue_ids'],attribution)
        require(g['turn_id'] in tmap,'Unknown turn')
        turn=tmap[g['turn_id']];cs=[cmap[i] for i in g['cue_ids']]
        require(cs and all(i in turn['cue_ids'] for i in g['cue_ids']),'Group crosses speaker turn')
        raw=cs[-1]['end_ms']-cs[0]['start_ms'];n=sum(counts[c['id']] for c in cs)
        dur=ceil(F(n*1000)/speed/grid)*grid
        require(raw<=max_ms and 0<dur<=max_ms,'Group outside configured cap')
        aa=[];prefix=0
        for c in cs:
            for a in anchors:
                if a['cue_id']==c['id']:
                    p=prefix+count(spoken(c,a['char_offset']));off=F(p*1000)/speed
                    aa.append({'source':a,'prefix':p,'offset':off,'ideal':F(a['time_ms'])-off})
            prefix+=counts[c['id']]
        aa.sort(key=lambda a:(a['source']['time_ms'],a['source']['id']))
        rows.append({'group':gi,'turn_id':g['turn_id'],'speaker':turn['speaker'],'cue_ids':g['cue_ids'],
          'source_start_ms':cs[0]['start_ms'],'source_end_ms':cs[-1]['end_ms'],'source_span_ms':raw,
          'duration_ms':dur,'syllables':n,'primary_anchor_id':aa[0]['source']['id'] if aa else None,
          'anchors_internal':aa,'ru':' '.join(flat(c['ru']) for c in cs),'zh':' '.join(flat(c['zh']) for c in cs),
          'sentence_split_exception':g.get('sentence_split_exception',False)})
    approved={}
    primary_ids={r['primary_anchor_id'] for r in rows if r['primary_anchor_id']}
    for change in plan.get('approved_anchor_shifts',[]):
        aid=change.get('anchor_id');shift=change.get('shift_ms')
        require(aid in primary_ids and aid not in approved,'Invalid/duplicate approved primary anchor shift')
        require(type(shift) is int and shift%grid==0 and bool(change.get('authorization')),
                'Anchor shift requires explicit recorded user decision and frame-aligned milliseconds')
        approved[aid]=change
    for turn in turns:
        rr=[r for r in rows if r['turn_id']==turn['id']];anchored=[i for i,r in enumerate(rr) if r['anchors_internal']]
        if anchored:
            first=anchored[0]
            for i in anchored:
                aid=rr[i]['primary_anchor_id']
                rr[i]['start_ms']=rounded(rr[i]['anchors_internal'][0]['ideal'],grid)+approved.get(aid,{}).get('shift_ms',0)
                rr[i]['placement']='first_anchor'
            for i in range(first-1,-1,-1):rr[i]['start_ms']=rr[i+1]['start_ms']-rr[i]['duration_ms'];rr[i]['placement']='backfill_to_first_anchor'
            for i in range(first+1,len(rr)):
                if not rr[i]['anchors_internal']:rr[i]['start_ms']=rr[i-1]['start_ms']+rr[i-1]['duration_ms'];rr[i]['placement']='continue_previous'
        else:
            # Keep a whole unanchored turn together at its original end: put
            # spare time at the handoff, not inside/after a continuous answer.
            block_start=rounded(F(rr[-1]['source_end_ms']),grid)-sum(r['duration_ms'] for r in rr)
            for i,r in enumerate(rr):
                r['start_ms']=block_start if i==0 else rr[i-1]['start_ms']+rr[i-1]['duration_ms']
                r['placement']='source_turn_end_backfill' if i==0 else 'continue_previous'
        for r in rr:r['end_ms']=r['start_ms']+r['duration_ms']
    timing_adjustments=schedule(rows,plan.get('video_end_ms'),grid)
    validate_turn_continuity(rows)
    anchor_rows=[]
    for r in rows:
        for a in r.pop('anchors_internal'):
            src=a['source'];pred=F(r['start_ms'])+a['offset'];alt=rounded(a['ideal'],grid)
            anchor_rows.append({'id':src['id'],'group':r['group'],'turn_id':r['turn_id'],'cue_id':src['cue_id'],
              'marker_ms':src['time_ms'],'target_ru':src['target_ru'],'target_zh':src.get('target_zh',''),
              'alignment_basis':src.get('alignment_basis','word_or_phrase_start'),'primary':src['id']==r['primary_anchor_id'],
              'prefix_syllables':a['prefix'],'predicted_ms':float(pred),'error_ms':float(pred-src['time_ms']),
              'within_2s':abs(pred-src['time_ms'])<=2000,'alternative_start_ms':alt,'alternative_end_ms':alt+r['duration_ms'],
              'shift_ms':alt-r['start_ms'],'evidence':src['evidence']})
    require(len(anchor_rows)==len(anchors),'Anchor omitted from output')
    joins=[]
    for a,b in zip(rows,rows[1:]):
        gap=b['start_ms']-a['end_ms'];same=a['turn_id']==b['turn_id']
        joins.append({'before_group':a['group'],'after_group':b['group'],'same_turn':same,'gap_ms':gap,
          'source_gap_ms':b['source_start_ms']-a['source_end_ms'],'needs_review':gap<0 or (same and gap!=0)})
    issues=[]
    for r in rows:
        t=tmap[r['turn_id']];lo=cmap[t['cue_ids'][0]]['start_ms'];hi=cmap[t['cue_ids'][-1]]['end_ms']
        if r['start_ms']<lo:issues.append({'group':r['group'],'type':'before_turn_source_start','ms':lo-r['start_ms']})
        if r['end_ms']>hi:issues.append({'group':r['group'],'type':'after_turn_source_end','ms':r['end_ms']-hi})
        if r['start_ms']<0:issues.append({'group':r['group'],'type':'negative_start','ms':-r['start_ms']})
        if 'video_end_ms' in plan and r['end_ms']>plan['video_end_ms']:issues.append({'group':r['group'],'type':'video_overflow','ms':r['end_ms']-plan['video_end_ms']})
        if r['sentence_split_exception']:issues.append({'group':r['group'],'type':'sentence_split_at_cue_boundary'})
    conflicts=bool(source_issues or issues or any(j['needs_review'] for j in joins) or any(not a['within_2s'] for a in anchor_rows))
    return {'source':plan.get('source'),'speaker_review':plan['speaker_review'],'speaker_attribution_checked':True,
      'mode':plan['mode'],'max_duration_ms':max_ms,'speed':str(speed),'grid_ms':grid,'turns':turns,
      'groups':rows,'anchors':anchor_rows,'joins':joins,'source_issues':source_issues,'boundary_issues':issues,
      'timing_adjustments':timing_adjustments,'approved_anchor_shifts':list(approved.values()),'nonoverlap_verified':True,
      'unanchored_turn_policy':'backfill_from_source_turn_end','avoidable_internal_gaps_verified':True,
      'status':'review_conflicts' if conflicts else 'estimated_not_audio_verified',
      'minimum_groups_under_sentence_and_90s_constraints':len(rows) if not plan.get('groups') else None}

def export(plan,output):
    max_ms=plan.get("max_duration_ms",90000)
    result=solve(plan);out=Path(output)
    validate_nonoverlap(result['groups'])
    validate_turn_continuity(result['groups'])
    require(not any(r['start_ms']<0 for r in result['groups']),'Negative start: report/resolve before SRT export, do not clamp')
    suffix='核对稿' if result['status']=='review_conflicts' else '规划稿'
    srt=out/('合并双语_'+suffix+'.srt');report=out/'计算与定位.json'
    require(not srt.exists() and not report.exists() and not (out/'定位报告.md').exists(),'Output exists')
    text='\n\n'.join(f"{r['group']}\n{fmt(r['start_ms'])} --> {fmt(r['end_ms'])}\n{r['ru']}\n{r['zh']}" for r in result['groups'])+'\n'
    out.mkdir(parents=True,exist_ok=True);srt.write_bytes(b'\xef\xbb\xbf'+text.replace('\n','\r\n').encode('utf-8'))
    saved=srt.read_text('utf-8-sig');validate_srt(saved)
    blocks=saved.strip('\n').split('\n\n');cmap={c['id']:c for c in plan['cues']}
    require(len(blocks)==len(result['groups']),'SRT readback count')
    for block,r in zip(blocks,result['groups']):
        lines=block.split('\n');cs=[cmap[i] for i in r['cue_ids']]
        require(len(lines)==4 and lines[0]==str(r['group']) and lines[1]==f"{fmt(r['start_ms'])} --> {fmt(r['end_ms'])}",'SRT structure/time readback')
        require(lines[2]==' '.join(flat(c['ru']) for c in cs) and lines[3]==' '.join(flat(c['zh']) for c in cs),'SRT differs from source text')
        require(0<r['end_ms']-r['start_ms']<=max_ms,'SRT duration')
    result['srt_sha256']=hashlib.sha256(srt.read_bytes()).hexdigest();result['text_readback_verified']=True
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    from speaker_report import write_report
    write_report(result,out/'定位报告.md')
    return srt,report,result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('plan');p.add_argument('output_directory');a=p.parse_args()
    s,r,d=export(json.loads(Path(a.plan).read_text('utf-8-sig')),a.output_directory)
    print(json.dumps({'srt':str(s.resolve()),'report':str(r.resolve()),'groups':len(d['groups']),'status':d['status']},ensure_ascii=False))
