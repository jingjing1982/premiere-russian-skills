"""Read captions from a specified saved Premiere sequence. Never edits the project."""
from __future__ import annotations
import argparse
import base64
import gzip
import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from subtitle_core import stamp

TPS = 254016000000


def extract(project: Path, sequence_uid: str, caption_track_uid: str | None = None) -> dict:
    original = project.read_bytes()
    xml = gzip.decompress(original) if original.startswith(b'\x1f\x8b') else original
    root = ET.fromstring(xml)
    ids = {n.get('ObjectID'): n for n in root if n.get('ObjectID')}
    uids = {n.get('ObjectUID'): n for n in root if n.get('ObjectUID')}
    sequence = uids.get(sequence_uid)
    if sequence is None or sequence.tag != 'Sequence':
        raise ValueError('Specified sequence UID is absent or is not a sequence')
    groups_node = sequence.find('TrackGroups')
    if groups_node is None:
        raise ValueError('Unsupported sequence track-group layout')
    groups = [ids[n.find('Second').get('ObjectRef')] for n in groups_node]
    frame_ticks = {int(g.findtext('./TrackGroup/FrameRate')) for g in groups if g.tag == 'VideoTrackGroup'}
    if len(frame_ticks) != 1 or next(iter(frame_ticks)) <= 0:
        raise ValueError('Missing or ambiguous video frame timebase')
    tpf = next(iter(frame_ticks))
    fps = Fraction(TPS, tpf)
    blobs = {}
    for node in root.iter('FormattedTextData'):
        if node.get('BinaryHash') and node.text and node.text.strip():
            blobs[node.get('BinaryHash')] = base64.b64decode(node.text.strip(), validate=True)

    def caption(item):
        texts = []
        for ref in item.findall('./BlockVector/BlockVectorItem'):
            node = ids[ref.get('ObjectRef')].find('FormattedTextData')
            if node is None:
                raise ValueError('Unsupported caption text layout')
            blob = base64.b64decode(node.text.strip(), validate=True) if node.text and node.text.strip() else blobs[node.get('BinaryHash')]
            candidates = []
            for pos in range(len(blob) - 4):
                length = struct.unpack_from('<I', blob, pos)[0]
                end = pos + 4 + length
                if not (0 < length < 20000 and end < len(blob) and blob[end] == 0):
                    continue
                try:
                    value = blob[pos + 4:end].decode('utf8')
                except UnicodeDecodeError:
                    continue
                if '\x00' not in value and re.search('[\u3400-\u9fff\u0400-\u04ff]', value):
                    candidates.append(value)
            if len(candidates) != 1:
                raise ValueError('Caption text decoding is ambiguous or unsupported; obtain current exported SRT')
            texts.append(candidates[0])
        if not texts:
            raise ValueError('Caption block has no supported text')
        return '\n'.join(texts)

    tracks, caption_tracks = [], []
    for group in groups:
        for ref in group.findall('./TrackGroup/Tracks/Track'):
            uid = ref.get('ObjectURef')
            track = uids[uid]
            spans, items = [], []
            for item_ref in track.findall('.//TrackItems/TrackItem'):
                item = ids[item_ref.get('ObjectRef')]
                span = item.find('.//TrackItem')
                if span is None or span.findtext('End') is None:
                    raise ValueError('Unsupported timeline item layout')
                start, end = int(span.findtext('Start', '0')), int(span.findtext('End'))
                spans.append((start, end))
                if track.tag == 'CaptionDataClipTrack':
                    text = caption(item)
                    items.append({'start_ticks': start, 'end_ticks': end,
                                  'start_ms': round(Fraction(start * 1000, TPS)),
                                  'end_ms': round(Fraction(end * 1000, TPS)),
                                  'text': text, 'source_object_id': item.get('ObjectID')})
            tracks.append({'uid': uid, 'tag': track.tag, 'item_count': len(spans),
                           'maximum_end_ticks': max((b for a, b in spans), default=0)})
            if track.tag == 'CaptionDataClipTrack' and items:
                caption_tracks.append((uid, items))
    if caption_track_uid:
        selected = [items for uid, items in caption_tracks if uid == caption_track_uid]
    else:
        selected = [items for uid, items in caption_tracks]
    if len(selected) != 1:
        raise ValueError('No unique caption track; select --caption-track-uid explicitly')
    cues = sorted(selected[0], key=lambda c: (c['start_ticks'], c['end_ticks']))
    for n, cue in enumerate(cues, 1):
        if cue['end_ticks'] <= cue['start_ticks'] or cue['start_ticks'] < 0:
            raise ValueError('Invalid source cue time')
        cue['id'] = n
        cue['lines'] = cue['text'].replace('\r\n', '\n').replace('\r', '\n').split('\n')
    markers = []
    marker_ref = sequence.find('./MarkerOwner/Markers')
    if marker_ref is not None:
        container = ids[marker_ref.get('ObjectRef')]
        for ref in container.findall('./Markers/Marker'):
            marker = ids[ref.find('Second').get('ObjectRef')]
            markers.append(json.loads(marker.findtext('DVAMarker'))['DVAMarker'])
        markers.sort(key=lambda m: int(m['mStartTime']['ticks']))
    return {'project_path': str(project.resolve()), 'sequence_uid': sequence_uid,
            'sequence_name': sequence.findtext('Name'), 'source_sha256': hashlib.sha256(original).hexdigest(),
            'source_kind': 'Saved Premiere project only; live unsaved captions not read',
            'live_unsaved_state_verified': False, 'ticks_per_second': TPS, 'ticks_per_frame': tpf,
            'fps': str(fps), 'caption_tracks': [uid for uid, items in caption_tracks],
            'selected_caption_track': next(uid for uid, items in caption_tracks if items is selected[0]),
            'tracks': tracks, 'maximum_track_end_ms': round(Fraction(max(t['maximum_end_ticks'] for t in tracks) * 1000, TPS)),
            'cues': cues, 'markers': markers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--sequence-uid', required=True)
    parser.add_argument('--caption-track-uid')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--srt', required=True, type=Path)
    args = parser.parse_args()
    targets = [args.project.resolve(), args.output.resolve(), args.srt.resolve()]
    if len(set(targets)) != 3:
        raise ValueError('Outputs must not overwrite the input or each other')
    if args.output.exists() or args.srt.exists():
        raise ValueError('Outputs must be new files')
    result = extract(args.project, args.sequence_uid, args.caption_track_uid)
    body = '\r\n\r\n'.join(f"{c['id']}\r\n{stamp(c['start_ms'])} --> {stamp(c['end_ms'])}\r\n" +
                              '\r\n'.join(c['lines']) for c in result['cues']) + '\r\n'
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf8')
    args.srt.write_bytes(b'\xef\xbb\xbf' + body.encode('utf8'))
    print(json.dumps({'source_kind': result['source_kind'], 'caption_count': len(result['cues']),
                      'sequence_uid': result['sequence_uid'], 'fps': result['fps']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
