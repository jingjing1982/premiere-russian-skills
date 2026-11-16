"""Reflow Russian lines in bilingual SRT; report timing gaps without changing times."""
import argparse
import csv
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

HAN = re.compile(r"[\u4e00-\u9fff]")
BLOCKS = re.compile(r"(\r?\n\s*\r?\n)")
TIMES = re.compile(r"^(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})$")
FUNCTION_WORDS = set('в во на к ко с со о об обо от до из из-за из-под у для без над под перед при по про через между и или либо но а что чтобы как не ни'.split())
PERSON_TITLES = set('кхенпо лама будда бодхисаттва досточтимый'.split())
FIXED_PHRASES = ('добро пожаловать', 'потому что', 'так как', 'то есть',
                 'в том числе', 'друг друга', 'друг другу', 'по крайней мере',
                 'таким образом', 'в связи с', 'несмотря на')


def clean_word(word):
    return word.strip('«»“”\"()[]{}.,:;!?…—').lower()


def boundary_quality(words, cut):
    """Small transparent language heuristics; flagged cases still need review."""
    normalized = [clean_word(word) for word in words]
    broken_phrase = False
    for phrase in FIXED_PHRASES:
        parts = phrase.split()
        for start in range(max(0, cut-len(parts)+1), min(cut, len(words)-len(parts)+1)):
            if normalized[start:start+len(parts)] == parts and start < cut < start+len(parts):
                broken_phrase = True
    # Preserve a short quoted expression or title where a wider layout can keep it whole.
    quote_start = None
    broken_quote = False
    for index, word in enumerate(words):
        if '«' in word or '“' in word:
            quote_start = index
        if quote_start is not None and ('»' in word or '”' in word):
            if index-quote_start+1 <= 7 and quote_start < cut <= index:
                broken_quote = True
            quote_start = None
    last = words[cut-1].rstrip('»”\")]}')
    if last.endswith(('.', '!', '?', '…')):
        broken_quote = False
    weak = (broken_phrase or broken_quote or normalized[cut-1] in FUNCTION_WORDS
            or normalized[cut-1] in PERSON_TITLES)
    if last.endswith(('.', '!', '?', '…')):
        rank = 0
    elif last.endswith((';', ':', '—')):
        rank = 1
    elif last.endswith(','):
        rank = 2
    else:
        rank = 3
    return int(weak), rank


def split_preserving_spaces(text, cut):
    positions = list(re.finditer(r'\S+', text))
    pos = positions[cut-1].end()
    if text[pos:pos+1] != ' ':
        raise ValueError('Expected a space at the selected word boundary')
    return [text[:pos], text[pos+1:]]


def russian_indices(lines):
    indices = []
    for i in range(2, len(lines)):
        if HAN.search(lines[i]):
            break
        indices.append(i)
    return indices


def wrap_greedy(words, width, measure=len):
    rows = [""]
    for word in words:
        candidate = (rows[-1] + " " + word).strip()
        if rows[-1] and measure(candidate) > width:
            rows.append(word)
        else:
            rows[-1] = candidate
    return rows


def best_two_lines(text, width, min_tail_words, measure=len):
    """Measure exact substrings. A list is legacy compatibility, not lossless input."""
    if not isinstance(text, str):
        text = ' '.join(text)
    tokens = list(re.finditer(r'\S+', text))
    words = [m.group() for m in tokens]
    min_tail_words = max(2, min_tail_words)
    word_positions = [i for i, token in enumerate(words) if any(c.isalnum() for c in token)]
    def candidate(tail):
        if tail >= len(word_positions):
            return None
        cut = word_positions[-tail]
        if cut < 1 or tail < min_tail_words:
            return None
        pos = tokens[cut-1].end()
        # Only replace one ordinary space; preserve remaining spaces verbatim.
        # NBSP, narrow NBSP and tabs are not permitted break positions.
        if text[pos:pos+1] != ' ':
            return None
        left, right = text[:pos], text[pos+1:]
        lw, rw = measure(left), measure(right)
        return (left, right) if max(lw, rw) <= width and lw > rw else None

    # Visual preference: three words below, two only when three is nearly
    # balanced (80% of the upper width), or cannot keep the upper line longer.
    # Language heuristics flag review; they never override this preference.
    preferred = max(3, min_tail_words)
    three = candidate(preferred)
    two = candidate(2)
    if three:
        if preferred == 3 and measure(three[1]) >= .80 * measure(three[0]) and two:
            return two
        return three
    if two:
        return two
    # More than three words below only when required to fit the upper line.
    for tail in range(preferred + 1, len(word_positions)):
        result = candidate(tail)
        if result:
            return result
    return None


def signature(block):
    lines = block.splitlines()
    ru = russian_indices(lines)
    return (lines[:2], [x for x in lines[2:] if HAN.search(x)],
            " ".join(lines[i] for i in ru))


def milliseconds(parts):
    hours, minutes, seconds, millis = map(int, parts)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def time_parts(block):
    lines = block.splitlines()
    if len(lines) < 2:
        return None
    match = TIMES.fullmatch(lines[1])
    return match.groups() if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=49,
                        help="Legacy estimate only; font measurement is preferred")
    parser.add_argument("--font-file", type=Path, help="Actual installed TTF/TTC/OTF; requires Pillow")
    parser.add_argument("--font-index", type=int, default=0, help="Face index in a TTC")
    parser.add_argument("--font-size", type=int, help="Required with --font-file; read the current caption size")
    parser.add_argument("--max-width", type=float, help="Calibrated caption-box width in sequence pixels")
    parser.add_argument("--tracking", type=float, default=0, help="Extra spacing per character in sequence pixels")
    parser.add_argument("--cue-widths", type=Path,
                        help="JSON: input_sha256 and cues mapping cue IDs to max_width/profile; missing cues stay unchanged")
    parser.add_argument("--min-tail-words", type=int, default=2)
    parser.add_argument("--mode", choices=("short-tail", "two-line"), default="two-line",
                        help="Compatibility option; both modes prefer one line when it fits")
    args = parser.parse_args()
    gap_path = args.report.with_name(args.report.stem + "_gaps.csv")
    layout_path = args.report.with_name(args.report.stem + "_layout.csv")
    outputs = [args.output, args.report, gap_path, layout_path]
    inputs = [args.input] + [p for p in (args.font_file, args.cue_widths) if p]
    resolved_outputs = [p.resolve() for p in outputs]
    if len(set(resolved_outputs)) != len(outputs) or set(resolved_outputs) & {p.resolve() for p in inputs}:
        parser.error("Outputs and reports must not overwrite inputs or each other")
    if any(p.exists() for p in outputs):
        parser.error("Outputs and reports must be new files; existing files are never overwritten")
    if args.max_chars < 10 or args.min_tail_words < 2:
        parser.error("Invalid width or minimum tail word count")
    if bool(args.font_file) != (args.max_width is not None):
        parser.error("Use --font-file and --max-width together")
    if args.font_file and args.font_size is None:
        parser.error("Pass the current caption --font-size explicitly; no inherited font-size default")
    if args.font_size is not None and args.font_size <= 0 or args.max_width is not None and args.max_width <= 0:
        parser.error("Invalid font size or usable width")
    if args.font_file:
        from PIL import ImageFont
        font = ImageFont.truetype(str(args.font_file), args.font_size, index=args.font_index)
        @lru_cache(maxsize=16384)
        def measure(text):
            return font.getlength(text) + max(0, len(text) - 1) * args.tracking
        width = args.max_width
        width_basis = f"{font.getname()}; size={args.font_size}; width={width}px; verify in Premiere"
    else:
        measure, width = len, args.max_chars
        width_basis = "legacy character estimate; NOT calibrated for proportional fonts"

    raw_bytes = args.input.read_bytes()
    cue_widths = None
    if args.cue_widths:
        layout = json.loads(args.cue_widths.read_text(encoding='utf-8-sig'))
        if layout.get('input_sha256') != hashlib.sha256(raw_bytes).hexdigest():
            parser.error('Width manifest does not match this exact source SRT')
        cue_widths = layout['cues']
    raw = raw_bytes.decode("utf-8-sig")
    sep = "\r\n" if "\r\n" in raw else "\n"
    parts = BLOCKS.split(raw)
    report = []
    layout_report = []
    for i in range(0, len(parts), 2):
        lines = parts[i].splitlines()
        if len(lines) < 3 or not lines[0].isdigit() or "-->" not in lines[1]:
            continue
        ru = russian_indices(lines)
        if not ru:
            continue
        full_text = " ".join(lines[j] for j in ru)
        words = full_text.split()
        settings = cue_widths.get(lines[0]) if cue_widths is not None else None
        cue_width = settings.get('max_width') if settings is not None else (width if cue_widths is None else None)
        if cue_width is None or not isinstance(cue_width, (float, int)) or cue_width <= 0:
            report.append([lines[0], lines[1], 'unknown_width_preserved', '', len(words), full_text])
            layout_report.append([lines[0], '', measure(full_text), '', '', '', 'unknown_width_preserved', 'unverified'])
            continue
        single_fits = measure(full_text) <= cue_width
        natural = [row for j in ru for row in wrap_greedy(lines[j].split(), cue_width, measure)]
        two = None if single_fits else best_two_lines(full_text, cue_width, args.min_tail_words, measure)
        short_tail = (len(natural) == 2 and
                      (len(natural[-1].split()) < args.min_tail_words or
                       len(natural[-1].split()) == 2 and measure(natural[-1]) < .40 * measure(natural[0])))
        three_lines = len(ru) > 2 or len(natural) > 2
        second_longer = len(natural) == 2 and measure(natural[1]) >= measure(natural[0])
        changed = False
        target = ([full_text] if single_fits else
                  list(two) if two else None)
        current_rows = [lines[j] for j in ru]
        if target is not None and current_rows != target:
            lines[ru[0]:ru[-1] + 1] = target
            parts[i] = sep.join(lines)
            changed = True
        if changed or target is None or three_lines or short_tail or second_longer:
            report.append([lines[0], lines[1], "changed" if changed else "visual_check",
                           len(natural), len(words), " ".join(words)])
        proposed = target if target is not None else current_rows
        tail_words = sum(any(c.isalnum() for c in w) for w in proposed[-1].split()) if len(proposed)==2 else ''
        layout_report.append([lines[0], cue_width, measure(full_text), len(proposed), tail_words,
                              settings.get('profile','') if settings else '',
                              'manual_preserved' if target is None else 'changed' if changed else 'unchanged',
                              'unverified'])

    source_blocks = [b for b in re.split(r"\r?\n\s*\r?\n", raw.strip()) if b]
    cue_positions = [i for i in range(0, len(parts), 2) if time_parts(parts[i])]
    gap_report = []
    for left_pos, right_pos in zip(cue_positions, cue_positions[1:]):
        left, right = parts[left_pos], parts[right_pos]
        left_time, right_time = time_parts(left), time_parts(right)
        gap_ms = milliseconds(right_time[:4]) - milliseconds(left_time[4:])
        if gap_ms == 0:
            continue
        action = "overlap_report_only" if gap_ms < 0 else "keep_gt_2s" if gap_ms > 2000 else "open_le_2s"
        left_lines, right_lines = left.splitlines(), right.splitlines()
        gap_report.append([left_lines[0], right_lines[0],
                           left_lines[1].split(" --> ")[1], right_lines[1].split(" --> ")[0],
                           f"{gap_ms / 1000:.3f}", action])

    output = "".join(parts)
    output_blocks = [b for b in re.split(r"\r?\n\s*\r?\n", output.strip()) if b]
    if len(source_blocks) != len(output_blocks):
        raise AssertionError("Cue count changed")
    for old, new in zip(source_blocks, output_blocks):
        old_sig, new_sig = signature(old), signature(new)
        if old_sig[0][0] != new_sig[0][0] or old_sig[1:] != new_sig[1:]:
            raise AssertionError("Cue number, Chinese text, or Russian words changed")
        old_time, new_time = time_parts(old), time_parts(new)
        if not old_time or not new_time or old_sig[0][1] != new_sig[0][1]:
            raise AssertionError("Cue timing changed; all starts and ends must remain exact")

    if args.input.read_bytes() != raw_bytes:
        raise AssertionError("Source changed during processing; refusing stale output")
    with args.output.open("xb") as handle:
        handle.write((b"\xef\xbb\xbf" if raw_bytes.startswith(b"\xef\xbb\xbf") else b"") + output.encode("utf-8"))
    with args.report.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["序号", "时间", "处理", "估计自动行数", "俄语词数", "俄语原文"])
        writer.writerows(report)
    with gap_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["前一条序号", "后一条序号", "前条结束时间", "后条开始时间", "间隙秒数", "处理"])
        writer.writerows(gap_report)
    print(f"Verified {len(source_blocks)} cues; changed {sum(x[2] == 'changed' for x in report)}; "
          f"visual checks {sum(x[2] == 'visual_check' for x in report)}; "
          f"unclosed <=2s {sum(x[-1] == 'open_le_2s' for x in gap_report)}; "
          f"allowed >2s {sum(x[-1] == 'keep_gt_2s' for x in gap_report)}; "
          f"overlaps {sum(x[-1] == 'overlap_report_only' for x in gap_report)}; timing changes 0")
    print(f"Width basis: {width_basis}")
    with layout_path.open('x', encoding='utf-8-sig', newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(['cue','usable_width','full_measured_width','proposed_lines','tail_words','profile','action','PR_visual_status'])
        writer.writerows(layout_report)


if __name__ == "__main__":
    main()
