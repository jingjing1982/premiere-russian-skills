"""Measure source-audio pauses on a frame-based Premiere timeline.

Usage: python pause_probe.py input.json output.json [--cache-dir DIR]
Input shape is documented in references/pause-measurement.md.
Requires ffmpeg and ffprobe on PATH; uses only Python's standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import subprocess
from pathlib import Path

S_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
S_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=7200, check=True)


def probe(path: Path) -> dict:
    data = json.loads(run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels,duration",
        "-of", "json", str(path),
    ]).stdout)
    if not data.get("streams"):
        raise ValueError(f"No first audio stream: {path}")
    stream = data["streams"][0]
    rate, channels = int(stream["sample_rate"]), int(stream["channels"])
    if rate <= 0 or channels <= 0:
        raise ValueError(f"Invalid audio format: {path}")
    return {"sample_rate": rate, "channels": channels,
            "duration": float(stream.get("duration", 0) or 0)}


def detect(path: Path, noise_db: float, cache: Path) -> dict:
    meta = probe(path)
    stat = path.stat()
    identity = {"path": str(path.resolve()), "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "noise_db": noise_db, **meta}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    saved = cache / f"{key}.json"
    if saved.exists():
        cached = json.loads(saved.read_text(encoding="utf-8"))
        if cached.get("identity") == identity:
            return cached
    result = run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info",
        "-i", str(path), "-map", "0:a:0", "-vn",
        "-af", f"silencedetect=noise={noise_db}dB:d=0.08",
        "-f", "null", "-",
    ])
    starts, spans = [], []
    for line in result.stderr.decode("utf-8", "replace").splitlines():
        start, end = S_START.search(line), S_END.search(line)
        if start:
            starts.append(float(start.group(1)))
        if end and starts:
            a, b = starts.pop(0), float(end.group(1))
            if b > a:
                spans.append([a, b])
    if starts and meta["duration"]:
        spans.extend([[a, meta["duration"]] for a in starts if a < meta["duration"]])
    spans.sort()
    report = {"identity": identity, "silence_spans": spans}
    cache.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return report


def summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    values = sorted(values)
    def quantile(q: float) -> float:
        x = (len(values) - 1) * q
        lo = math.floor(x)
        return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (x - lo)
    return {"n": len(values), "median": round(statistics.median(values), 3),
            "p25": round(quantile(.25), 3), "p75": round(quantile(.75), 3),
            "p90": round(quantile(.90), 3)}


def overlapping_rows(rows: list[dict], a: float, b: float) -> list[tuple[dict, float, float]]:
    found = []
    for row in rows:
        x = max(a, row["start_frame"] / row["fps"])
        y = min(b, row["end_frame"] / row["fps"])
        if y > x:
            found.append((row, x, y))
    return found


def exact_zero(parts: list[tuple[dict, float, float]], formats: dict[str, dict]) -> dict:
    checked = 0
    first_nonzero = None
    for row, a, b in parts:
        path = row["path"]
        fmt = formats[path]
        source = row["source_in_seconds"] + a - row["start_frame"] / row["fps"]
        piece_checked = 0
        # Seeking after input is slower but avoids keyframe-only approximate seeks.
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                   "-i", path, "-ss", f"{source:.9f}", "-t", f"{b-a:.9f}",
                   "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            remainder = b""
            sample_frame_bytes = 4 * fmt["channels"]
            while True:
                chunk = process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                chunk = remainder + chunk
                whole = (len(chunk) // sample_frame_bytes) * sample_frame_bytes
                remainder = chunk[whole:]
                chunk = chunk[:whole]
                piece_checked += whole // sample_frame_bytes
                if first_nonzero is None and any(chunk):
                    first_nonzero = {"path": path, "timeline_seconds": round(a, 6)}
            if remainder:
                raise ValueError(f"Partial PCM sample frame: {path}")
            error = process.stderr.read()
            if process.wait(timeout=60):
                raise RuntimeError(error.decode("utf-8", "replace")[-300:])
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            process.stderr.close()
        expected = (b - a) * fmt["sample_rate"]
        if abs(piece_checked - expected) > max(2, .04 * fmt["sample_rate"]):
            raise ValueError(f"Decoded duration differs for {path}")
        checked += piece_checked
    return {"all_channels_exact_zero": first_nonzero is None,
            "checked_sample_frames": checked, "first_nonzero": first_nonzero}


def analyze(source: dict, cache: Path) -> dict:
    fps = float(source["fps"])
    if fps <= 0:
        raise ValueError("fps must be positive")
    noise_db = float(source.get("analysis_threshold_dbfs", -35))
    rows = []
    for raw in source["audio_rows"]:
        row = dict(raw, fps=fps)
        row["path"] = str(Path(row["path"]).resolve(strict=True))
        if row["end_frame"] <= row["start_frame"] or row.get("speed", 1) != 1:
            raise ValueError("Only forward, 1x audio rows are supported")
        rows.append(row)
    rows.sort(key=lambda r: r["start_frame"])
    if any(a["end_frame"] > b["start_frame"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Overlapping audio rows require a rendered final mix")
    media = {r["path"]: detect(Path(r["path"]), noise_db, cache) for r in rows}
    formats = {path: value["identity"] for path, value in media.items()}
    cues = sorted(source["cues"], key=lambda c: c["start_frame"])
    samples = []
    for before, after in zip(cues, cues[1:]):
        a, b = before["end_frame"] / fps, after["start_frame"] / fps
        if not (0 <= b - a <= 1):
            continue
        if before.get("speaker") and after.get("speaker") and before["speaker"] != after["speaker"]:
            continue
        middle = (a + b) / 2
        covering = [r for r in rows if r["start_frame"] / fps <= middle - 1.0
                    and r["end_frame"] / fps >= middle + 1.0]
        if len(covering) != 1:
            continue
        row = covering[0]
        source_time = row["source_in_seconds"] + middle - row["start_frame"] / fps
        spans = media[row["path"]]["silence_spans"]
        matches = [(max(lo - source_time, source_time - hi, 0), -(hi - lo), lo, hi)
                   for lo, hi in spans if .1 <= hi - lo <= 2.0
                   and max(lo - source_time, source_time - hi, 0) <= .25]
        if not matches:
            continue
        distance, neg_dur, lo, hi = min(matches)
        samples.append({"boundary_frame": round(middle * fps),
                        "speaker": before.get("speaker") or "__unknown__",
                        "kind": "sentence_end" if before.get("sentence_end") else "other",
                        "caption_gap_seconds": round(b - a, 3),
                        "low_energy_seconds": round(hi - lo, 3),
                        "distance_to_boundary_seconds": round(distance, 3)})
    groups = {}
    for item in samples:
        key = (item["speaker"], item["kind"])
        groups.setdefault(key, []).append(item["low_energy_seconds"])
    grouped = {f"{speaker}|{kind}": summary(vals) for (speaker, kind), vals in groups.items()}
    candidates = []
    for item in source.get("candidates", []):
        a, b = item["start_frame"] / fps, item["end_frame"] / fps
        pieces = overlapping_rows(rows, a, b)
        if not pieces or abs(sum(y - x for _, x, y in pieces) - (b - a)) > 1 / fps:
            candidates.append({**item, "error": "Audio coverage incomplete"})
            continue
        spans = []
        for row, x, y in pieces:
            offset = row["source_in_seconds"] - row["start_frame"] / fps
            for lo, hi in media[row["path"]]["silence_spans"]:
                left, right = max(x, lo - offset), min(y, hi - offset)
                if right > left:
                    spans.append([round(left, 6), round(right, 6)])
        candidates.append({**item, "low_energy_spans_timeline_seconds": sorted(spans)})
    cuts = []
    for item in source.get("cuts", []):
        a, b = item["start_frame"] / fps, item["end_frame"] / fps
        if not a < b:
            raise ValueError("Invalid cut interval")
        pieces = overlapping_rows(rows, a, b)
        if not pieces or abs(sum(y - x for _, x, y in pieces) - (b - a)) > 1 / fps:
            cuts.append({**item, "error": "Audio coverage incomplete"})
            continue
        cuts.append({**item, **exact_zero(pieces, formats)})
    return {"fps": fps, "analysis_threshold_dbfs": noise_db,
            "media": {p: v["identity"] for p, v in media.items()},
            "normal_pause_samples": samples, "reference_by_speaker_and_kind": grouped,
            "sentence_end_all_speakers": summary([x["low_energy_seconds"] for x in samples
                                                  if x["kind"] == "sentence_end"]),
            "candidates": candidates, "cuts": cuts,
            "limitations": "Threshold spans are only candidate references. Exact-zero verification proves no digital audio samples were removed, not that playback pacing sounds natural."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    cache = args.cache_dir or args.output.parent / "pause-cache"
    result = analyze(source, cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"samples": len(result["normal_pause_samples"]),
                      "candidates": len(result["candidates"]), "cuts": len(result["cuts"]),
                      "sentence_end": result["sentence_end_all_speakers"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
