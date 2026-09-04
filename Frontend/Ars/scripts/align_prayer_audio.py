"""
Transcribe a spoken prayer video with faster-whisper and align segment
timestamps to the canonical prayer lines in loops.json.

Usage:
  python align_prayer_audio.py
  python align_prayer_audio.py --model small --loop-index 0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
LOOPS_JSON = ROOT / "assets" / "docs" / "loops.json"
DEFAULT_VIDEO = ROOT / "assets" / "videos" / "Video01Sound.mp4"
RAW_OUT = ROOT / "assets" / "docs" / "Child01_whisper_raw.json"


def normalize(text: str) -> str:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"[^a-z0-9'\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_prayer_lines(text: str) -> list[str]:
    """Match app.js: newlines + period boundaries (before width wrap)."""
    lines: list[str] = []
    for block in str(text or "").replace("\r\n", "\n").split("\n"):
        block = block.strip()
        if not block:
            continue
        buf = ""
        for ch in block:
            buf += ch
            if ch == ".":
                trimmed = buf.strip()
                if trimmed:
                    lines.append(trimmed)
                buf = ""
        tail = buf.strip()
        if tail:
            lines.append(tail)
    return lines


def words_from_segments(segments) -> list[dict]:
    words: list[dict] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                token = (w.word or "").strip()
                if not token:
                    continue
                words.append(
                    {
                        "word": token,
                        "start": float(w.start),
                        "end": float(w.end),
                    }
                )
        else:
            token = (seg.text or "").strip()
            if token:
                words.append(
                    {
                        "word": token,
                        "start": float(seg.start),
                        "end": float(seg.end),
                    }
                )
    return words


def align_lines(lines: list[str], words: list[dict]) -> list[dict]:
    """Greedy left-to-right word matching of each prayer line against Whisper words."""
    norm_words = [normalize(w["word"]) for w in words]
    # Flatten whisper into individual tokens (whisper words can include punctuation)
    flat: list[tuple[str, float, float]] = []
    for w, nw in zip(words, norm_words):
        for token in nw.split():
            if token:
                flat.append((token, w["start"], w["end"]))

    cursor = 0
    cues: list[dict] = []
    n = len(flat)

    for line in lines:
        target = normalize(line).split()
        if not target:
            continue

        # Find start: first target token at/after cursor (fuzzy: prefix match)
        start_idx = None
        search_limit = min(n, cursor + 40)
        for i in range(cursor, search_limit):
            if flat[i][0] == target[0] or flat[i][0].startswith(target[0][:4]):
                # Verify a short window matches
                ok = True
                for j, tok in enumerate(target[: min(3, len(target))]):
                    if i + j >= n:
                        ok = False
                        break
                    fw = flat[i + j][0]
                    if not (fw == tok or fw.startswith(tok[:3]) or tok.startswith(fw[:3])):
                        ok = False
                        break
                if ok:
                    start_idx = i
                    break

        if start_idx is None:
            # Fallback: keep advancing with estimated gap
            start_t = cues[-1]["end"] if cues else 0.0
            cues.append(
                {
                    "text": line,
                    "start": round(start_t, 3),
                    "end": round(start_t + max(1.5, 0.35 * len(target)), 3),
                    "matched": False,
                }
            )
            continue

        # Consume target tokens from start_idx
        i = start_idx
        t = 0
        end_t = flat[start_idx][2]
        while t < len(target) and i < n:
            fw = flat[i][0]
            tok = target[t]
            if fw == tok or fw.startswith(tok[:3]) or tok.startswith(fw[:3]):
                end_t = flat[i][2]
                t += 1
                i += 1
            else:
                # Skip filler whisper word or skip target typo
                # Prefer skipping whisper noise first if next whisper matches current target
                if i + 1 < n and (
                    flat[i + 1][0] == tok
                    or flat[i + 1][0].startswith(tok[:3])
                ):
                    i += 1
                else:
                    t += 1

        start_t = flat[start_idx][1]
        cues.append(
            {
                "text": line,
                "start": round(start_t, 3),
                "end": round(end_t, 3),
                "matched": True,
            }
        )
        cursor = max(i, start_idx + 1)

    # Ensure monotonic non-overlapping starts
    for i in range(1, len(cues)):
        if cues[i]["start"] < cues[i - 1]["start"]:
            cues[i]["start"] = cues[i - 1]["start"]
        if cues[i - 1]["end"] > cues[i]["start"]:
            cues[i - 1]["end"] = cues[i]["start"]

    return cues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--loops", type=Path, default=LOOPS_JSON)
    parser.add_argument("--loop-index", type=int, default=0)
    parser.add_argument("--model", default="small")
    parser.add_argument("--write-loops", action="store_true", default=True)
    parser.add_argument("--no-write-loops", action="store_false", dest="write_loops")
    args = parser.parse_args()

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1
    if not args.loops.is_file():
        print(f"loops.json not found: {args.loops}", file=sys.stderr)
        return 1

    payload = json.loads(args.loops.read_text(encoding="utf-8"))
    loops = payload.get("loops") or []
    if args.loop_index < 0 or args.loop_index >= len(loops):
        print(f"Invalid loop index {args.loop_index}", file=sys.stderr)
        return 1

    loop = loops[args.loop_index]
    lines = split_prayer_lines(loop.get("prayer") or "")
    print(f"Prayer lines: {len(lines)}")
    model_path = args.model
    local_small = (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--Systran--faster-whisper-small"
        / "snapshots"
        / "536b0662742c02347bc0e980a01041f333bce120"
    )
    if args.model == "small" and (local_small / "model.bin").is_file():
        model_path = str(local_small)
        print(f"Using local model: {model_path}")
    else:
        print(f"Loading Whisper model '{args.model}'...")

    model = WhisperModel(model_path, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(args.video),
        language="en",
        word_timestamps=True,
        vad_filter=True,
    )
    segments = list(segments_iter)
    print(f"Detected duration ~{info.duration:.1f}s, language={info.language}")

    words = words_from_segments(segments)
    raw = {
        "duration": info.duration,
        "language": info.language,
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in (s.words or [])
                ],
            }
            for s in segments
        ],
        "prayerLines": lines,
    }
    RAW_OUT.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"Wrote raw transcript: {RAW_OUT}")

    cues = align_lines(lines, words)
    matched = sum(1 for c in cues if c.get("matched"))
    print(f"Aligned {matched}/{len(cues)} lines")

    for c in cues:
        flag = "ok" if c.get("matched") else "FALLBACK"
        print(f"  [{c['start']:7.2f} -> {c['end']:7.2f}] ({flag}) {c['text'][:70]}")

    # Strip helper field before saving into loops
    audio_cues = [{"text": c["text"], "start": c["start"], "end": c["end"]} for c in cues]

    if args.write_loops:
        loop["video"] = args.video.name
        loop["audioSync"] = True
        loop["audioCues"] = audio_cues
        # Optional: if transcript clearly fixes typos, leave prayer as source of truth
        # unless user later asks to rewrite prayer text from Whisper.
        args.loops.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {args.loops} with {len(audio_cues)} audioCues")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
