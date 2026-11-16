"""Build/replay bounded native Premiere split/move operations; never remove clips.

build is offline. run requires an explicitly supplied existing bridge adapter and
--execute-preview. This utility never installs a bridge or changes its permissions.
"""
import argparse
import hashlib
import importlib.util
import json
import ntpath
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from saved_audit import load, records, link_pairs, audit
from review import validate_review

TICKS_PER_SECOND = 254016000000


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def write(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
    temp.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_rows(rows):
    if not rows:
        raise ValueError('Empty baseline')
    for r in rows:
        if (len(r) != 7 or any(type(v) is not int for v in r[:6]) or r[0] not in (0, 1)
                or min(r[1:6]) < 0 or r[3] <= r[2] or r[3] - r[2] != r[5] - r[4]
                or not isinstance(r[6], str) or not r[6]):
            raise ValueError('Require simple 1x, nonnegative integer-frame AV rows')
    for kind, tr in {(r[0], r[1]) for r in rows}:
        subset = sorted([r for r in rows if r[:2] == [kind, tr]], key=lambda r: r[2])
        if any(a[3] > b[2] for a, b in zip(subset, subset[1:])):
            raise ValueError('Overlapping track items need a separate implementation')
    for kind in (0, 1):
        subset = sorted([r for r in rows if r[0] == kind], key=lambda r: r[2])
        if any(a[3] > b[2] for a, b in zip(subset, subset[1:])):
            raise ValueError('Layered or multichannel overlaps require a separately verified runner')


def one(rows, kind, tr, start, end):
    hits = [r for r in rows if r[:4] == [kind, tr, start, end]]
    if len(hits) != 1:
        raise ValueError('Missing/ambiguous exact clip')
    return hits[0]


def model(rows, cuts, moves):
    check_rows(rows)
    state = sorted([r.copy() for r in rows])
    steps = []
    for spec in cuts:
        fr, vt, at = (spec[k] for k in ('frame', 'video_track', 'audio_track'))
        if any(type(x) is not int or x < 0 for x in (fr, vt, at)):
            raise ValueError('Cut fields must be nonnegative integers')
        hits = [r for r in state if r[:2] == [0, vt] and r[2] < fr < r[3]]
        if len(hits) != 1:
            raise ValueError('Cut is not strictly inside one clip; do not re-cut')
        video = hits[0].copy()
        audio = one(state, 1, at, video[2], video[3]).copy()
        if audio[2:] != video[2:]:
            raise ValueError('Audio source mapping differs')
        before = [r.copy() for r in state]
        for old in (video, audio):
            left, right = old.copy(), old.copy()
            left[3], left[5] = fr, old[4] + fr - old[2]
            right[2], right[4] = fr, left[5]
            state.remove(old)
            state.extend((left, right))
        state.sort()
        steps.append({'type': 'cut', **spec, 'video': video, 'audio': audio,
                      'before': before, 'after': [r.copy() for r in state]})
    for spec in moves:
        a, b, vt, at, dest = (spec[k] for k in ('start', 'end', 'video_track', 'audio_track', 'target_track'))
        if any(type(x) is not int or x < 0 for x in (a, b, vt, at, dest)) or dest not in (1, 2) or dest == vt:
            raise ValueError('Move must target V2/V3 and change track')
        video = one(state, 0, vt, a, b).copy()
        audio = one(state, 1, at, a, b).copy()
        if video[2:] != audio[2:]:
            raise ValueError('Audio source mapping differs')
        if any(r[0] == 0 and r[1] == dest and r[2] < b and a < r[3] for r in state):
            raise ValueError('Destination occupied')
        before = [r.copy() for r in state]
        state.remove(video)
        changed = video.copy()
        changed[1] = dest
        state.append(changed)
        state.sort()
        steps.append({'type': 'move', **spec, 'video': video, 'audio': audio,
                      'before': before, 'after': [r.copy() for r in state]})
    return steps


def window(state, a, b):
    return sorted([r for r in state if r[2] < b and a < r[3]])


def counts(state):
    result = {}
    for r in state:
        key = f'{r[0]}:{r[1]}'
        result[key] = result.get(key, 0) + 1
    return result


def position(states, actual):
    matches = [i for i, s in enumerate(states) if sorted(s) == sorted(actual)]
    if len(matches) != 1:
        raise ValueError('Live state is not one unambiguous completed prefix; inspect, never retry blindly')
    return matches[0]


def header(cfg):
    return ('(function(){if(app.project.path!==' + json.dumps(cfg['preview']) +
            ')throw Error("Wrong preview project");var s=app.project.activeSequence;'
            'if(!s||s.sequenceID!==' + json.dumps(cfg['uid']) + '||String(s.timebase)!==' +
            json.dumps(str(cfg['tpf'])) + ')throw Error("Wrong sequence/timebase");var T=' + str(cfg['tpf']) + ';')


SNAP = r'''
function snap(a,b){var out=[],counts={};for(var k=0;k<2;k++){var ts=k?s.audioTracks:s.videoTracks;
for(var t=0;t<ts.numTracks;t++){var cs=ts[t].clips;if(cs.numItems)counts[k+":"+t]=cs.numItems;
for(var i=0;i<cs.numItems;i++){var c=cs[i],start=Number(c.start.ticks)/T,end=Number(c.end.ticks)/T;
if(start<b&&a<end)out.push([k,t,start,end,Number(c.inPoint.ticks)/T,Number(c.outPoint.ticks)/T,c.projectItem.getMediaPath()]);}}}
return {rows:out,counts:counts};}
function same(a,b){if(a.length!==b.length)return false;for(var i=0;i<a.length;i++)if(JSON.stringify(a[i])!==JSON.stringify(b[i]))return false;return true;}
function rowsort(a,b){for(var i=0;i<6;i++){if(a[i]!==b[i])return a[i]-b[i];}return a[6]<b[6]?-1:a[6]>b[6]?1:0;}
function check(x,expected,c){x.rows.sort(rowsort);if(!same(x.rows,expected))throw Error("Local state mismatch");
for(var k in c)if(x.counts[k]!==c[k])throw Error("Track count mismatch");
for(var k in x.counts)if(c[k]!==x.counts[k])throw Error("Unexpected track contents");}
function exact(tr,row){var hit=null;for(var i=0;i<tr.clips.numItems;i++){var c=tr.clips[i];
if(String(c.start.ticks)===String(row[2]*T)&&String(c.end.ticks)===String(row[3]*T)){
if(hit)throw Error("Duplicate exact clip");hit=c;}}
if(!hit||String(hit.inPoint.ticks)!==String(row[4]*T)||String(hit.outPoint.ticks)!==String(row[5]*T)||hit.projectItem.getMediaPath()!==row[6]||hit.getSpeed()!==1||hit.isSpeedReversed())throw Error("Clip identity/speed mismatch");return hit;}
function clear(){var z=s.getSelection();for(var i=0;i<z.length;i++)z[i].setSelected(0,0);}
'''


def tc(fr, fps):
    return f'{fr//(fps*3600):02}:{fr//(fps*60)%60:02}:{fr//fps%60:02}:{fr%fps:02}'


def operation_script(cfg, op):
    v, a = op['video'], op['audio']
    lo, hi = max(0, v[2]-1), v[3]+1
    script = header(cfg) + SNAP
    script += f'check(snap({lo},{hi}),{json.dumps(window(op["before"],lo,hi))},{json.dumps(counts(op["before"]))});'
    script += f'var vr={json.dumps(v)},ar={json.dumps(a)};var v=exact(s.videoTracks[{v[1]}],vr),a=exact(s.audioTracks[{a[1]}],ar);if(v.projectItem.nodeId!==a.projectItem.nodeId)throw Error("AV item differs");if(s.videoTracks[{v[1]}].isLocked()||s.audioTracks[{a[1]}].isLocked())throw Error("Source track locked");app.enableQE();var q=qe.project.getActiveSequence();if(!q||String(q.guid)!==String(s.sequenceID))throw Error("QE sequence identity mismatch");'
    if op['type'] == 'cut':
        frame = op['frame']
        right_v, right_a = v.copy(), a.copy()
        for row in (right_v, right_a):
            row[4] += frame-row[2]
            row[2] = frame
        script += f'q.getVideoTrackAt({v[1]}).razor("{tc(frame,cfg["fps"])}");q.getAudioTrackAt({a[1]}).razor("{tc(frame,cfg["fps"])}");clear();'
        script += f'exact(s.videoTracks[{v[1]}],{json.dumps(right_v)}).setSelected(1,0);exact(s.audioTracks[{a[1]}],{json.dumps(right_a)}).setSelected(1,0);if(s.getSelection().length!==2)throw Error("Unexpected selection");s.linkSelection();clear();'
    else:
        dest = op['target_track']
        script += f'if(s.videoTracks.numTracks<={dest})throw Error("Destination track absent");if(s.videoTracks[{dest}].isLocked())throw Error("Destination track locked");var tr=q.getVideoTrackAt({v[1]}),hit=null;'
        script += 'for(var i=0;i<tr.numItems;i++){var c=tr.getItemAt(i);if(c.type==="Clip"&&String(c.start.ticks)===String(vr[2]*T)&&String(c.end.ticks)===String(vr[3]*T)){if(hit)throw Error("QE duplicate");hit=c;}}if(!hit)throw Error("QE clip absent");'
        script += f'hit.moveToTrack({dest-v[1]},0,"00:00:00:00",false);'
    script += f'var result=snap({lo},{hi});check(result,{json.dumps(window(op["after"],lo,hi))},{json.dumps(counts(op["after"]))});return JSON.stringify(result);}})()'
    return script


def build(config, folder):
    cfg = read(config)
    if cfg['fps'] not in (25, 50) or cfg['tpf'] != TICKS_PER_SECOND // cfg['fps']:
        raise ValueError('Only integer 25/50 fps plans supported; other timebases need validation')
    for key in ('source_snapshot', 'main_project', 'preview'):
        if not ntpath.isabs(cfg[key]):
            raise ValueError('Absolute project paths required')
    preview = ntpath.normcase(str(Path(cfg['preview']).resolve()))
    if any(preview == ntpath.normcase(str(Path(cfg[k]).resolve())) for k in ('source_snapshot', 'main_project')):
        raise ValueError('This runner only writes an independent preview')
    root, ix, ux = load(cfg['source_snapshot'])
    recs = records(ix, ux, cfg['uid'], cfg['tpf'])
    link_pairs(ix, ux, cfg['uid'], recs)
    rows = [r for r, _ in recs]
    if cfg.get('baseline') is not None and sorted(cfg['baseline']) != rows:
        raise ValueError('Provided baseline differs from saved snapshot')
    ops = model(rows, cfg['cuts'], cfg['moves'])
    evidence = validate_review(cfg, rows)
    for k in ('main_project', 'preview'):
        if Path(cfg[k]).exists() and Path(cfg[k]).samefile(cfg['source_snapshot']):
            raise ValueError('Source, snapshot and preview must be separate physical files')
    if Path(cfg['preview']).exists() and Path(cfg['main_project']).exists() and Path(cfg['preview']).samefile(cfg['main_project']):
        raise ValueError('Preview aliases the main project')
    audit(cfg['source_snapshot'], cfg['preview'], cfg['uid'], cfg['tpf'], rows)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copy2(cfg['source_snapshot'], folder/'baseline.prproj')
    shutil.copy2(cfg['review'], folder/'review.json')
    scripts = {'shape.jsx': header(cfg)+SNAP+'return JSON.stringify(snap(0,Infinity));})()',
               'save.jsx': header(cfg)+'app.project.save();return JSON.stringify({saved:true});})()'}
    for i, op in enumerate(ops):
        name = f'{i:04}_{op["type"]}.jsx'
        op['script'] = name
        scripts[name] = operation_script(cfg, op)
    for name, script in scripts.items():
        (folder/name).write_text(script, 'utf-8')
    manifest = {'config': cfg, 'baseline': rows, 'baseline_sha256': digest(folder/'baseline.prproj'),
                'review_sha256': digest(folder/'review.json'), 'review_summary': evidence,
                'ops': ops, 'scripts_sha256': {n: digest(folder/n) for n in scripts}}
    write(folder/'plan.json', manifest)
    print(json.dumps({'prepared_cuts': len(cfg['cuts']), 'prepared_moves': len(cfg['moves']),
                      'premiere_contacted': False, 'bundle': str(folder.resolve())}, ensure_ascii=False))


def run(folder, adapter, limit, until_complete=False):
    if limit < 1:
        raise ValueError('Batch size must be positive')
    metrics = {'started_utc': datetime.now(timezone.utc).isoformat(), 'seconds': {}, 'calls': {}}
    started = time.perf_counter()
    def timed(category, fn, *args):
        at = time.perf_counter()
        try:
            return fn(*args)
        finally:
            metrics['seconds'][category] = metrics['seconds'].get(category, 0) + time.perf_counter()-at
            metrics['calls'][category] = metrics['calls'].get(category, 0) + 1
    try:
        result = _run(folder, adapter, limit, until_complete, timed)
        metrics['outcome'] = 'completed' if result['completed'] == result['total'] else 'batch_complete'
        metrics['progress'] = result
        return result
    except Exception as exc:
        metrics['outcome'] = 'failed'
        metrics['error_type'] = type(exc).__name__
        raise
    finally:
        metrics['elapsed_seconds'] = time.perf_counter()-started
        # Separate per-run files avoid overwriting earlier interruption evidence.
        if Path(folder).is_dir():
            write(Path(folder)/('timing-'+str(time.time_ns())+'.json'), metrics)


def _run(folder, adapter, limit, until_complete, timed):
    folder = Path(folder)
    p = read(folder/'plan.json')
    cfg = p['config']
    if digest(folder/'baseline.prproj') != p['baseline_sha256']:
        raise ValueError('Frozen baseline changed')
    for n, expected in p['scripts_sha256'].items():
        if Path(n).name != n:
            raise ValueError('Script must be inside the operation bundle')
        if digest(folder/n) != expected:
            raise ValueError('Prepared script changed: '+n)
    if not p.get('review_sha256') or digest(folder/'review.json') != p['review_sha256']:
        raise ValueError('Classification review missing or changed')
    validation_cfg = dict(cfg, source_snapshot=str(folder/'baseline.prproj'), review=str(folder/'review.json'))
    validate_review(validation_cfg, p['baseline'])
    spec = importlib.util.spec_from_file_location('authorized_pr_adapter', adapter)
    sys.path.insert(0, str(Path(adapter).resolve().parent))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def call(name):
        category = 'full_read' if name == 'shape.jsx' else 'save' if name == 'save.jsx' else 'mutation_and_local_check'
        result = timed(category, module.run_pr_script, (folder/name).read_text('utf-8'))
        if isinstance(result, str):
            result = json.loads(result)
        if isinstance(result, dict) and result.get('error'):
            raise RuntimeError(result['error'])
        return result
    states = [p['baseline']] + [x['after'] for x in p['ops']]
    current = position(states, call('shape.jsx')['rows'])
    journal_path = folder/'progress.json'
    if journal_path.exists():
        journal = read(journal_path)
        if journal['plan_sha256'] != digest(folder/'plan.json') or current not in (journal['completed'], journal['completed']+1):
            raise ValueError('Progress diverged; inspect before continuing')
    elif current != 0:
        raise ValueError('Missing journal for a modified preview; inspect first')
    # Full saved-file link/effect audit before continuing after any interruption.
    def save_audit(at):
        call('save.jsx')
        result = timed('saved_file_audit', audit, folder/'baseline.prproj', cfg['preview'], cfg['uid'], cfg['tpf'], states[at])
        write(folder/f'audit-{at}.json', result)
        return result
    def checkpoint(completed, audited):
        write(journal_path, {'plan_sha256': digest(folder/'plan.json'), 'completed': completed, 'saved_audited': audited})
    if current:
        save_audit(current)
    else:
        timed('saved_file_audit', audit, folder/'baseline.prproj', cfg['preview'], cfg['uid'], cfg['tpf'], states[0])
    audited = current
    checkpoint(current, audited)
    while current < len(p['ops']):
        end = min(len(p['ops']), current+limit)
        for i in range(current, end):
            op = p['ops'][i]
            result = call(op['script'])
            lo, hi = max(0, op['video'][2]-1), op['video'][3]+1
            if sorted(result['rows']) != window(op['after'], lo, hi) or result['counts'] != counts(op['after']):
                raise ValueError('Returned local result differs; inspect before retry')
            checkpoint(i+1, audited)
            print(f'Verified local state {i+1}/{len(p["ops"])}', flush=True)
            # Audit the initial action and first necessary split BEFORE another mutation.
            pilot = i == 0 or (op['type'] == 'cut' and not any(x['type'] == 'cut' for x in p['ops'][:i]))
            if pilot and i+1 < end:
                if sorted(call('shape.jsx')['rows']) != states[i+1]:
                    raise ValueError('Pilot global state differs')
                save_audit(i+1)
                audited = i+1
                checkpoint(i+1, audited)
        if sorted(call('shape.jsx')['rows']) != states[end]:
            raise ValueError('Phase global state differs; no automatic retry')
        result = save_audit(end)
        current = audited = end
        checkpoint(current, audited)
        print(json.dumps({'completed': current, 'total': len(p['ops']), 'saved_audit': result}, ensure_ascii=False), flush=True)
        if not until_complete:
            break
        # No repeat startup/save here: this uninterrupted process just audited this state.
    return {'completed': current, 'total': len(p['ops'])}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build'); b.add_argument('config'); b.add_argument('bundle')
    r = sub.add_parser('run'); r.add_argument('bundle'); r.add_argument('--adapter', required=True)
    r.add_argument('--limit', type=int, default=20); r.add_argument('--execute-preview', action='store_true')
    r.add_argument('--until-complete', action='store_true', help='Continue batches in this process; preserve batch-end audits')
    args = ap.parse_args()
    if args.command == 'build':
        build(args.config, args.bundle)
    else:
        if not args.execute_preview or args.limit < 1:
            ap.error('run requires --execute-preview and a positive --limit')
        run(args.bundle, args.adapter, args.limit, args.until_complete)
