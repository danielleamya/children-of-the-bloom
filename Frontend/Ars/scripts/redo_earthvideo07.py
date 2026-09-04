"""Redo Whisper + cues for EarthVideo07 / Video07Sound.mp4 only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import bake_word_timings as bake  # noqa: E402
import fix_word_timings as fix  # noqa: E402
import recase_from_docx as recase  # noqa: E402

KEY = "EarthVideo07"
VIDEO = ROOT / "assets" / "videos" / "Video07Sound.mp4"
RAW_PATH = ROOT / "assets" / "docs" / "whisper_raw" / "EarthVideo07_whisper_raw.json"
LOOPS_JSON = ROOT / "assets" / "docs" / "loops.json"
LOCAL_SMALL = (
    Path.home()
    / ".cache"
    / "huggingface"
    / "hub"
    / "models--Systran--faster-whisper-small"
    / "snapshots"
    / "536b0662742c02347bc0e980a01041f333bce120"
)


def transcribe() -> dict:
    if not VIDEO.is_file():
        raise SystemExit(f"Missing video: {VIDEO}")
    model_path = str(LOCAL_SMALL) if (LOCAL_SMALL / "model.bin").is_file() else "small"
    print(f"Loading model: {model_path}")
    model = WhisperModel(model_path, device="cpu", compute_type="int8")
    print(f"Transcribing {VIDEO.name} ...")
    segments_iter, info = model.transcribe(
        str(VIDEO),
        language="en",
        word_timestamps=True,
        vad_filter=True,
    )
    raw_segs = []
    for seg in segments_iter:
        raw_segs.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text,
                "words": [
                    {
                        "word": w.word,
                        "start": float(w.start),
                        "end": float(w.end),
                    }
                    for w in (seg.words or [])
                ],
            }
        )
    payload = {
        "video": VIDEO.name,
        "duration": float(info.duration),
        "language": info.language,
        "segments": raw_segs,
    }
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {RAW_PATH} ({len(raw_segs)} segments, {info.duration:.1f}s)")
    return payload


def update_loop_from_whisper(raw: dict) -> None:
    if not recase.DOCX_PATH.is_file():
        raise SystemExit(f"Missing essay docx: {recase.DOCX_PATH}")

    sections, _closing = recase.parse_docx_sections(recase.DOCX_PATH)
    payload = json.loads(LOOPS_JSON.read_text(encoding="utf-8"))
    loops = payload.get("loops") or []
    index = next(
        (i for i, loop in enumerate(loops) if loop.get("videoKey") == KEY),
        None,
    )
    if index is None:
        raise SystemExit(f"No loop with videoKey={KEY}")

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
        "Casilda Benners",
        "Black Liberated Reality",
        "Children of the Bloom",
        "Mother of the Sun",
        "Mother of the Earth",
        "St. Croix",
        "St. Thomas",
        "Puerto Rico",
        "Great Depression",
    ):
        if forced.lower() not in {p.lower() for p in essay_phrases}:
            essay_phrases.insert(0, forced)

    prayer, cues = recase.cues_from_recased_segments(
        raw.get("segments") or [],
        forms,
        proper,
        key=KEY,
        essay_phrases=essay_phrases,
    )

    # Bake word timings into the new cues.
    flat = bake.flat_words(raw)
    cursor = 0
    for cue in cues:
        text = cue.get("text") or ""
        timing, wstarts, cursor = bake.align_timing(text, flat, cursor)
        start = float(cue.get("start") or 0)
        end = float(cue.get("end") or start + 2)
        if not any(isinstance(t, (int, float)) and t > 0 for t in timing):
            n = max(1, len(timing))
            timing = [round(start + (end - start) * (i / max(1, n - 1)), 3) for i in range(n)]
        cue["wordTiming"] = timing
        cue["wordStarts"] = wstarts
        fix.fix_cue(cue)

    loop["prayer"] = prayer
    loop["audioCues"] = cues
    loop["video"] = VIDEO.name
    loop["videoKey"] = KEY
    loop["audioSync"] = True

    LOOPS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {KEY}: {len(cues)} cues")
    for i, cue in enumerate(cues[:8]):
        print(f"  [{i}] {cue['start']:.2f}-{cue['end']:.2f}  {cue['text']}")
    if len(cues) > 8:
        print(f"  ... +{len(cues) - 8} more")


def main() -> int:
    raw = transcribe()
    update_loop_from_whisper(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
