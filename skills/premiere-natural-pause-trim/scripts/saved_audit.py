"""Read-only audit of saved Premiere projects. No Premiere connection or writes."""
import collections
import gzip
import xml.etree.ElementTree as ET
from pathlib import Path


def load(path):
    root = ET.fromstring(gzip.decompress(Path(path).read_bytes()))
    ids = {x.get('ObjectID'): x for x in root if x.get('ObjectID')}
    uids = {x.get('ObjectUID'): x for x in root if x.get('ObjectUID')}
    ids.update(uids)
    return root, ids, uids


def records(ix, ux, uid, tpf):
    result = []
    for ref in ux[uid].findall('./TrackGroups/TrackGroup/Second'):
        group = ix[ref.get('ObjectRef')]
        if group.tag not in ('VideoTrackGroup', 'AudioTrackGroup'):
            continue
        kind = int(group.tag == 'AudioTrackGroup')
        for tr in group.findall('./TrackGroup/Tracks/Track'):
            for cr in ux[tr.get('ObjectURef')].findall('./ClipTrack/ClipItems/TrackItems/TrackItem'):
                obj = ix[cr.get('ObjectRef')]
                if obj.tag not in ('VideoClipTrackItem', 'AudioClipTrackItem'):
                    raise ValueError('Unsupported AV track item: ' + obj.tag)
                sub = ix[obj.find('./ClipTrackItem/SubClip').get('ObjectRef')]
                clip = ix[sub.find('Clip').get('ObjectRef')].find('Clip')
                source = ix[clip.find('Source').get('ObjectRef')]
                media = ux[source.find('./MediaSource/Media').get('ObjectURef')]
                ticks = [int(obj.findtext('.//TrackItem/' + k, '0')) for k in ('Start', 'End')]
                ticks += [int(clip.findtext(k, '0')) for k in ('InPoint', 'OutPoint')]
                if any(x % tpf for x in ticks):
                    raise ValueError('Subframe AV timing needs a separate mapping')
                row = [kind, int(tr.get('Index')), *[x // tpf for x in ticks], media.findtext('ActualMediaFilePath')]
                result.append((row, obj))
    return sorted(result, key=lambda x: x[0])


def graph(ix, obj, seen=()):
    if obj is None:
        return None
    key = obj.get('ObjectID') or obj.get('ObjectUID')
    if key and key in seen:
        return ('cycle', obj.tag)
    path = seen + (key,) if key else seen
    attrs = tuple(sorted((k, v) for k, v in obj.attrib.items()
                         if k not in ('ObjectID', 'ObjectUID', 'ObjectRef', 'ObjectURef')))
    children = [graph(ix, ch, path) for ch in obj]
    if obj.get('ObjectRef'):
        children.append(graph(ix, ix[obj.get('ObjectRef')], path))
    if obj.get('ObjectURef'):
        children.append(graph(ix, ix[obj.get('ObjectURef')], path))
    return obj.tag, attrs, (obj.text or '').strip(), tuple(children)


def link_pairs(ix, ux, uid, recs):
    by_id = {obj.get('ObjectID'): row for row, obj in recs}
    result, used = [], []
    for lr in ux[uid].findall('./PersistentGroupContainer/LinkContainer/Links/Link'):
        ids = [x.get('ObjectRef') for x in ix[lr.get('ObjectRef')].findall('.//TrackItem')]
        if len(ids) != 2 or any(i not in by_id for i in ids):
            raise ValueError('Only simple one-video/one-audio links are supported')
        pair = sorted([by_id[i] for i in ids])
        if [r[0] for r in pair] != [0, 1] or pair[0][2:] != pair[1][2:]:
            raise ValueError('Link does not match exact AV time/source')
        used.extend(ids)
        result.append(pair)
    if len(used) != len(set(used)) or set(used) != set(by_id):
        raise ValueError('Missing or duplicate AV links')
    return result


def audit(before_path, after_path, uid, tpf, expected):
    br, bi, bu = load(before_path)
    ar, ai, au = load(after_path)
    before, after = records(bi, bu, uid, tpf), records(ai, au, uid, tpf)
    if [r for r, _ in after] != sorted(expected):
        raise ValueError('Saved AV state differs from the planned state')
    link_pairs(bi, bu, uid, before)
    links = link_pairs(ai, au, uid, after)
    for original, original_obj in before:
        subs = sorted([(r, o) for r, o in after if r[0] == original[0]
                       and original[2] <= r[2] < r[3] <= original[3]], key=lambda x: x[0][2])
        if not subs or subs[0][0][2] != original[2] or subs[-1][0][3] != original[3]:
            raise ValueError('Missing source coverage')
        if any(x[0][3] != y[0][2] for x, y in zip(subs, subs[1:])):
            raise ValueError('Duplicate or missing coverage')
        for r, obj in subs:
            if (r[6] != original[6] or r[4] - original[4] != r[2] - original[2]
                    or r[5] - original[4] != r[3] - original[2]
                    or (r[0] == 1 and r[1] != original[1])):
                raise ValueError('Source mapping or audio track changed')
            component_path = './ClipTrackItem/ComponentOwner/Components'
            if graph(ai, obj.find(component_path)) != graph(bi, original_obj.find(component_path)):
                raise ValueError('Effect/keyframe graph changed')
    # Compare all non-AV track graphs, including caption timings and style references.
    def non_av(ix, ux, seq):
        return [graph(ix, ix[r.get('ObjectRef')]) for r in seq.findall('./TrackGroups/TrackGroup/Second')
                if ix[r.get('ObjectRef')].tag not in ('VideoTrackGroup', 'AudioTrackGroup')]
    if non_av(bi, bu, bu[uid]) != non_av(ai, au, au[uid]):
        raise ValueError('Caption/non-AV track graph changed')
    def formatted(root):
        return collections.Counter((x.text or '').strip() for x in root.iter('FormattedTextData'))
    if formatted(br) != formatted(ar):
        raise ValueError('Formatted text changed')
    def markers(ix, seq):
        return [graph(ix, x) for x in seq if 'marker' in x.tag.lower()]
    if markers(bi, bu[uid]) != markers(ai, au[uid]):
        raise ValueError('Markers changed')
    others = 0
    for other_uid, seq in bu.items():
        if seq.tag == 'Sequence' and other_uid != uid:
            if [r for r, _ in records(bi, bu, other_uid, 1)] != [r for r, _ in records(ai, au, other_uid, 1)]:
                raise ValueError('Other sequence AV changed')
            if non_av(bi, bu, seq) != non_av(ai, au, au[other_uid]):
                raise ValueError('Other sequence captions changed')
            others += 1
    return {'av_link_pairs': len(links), 'video_clips': sum(r[0] == 0 for r, _ in after),
            'audio_clips': sum(r[0] == 1 for r, _ in after), 'other_sequences_checked': others,
            'coverage_audio_positions_effects_captions_markers_verified': True,
            'sound_classification_verified_by_this_tool': False}
