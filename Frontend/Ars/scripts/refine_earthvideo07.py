"""Refine EarthVideo07 cues from existing Whisper raw into shorter timed lines."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import bake_word_timings as bake  # noqa: E402
import fix_word_timings as fix  # noqa: E402
import recase_from_docx as recase  # noqa: E402

KEY = "EarthVideo07"
VIDEO_NAME = "Video07Sound.mp4"
RAW_PATH = ROOT / "assets" / "docs" / "whisper_raw" / "EarthVideo07_whisper_raw.json"
LOOPS_JSON = ROOT / "assets" / "docs" / "loops.json"

EXTRA_FIXES = [
    (re.compile(r"\blook\s+deaf\b", re.I), "look death"),
]


def apply_extra_fixes(text: str) -> str:
    out = text
    for pat, repl in EXTRA_FIXES:
        out = pat.sub(repl, out)
    return out


def flatten_raw_words(raw: dict) -> list[dict]:
    words: list[dict] = []
    for seg in raw.get("segments") or []:
        for w in seg.get("words") or []:
            token = str(w.get("word") or "").strip()
            if not token:
                continue
            words.append(
                {
                    "word": token,
                    "start": float(w["start"]),
                    "end": float(w.get("end", w["start"])),
                }
            )
    return words


def join_words(chunk: list[dict]) -> str:
    parts: list[str] = []
    for w in chunk:
        token = w["word"].strip()
        if not token:
            continue
        if parts and token[:1] in ",.;:!?)]}'\"":
            parts[-1] = parts[-1] + token
        else:
            parts.append(token)
    return " ".join(parts).strip()


def split_word_stream(words: list[dict], soft_limit: int = 7) -> list[list[dict]]:
    """Split Whisper words into short reading lines at punctuation."""
    lines: list[list[dict]] = []
    buf: list[dict] = []

    def flush() -> None:
        nonlocal buf
        if buf:
            lines.append(buf)
            buf = []

    for w in words:
        buf.append(w)
        token = w["word"].strip()
        hard = bool(re.search(r"[.!?]$", token))
        soft = bool(re.search(r"[,;:—–-]$", token)) and len(buf) >= soft_limit
        if hard or soft:
            flush()
    flush()
    return lines


def main() -> int:
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    words = flatten_raw_words(raw)
    chunks = split_word_stream(words)

    sections, _ = recase.parse_docx_sections(recase.DOCX_PATH)
    payload = json.loads(LOOPS_JSON.read_text(encoding="utf-8"))
    loops = payload.get("loops") or []
    index = next(i for i, loop in enumerate(loops) if loop.get("videoKey") == KEY)
    loop = loops[index]
    essay = sections[index] if index < len(sections) else None
    original = (essay or {}).get("prayer") or loop.get("prayer") or ""
    forms, proper = recase.build_case_forms(original)
    if essay and essay.get("leadingQuestion"):
        q_forms, q_proper = recase.build_case_forms(essay["leadingQuestion"])
        for k, v in q_forms.items():
            forms.setdefault(k, []).extend(v)
        proper |= q_proper
    essay_phrases = recase.extract_essay_phrases(original)
    for forced in (
        "Mother of the Earth",
        "Black Liberated Reality",
        "Children of the Bloom",
    ):
        if forced.lower() not in {p.lower() for p in essay_phrases}:
            essay_phrases.insert(0, forced)

    flat = bake.flat_words(raw)
    cursor = 0
    cues: list[dict] = []
    prev_ended = True
    for chunk in chunks:
        raw_text = join_words(chunk)
        raw_text = apply_extra_fixes(raw_text)
        raw_text = recase.apply_hard_phrase_fixes(raw_text)
        raw_text = recase.soft_replace_essay_phrases(raw_text, essay_phrases)
        text = recase.recase_text(
            raw_text,
            forms,
            proper,
            initial_sentence_start=prev_ended,
        )
        text = apply_extra_fixes(recase.apply_hard_phrase_fixes(text))
        if text and prev_ended and text[:1].islower():
            text = text[:1].upper() + text[1:]
        # Soft-split / essay phrase merges can leave mid-line sentence capitals.
        if text and not prev_ended:
            text = re.sub(r"^(Then|And|That|The|In|With)\b", lambda m: m.group(1).lower(), text)
        text = re.sub(r"([,;:—–-]\s+)Then\b", r"\1then", text)
        if not text:
            continue
        start = round(float(chunk[0]["start"]), 2)
        end = round(float(chunk[-1]["end"]), 2)
        cue = {"text": text, "start": start, "end": end}
        if len(text) <= 34:
            cue["nowrap"] = True
        timing, wstarts, cursor = bake.align_timing(text, flat, cursor)
        if not any(isinstance(t, (int, float)) and t > 0 for t in timing):
            n = max(1, len(timing))
            timing = [
                round(start + (end - start) * (i / max(1, n - 1)), 3) for i in range(n)
            ]
        cue["wordTiming"] = timing
        cue["wordStarts"] = wstarts
        fix.fix_cue(cue)
        cues.append(cue)
        prev_ended = bool(re.search(r"[.!?]$", text))

    # Keep starts monotonic after soft splits.
    for i in range(1, len(cues)):
        if cues[i]["start"] < cues[i - 1]["start"]:
            cues[i]["start"] = cues[i - 1]["start"]
        if cues[i - 1]["end"] > cues[i]["start"]:
            cues[i - 1]["end"] = cues[i]["start"]

    loop["prayer"] = "\n".join(c["text"] for c in cues)
    loop["audioCues"] = cues
    loop["video"] = VIDEO_NAME
    loop["videoKey"] = KEY
    loop["audioSync"] = True
    if essay and essay.get("leadingQuestion"):
        loop["leadingQuestion"] = essay["leadingQuestion"]

    LOOPS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {KEY}: {len(cues)} cues")
    for i, cue in enumerate(cues):
        flag = " nowrap" if cue.get("nowrap") else ""
        print(f"  [{i:02d}] {cue['start']:5.2f}-{cue['end']:5.2f}{flag}  {cue['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
