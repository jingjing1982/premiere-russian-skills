"""Prepare exact, guarded bridge requests offline. Never connects or installs a bridge."""
import argparse
import json
import ntpath
from pathlib import Path
from track_sort import SNAP, TICKS_PER_SECOND, digest, header, read, write
from review import validate_review


def source_header(cfg):
    return ('(function(){if(app.project.path!==' + json.dumps(cfg['main_project']) +
            ')throw Error("Wrong source project");var s=null;'
            'for(var i=0;i<app.project.sequences.numSequences;i++){var x=app.project.sequences[i];'
            'if(x.sequenceID===' + json.dumps(cfg['uid']) + ')s=x;}'
            'if(!s||String(s.timebase)!==' + json.dumps(str(cfg['tpf'])) +
            ')throw Error("Wrong source sequence/timebase");var T=' + str(cfg['tpf']) + ';')


PREFLIGHT = '''var out={path:app.project.path,uid:s.sequenceID,timebase:String(s.timebase),tracks:[],media:[]},seen={};
for(var k=0;k<2;k++){var tracks=k?s.audioTracks:s.videoTracks;
for(var t=0;t<tracks.numTracks;t++){var tr=tracks[t];
out.tracks.push({kind:k,index:t,locked:tr.isLocked(),muted:tr.isMuted(),clips:tr.clips.numItems});
for(var i=0;i<tr.clips.numItems;i++){var p=tr.clips[i].projectItem;
if(!p)throw Error("Nonstandard media item");var key=String(p.nodeId);
if(!seen[key]){seen[key]=true;out.media.push({path:p.getMediaPath(),offline:p.isOffline()});}}}}
return JSON.stringify(out);})()'''


def prepare(bundles, output):
    loaded = []
    for directory in bundles:
        directory = Path(directory).resolve()
        plan = read(directory/'plan.json')
        cfg = plan['config']
        if cfg['fps'] not in (25, 50) or cfg['tpf'] != TICKS_PER_SECOND//cfg['fps']:
            raise ValueError('Unsupported timebase')
        for key in ('main_project', 'preview', 'source_snapshot'):
            if not ntpath.isabs(cfg[key]):
                raise ValueError('Absolute project paths required')
        if ntpath.normcase(cfg['preview']) in {ntpath.normcase(cfg[k]) for k in ('main_project', 'source_snapshot')}:
            raise ValueError('Preview must be independent')
        if digest(directory/'baseline.prproj') != plan['baseline_sha256']:
            raise ValueError('Frozen baseline changed')
        if not plan.get('review_sha256') or digest(directory/'review.json') != plan['review_sha256']:
            raise ValueError('Classification review missing or changed')
        validate_review(dict(cfg, source_snapshot=str(directory/'baseline.prproj'),
                             review=str(directory/'review.json')), plan['baseline'])
        for name, expected in plan['scripts_sha256'].items():
            if Path(name).name != name or digest(directory/name) != expected:
                raise ValueError('Invalid or changed script: '+name)
        loaded.append((directory, plan))
    if not loaded:
        raise ValueError('At least one prepared operation bundle is required')
    mains = {ntpath.normcase(p['config']['main_project']) for _, p in loaded}
    if any(ntpath.normcase(p['config']['preview']) in mains for _, p in loaded):
        raise ValueError('A preview cannot be another supplied main project')
    allowed = sorted({p['config'][k] for _, p in loaded for k in ('main_project', 'preview')})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'premiere_contacted': False, 'bridge_installed': False, 'requests': [], 'operation_bundles': []}
    for number, (directory, plan) in enumerate(loaded, 1):
        cfg = plan['config']
        # ExtendScript uses an ES3-compatible loop, not Array.indexOf.
        open_script = ('(function(){var paths=' + json.dumps(allowed) + ';var ok=false;'
                       'for(var j=0;j<paths.length;j++){if(app.project.path===paths[j])ok=true;}'
                       'if(!ok)throw Error("Unexpected current project");'
                       'app.openDocument(' + json.dumps(cfg['preview']) + ');'
                       'if(app.project.path!==' + json.dumps(cfg['preview']) + ')throw Error("Preview did not open");'
                       'return JSON.stringify({path:app.project.path});})()')
        activate = ('(function(){if(app.project.path!==' + json.dumps(cfg['preview']) +
                    ')throw Error("Wrong preview project");app.project.openSequence(' + json.dumps(cfg['uid']) +
                    ');var s=app.project.activeSequence;if(!s||s.sequenceID!==' + json.dumps(cfg['uid']) +
                    '||String(s.timebase)!==' + json.dumps(str(cfg['tpf'])) + ')throw Error("Preview sequence did not activate");'
                    'return JSON.stringify({uid:s.sequenceID});})()')
        scripts = {
            'source-shape': (source_header(cfg)+SNAP+'return JSON.stringify(snap(0,Infinity));})()', 'source_read'),
            'preview-open': (open_script, 'open_existing_preview'),
            'preview-activate': (activate, 'activate_preview_sequence'),
            'preview-preflight': (header(cfg)+PREFLIGHT, 'preview_read'),
        }
        for purpose, (script, action) in scripts.items():
            path = output/f'{number:02}-{purpose}.jsx'
            path.write_text(script, 'utf-8')
            manifest['requests'].append({'file': str(path.resolve()), 'sha256': digest(path),
                                         'action': action, 'main_project': cfg['main_project'],
                                         'preview': cfg['preview'], 'uid': cfg['uid']})
        manifest['operation_bundles'].append({'directory': str(directory), 'plan_sha256': digest(directory/'plan.json'),
                                               'scripts_sha256': plan['scripts_sha256']})
    write(output/'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('bundles', nargs='+')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    result = prepare(args.bundles, args.out)
    print(json.dumps({'requests': len(result['requests']), 'premiere_contacted': False,
                      'output': str(Path(args.out).resolve())}, ensure_ascii=False))
