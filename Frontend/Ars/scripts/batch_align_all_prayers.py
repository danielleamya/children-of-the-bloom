"""
Batch-transcribe all WithSound loop videos, update loops.json prayers/cues,
and sync the Excel template video column.

Usage (from Frontend/Ars):
  python scripts/batch_align_all_prayers.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
LOOPS_JSON = ROOT / "assets" / "docs" / "loops.json"
XLSX = ROOT / "assets" / "docs" / "conversational_template.xlsx"
VIDEOS = ROOT / "assets" / "videos"
RAW_DIR = ROOT / "assets" / "docs" / "whisper_raw"

LOCAL_SMALL = (
    Path.home()
    / ".cache"
    / "huggingface"
    / "hub"
    / "models--Systran--faster-whisper-small"
    / "snapshots"
    / "536b0662742c02347bc0e980a01041f333bce120"
)

# Prefer explicit WithSound filenames keyed by loops.json videoKey.
VIDEO_BY_KEY = {
    "Child01": "Video01Sound.mp4",
    "Child02": "Video02Sound.mp4",
    "Nana03": "Video03Sound.mp4",
    "Phytoplankton": "Video04Sound.mp4",
    "ChildMe05": "Video05Sound.mp4",
    "MassiveAlgal06": "Video06Sound.mp4",
    "EarthVideo07": "Video07Sound.mp4",
    "CosmicMother08": "Video08Sound.mp4",
}


def clean_segment_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""
    # Keep Whisper wording; lightly normalize casing of first char.
    return text[0].upper() + text[1:] if len(text) > 1 else text.upper()


def cues_from_segments(segments) -> tuple[str, list[dict], list[dict]]:
    lines: list[str] = []
    cues: list[dict] = []
    raw_segs: list[dict] = []
    for seg in segments:
        text = clean_segment_text(seg.text)
        words = [
            {"word": w.word, "start": float(w.start), "end": float(w.end)}
            for w in (seg.words or [])
        ]
        raw_segs.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text,
                "words": words,
            }
        )
        if not text:
            continue
        lines.append(text)
        cue = {
            "text": text,
            "start": round(float(seg.start), 2),
            "end": round(float(seg.end), 2),
        }
        # Keep only very short closing lines from wrapping awkwardly.
        if len(text) <= 28:
            cue["nowrap"] = True
        cues.append(cue)
    prayer = "\n".join(lines)
    return prayer, cues, raw_segs


def main() -> int:
    if not LOOPS_JSON.is_file():
        print(f"Missing {LOOPS_JSON}", file=sys.stderr)
        return 1

    payload = json.loads(LOOPS_JSON.read_text(encoding="utf-8"))
    loops = payload.get("loops") or []
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    model_path = str(LOCAL_SMALL) if (LOCAL_SMALL / "model.bin").is_file() else "small"
    print(f"Loading model: {model_path}")
    model = WhisperModel(model_path, device="cpu", compute_type="int8")

    for index, loop in enumerate(loops):
        key = loop.get("videoKey") or f"loop{index}"
        # Keep carefully tuned Child01 cues unless --force later.
        if key == "Child01" and loop.get("audioCues") and loop.get("audioSync"):
            loop["video"] = VIDEO_BY_KEY.get(key, loop.get("video"))
            loop["audioSync"] = True
            print(f"[{index}] {key}: keep existing cues ({len(loop['audioCues'])})")
            continue

        filename = VIDEO_BY_KEY.get(key)
        if not filename:
            print(f"[{index}] {key}: no WithSound mapping, skip")
            continue
        video_path = VIDEOS / filename
        if not video_path.is_file():
            print(f"[{index}] {key}: missing {filename}, skip")
            continue

        print(f"[{index}] {key}: transcribing {filename} ...")
        segments_iter, info = model.transcribe(
            str(video_path),
            language="en",
            word_timestamps=True,
            vad_filter=True,
        )
        segments = list(segments_iter)
        prayer, cues, raw_segs = cues_from_segments(segments)
        print(
            f"    duration={info.duration:.1f}s segments={len(raw_segs)} cues={len(cues)}"
        )

        raw_path = RAW_DIR / f"{key}_whisper_raw.json"
        raw_path.write_text(
            json.dumps(
                {
                    "video": filename,
                    "duration": info.duration,
                    "language": info.language,
                    "segments": raw_segs,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        loop["prayer"] = prayer
        loop["video"] = filename
        loop["audioSync"] = True
        loop["audioCues"] = cues

    LOOPS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {LOOPS_JSON}")

    # Sync Excel prayer + video columns when openpyxl is available.
    try:
        import openpyxl
    except ImportError:
        print("openpyxl not installed; skipped Excel update")
        return 0

    if not XLSX.is_file():
        print(f"Missing {XLSX}; skipped Excel update")
        return 0

    wb = openpyxl.load_workbook(XLSX)
    ws = wb.active
    # Data rows start at 2; first N rows with leading questions map to loops.
    loop_i = 0
    for row in range(2, ws.max_row + 1):
        prayer_cell = ws.cell(row, 1).value
        leading = ws.cell(row, 2).value
        if not prayer_cell:
            continue
        if not leading:
            # closing row — leave prayer unless empty
            continue
        if loop_i >= len(loops):
            break
        loop = loops[loop_i]
        ws.cell(row, 1).value = loop.get("prayer") or prayer_cell
        key = loop.get("videoKey")
        ws.cell(row, 3).value = VIDEO_BY_KEY.get(key, key)
        loop_i += 1

    wb.save(XLSX)
    print(f"Updated {XLSX} ({loop_i} loops)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
