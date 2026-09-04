"""Attach Whisper word timings to audioCues in loops.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

docs = Path(__file__).resolve().parents[1] / "assets" / "docs"
loops_path = docs / "loops.json"

WHISPER = {
    "Child01": docs / "Child01_whisper_raw.json",
    "Child02": docs / "whisper_raw" / "Child02_whisper_raw.json",
    "Nana03": docs / "whisper_raw" / "Nana03_whisper_raw.json",
    "ChildMe05": docs / "whisper_raw" / "ChildMe05_whisper_raw.json",
    "MassiveAlgal06": docs / "whisper_raw" / "MassiveAlgal06_whisper_raw.json",
    "EarthVideo07": docs / "whisper_raw" / "EarthVideo07_whisper_raw.json",
    "CosmicMother08": docs / "whisper_raw" / "CosmicMother08_whisper_raw.json",
    "Phytoplankton": docs / "whisper_raw" / "Phytoplankton_whisper_raw.json",
}

# Previous manual nudges for late-feeling Child01 phrases
CHILD01_NUDGE = {0: -0.22, 1: -0.25, 4: -0.22}


def norm_tok(word: str) -> str:
    w = (word or "").strip().lower()
    w = w.replace("\u2019", "'").replace("\u2018", "'")
    w = re.sub(r"^[^a-z0-9']+|[^a-z0-9']+$", "", w)
    return w


def flat_words(raw: dict) -> list[tuple[str, float, float]]:
    out: list[tuple[str, float, float]] = []
    for seg in raw.get("segments") or []:
        for w in seg.get("words") or []:
            tok = norm_tok(w.get("word"))
            if not tok:
                continue
            start = float(w["start"])
            end = float(w.get("end", start))
            out.append((tok, start, end))
    return out


def align_timing(
    text: str, flat: list[tuple[str, float, float]], cursor: int = 0
) -> tuple[list[float], dict[str, float], int]:
    tokens = text.strip().split()
    targets = [norm_tok(t) for t in tokens]
    timing: list[float | None] = [None] * len(targets)
    word_starts: dict[str, float] = {}
    i = cursor
    n = len(flat)

    for ti, tok in enumerate(targets):
        if not tok:
            timing[ti] = flat[i - 1][1] if i else 0.0
            continue
        found = None
        for j in range(i, min(n, i + 35)):
            fw = flat[j][0]
            if fw == tok or fw.startswith(tok[:4]) or tok.startswith(fw[:4]):
                found = j
                break
        if found is None:
            continue
        timing[ti] = round(flat[found][1], 3)
        if tok not in word_starts:
            word_starts[tok] = timing[ti]
        i = found + 1

    last: float | None = None
    for ti in range(len(timing)):
        if timing[ti] is not None:
            last = timing[ti]
        elif last is not None:
            timing[ti] = last
    for ti in range(len(timing) - 1, -1, -1):
        if timing[ti] is None and ti + 1 < len(timing) and timing[ti + 1] is not None:
            timing[ti] = timing[ti + 1]

    # Fill remaining gaps by interpolating across the matched window —
    # never write 0.0 placeholders (they break wrap sync in the app).
    known = [(i, t) for i, t in enumerate(timing) if t is not None]
    if not known:
        # No matches: even span (caller should still have cue start/end)
        n_tok = max(1, len(timing))
        timing = [float(i) for i in range(n_tok)]  # placeholder; fixed below
        known = []
    if known:
        for ti in range(len(timing)):
            if timing[ti] is not None:
                continue
            # find neighbors
            prev = next((p for p in reversed(known) if p[0] < ti), None)
            nxt = next((p for p in known if p[0] > ti), None)
            if prev and nxt:
                span_i = nxt[0] - prev[0]
                frac = (ti - prev[0]) / span_i if span_i else 0
                timing[ti] = prev[1] + (nxt[1] - prev[1]) * frac
            elif prev:
                timing[ti] = prev[1]
            elif nxt:
                timing[ti] = nxt[1]
            else:
                timing[ti] = 0.0

    return [float(t) for t in timing], word_starts, i


def main() -> None:
    data = json.loads(loops_path.read_text(encoding="utf-8"))

    for loop in data["loops"]:
        key = loop.get("videoKey") or ""
        path = WHISPER.get(key)
        if not path or not path.exists():
            print("skip", key, "no whisper")
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        flat = flat_words(raw)
        cursor = 0
        cues = loop.get("audioCues") or []
        for ci, cue in enumerate(cues):
            text = (cue.get("text") or "").strip()
            if not text:
                continue
            timing, wstarts, cursor = align_timing(text, flat, cursor)
            cue["wordTiming"] = timing
            cue["wordStarts"] = wstarts
            if key == "Child01" and ci in CHILD01_NUDGE:
                cue["start"] = round(float(cue["start"]) + CHILD01_NUDGE[ci], 2)
        print(key, "cues", len(cues), "flat", len(flat), "cursor", cursor)

    cues = data["loops"][0]["audioCues"]
    for i, c in enumerate(cues[:6]):
        keys = ["going", "travels", "silenced", "elsewhere", "dissociates"]
        hits = {k: c.get("wordStarts", {}).get(k) for k in keys if k in c.get("wordStarts", {})}
        print(i, c["start"], hits, c["text"][:52])

    loops_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("wrote", loops_path)


if __name__ == "__main__":
    main()
