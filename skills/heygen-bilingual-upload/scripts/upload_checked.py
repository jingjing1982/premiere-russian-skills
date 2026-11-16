"""Public CSV entrypoint: require a current handoff, then use the audited converter."""
import argparse, json
from pathlib import Path
from handoff import check, cues
from srt_to_heygen_csv import convert, verify_csv, audit_speakers

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('srt');p.add_argument('csv');p.add_argument('--template-xlsx',required=True)
    p.add_argument('--handoff',required=True);p.add_argument('--speaker-review');p.add_argument('--sheet')
    p.add_argument('--verify-only',action='store_true');p.add_argument('--report',required=True)
    a=p.parse_args();d=check(a.handoff,a.srt)
    if d['stage']!='ready-for-upload' or d['unresolved']:raise ValueError('Handoff not ready: resolve conflicts first')
    source_rows=cues(a.srt)
    if any(r['end_ms']-r['start_ms']>90000 for r in source_rows) or any(b['start_ms']<a['end_ms'] for a,b in zip(source_rows,source_rows[1:])):
        raise ValueError('Source has over-90-second cues or overlaps/reverse order; report as review-only, not final upload')
    report=Path(a.report)
    if report.exists() or report.resolve() in {Path(x).resolve() for x in [a.srt,a.csv,a.template_xlsx,a.handoff] + ([a.speaker_review] if a.speaker_review else [])}:raise ValueError('Report must be a new distinct file')
    audit=audit_speakers(a.srt,a.template_xlsx,a.sheet,speaker_review=a.speaker_review)
    if audit['blocking_cues']:raise ValueError('Unresolved speaker cues: '+str(audit['blocking_cues']))
    op=verify_csv if a.verify_only else convert
    result=op(a.srt,a.csv,a.template_xlsx,a.sheet,speaker_review=a.speaker_review)
    check(a.handoff,a.srt)
    result['handoff_id']=d['id']
    with report.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'verified':result['verified'],'speaker_empty_count':result['speaker_empty_count'],'output':str(Path(a.csv).resolve())},ensure_ascii=False))
if __name__=='__main__':main()
