"""Validate recorded cue attribution, not infer or certify voices from text."""
import hashlib
import json


def cue_fingerprint(cues):
    fields = [{k: c[k] for k in ('id', 'start_ms', 'end_ms', 'ru', 'zh')} for c in cues]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def validate_speakers(plan):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    cues = plan['cues']; ids = [c['id'] for c in cues]
    review = plan.get('speaker_review', {})
    require(review.get('cue_sha256') == cue_fingerprint(cues), 'Missing/stale speaker review for these source cues')
    ledger = review.get('attribution', [])
    require([a.get('cue_id') for a in ledger] == ids, 'Speaker attribution must cover all cues once in order')
    evidence = review.get('evidence', [])
    emap = {e['id']: e for e in evidence}
    require(len(emap) == len(evidence), 'Duplicate speaker evidence IDs')
    def check_evidence(ref):
        e = emap.get(ref, {})
        require(e.get('kind') in ('audio_review', 'visual_dialogue_review', 'user_confirmation')
                and bool(str(e.get('reference', '')).strip()) and bool(str(e.get('observation', '')).strip()),
                'Speaker evidence needs actual audio/visual-dialogue review or user confirmation and a locatable reference')
    for a in ledger:
        require(a.get('status') == 'confirmed' and a.get('turn_id'),
                f"Unresolved/mixed speaker content: cue {a.get('cue_id')}; keep source, do not merge")
        check_evidence(a.get('evidence_id'))
    turns = [a['turn_id'] for a in ledger]
    # A turn cannot disappear and resume: that would hide a speaker handoff.
    runs = [t for i, t in enumerate(turns) if i == 0 or t != turns[i-1]]
    require(len(set(runs)) == len(runs), 'Each speaking turn must be contiguous')
    boundaries = review.get('boundaries', [])
    expected = [(ids[i-1], ids[i]) for i in range(1, len(ids)) if turns[i] != turns[i-1]]
    require([(b.get('before_cue'), b.get('after_cue')) for b in boundaries] == expected,
            'Every speaker handoff needs a boundary review')
    for b in boundaries:
        check_evidence(b.get('evidence_id'))
        require(b.get('translation_status') == 'separable',
                'Translation crosses speaker handoff or is unresolved; report without rewriting')
    attribution = {a['cue_id']: a['turn_id'] for a in ledger}
    if 'turns' in plan:
        for turn in plan['turns']:
            require(all(attribution.get(i) == turn['id'] for i in turn['cue_ids']),
                    'Turn plan disagrees with reviewed cue attribution')
    return attribution


def check_group(cue_ids, attribution):
    if len({attribution[i] for i in cue_ids}) != 1:
        raise ValueError('Group crosses reviewed speaker handoff; sentence completeness/90s/fewer cuts cannot override it')
