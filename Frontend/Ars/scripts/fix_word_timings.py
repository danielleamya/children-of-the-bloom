"""Remove invalid wordTiming zeros / regressions that break prayer sync."""
from __future__ import annotations

import json
from pathlib import Path

loops_path = Path(__file__).resolve().parents[1] / "assets" / "docs" / "loops.json"


def fix_cue(cue: dict) -> bool:
    changed = False
    text = (cue.get("text") or "").strip()
    tokens = text.split()
    start = float(cue.get("start") or 0)
    end = float(cue.get("end") or start + 2)
    if end <= start:
        end = start + max(1.0, 0.35 * max(1, len(tokens)))

    timing = cue.get("wordTiming")
    if not isinstance(timing, list) or not tokens:
        return False

    # Pad / trim to token count
    if len(timing) != len(tokens):
        if len(timing) < len(tokens):
            timing = list(timing) + [None] * (len(tokens) - len(timing))
        else:
            timing = list(timing[: len(tokens)])
        changed = True

    cleaned: list[float] = []
    for i, raw in enumerate(timing):
        try:
            t = float(raw)
        except (TypeError, ValueError):
            t = None
        # Reject failed alignments and times before the cue window.
        if t is None or t < start - 0.05 or t > end + 1.5:
            frac = i / max(1, len(tokens) - 1) if len(tokens) > 1 else 0
            t = start + (end - start) * frac
            changed = True
        cleaned.append(round(t, 3))

    # Enforce mild monotonicity
    for i in range(1, len(cleaned)):
        if cleaned[i] + 0.01 < cleaned[i - 1]:
            cleaned[i] = cleaned[i - 1]
            changed = True

    cue["wordTiming"] = cleaned
    word_starts: dict[str, float] = {}
    for tok, t in zip(tokens, cleaned):
        key = "".join(ch for ch in tok.lower() if ch.isalnum() or ch in "'")
        if key and key not in word_starts:
            word_starts[key] = t
    cue["wordStarts"] = word_starts
    return changed


def main() -> None:
    data = json.loads(loops_path.read_text(encoding="utf-8"))
    fixed = 0
    for loop in data.get("loops") or []:
        for cue in loop.get("audioCues") or []:
            if fix_cue(cue):
                fixed += 1
    loops_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"fixed {fixed} cues in {loops_path}")


if __name__ == "__main__":
    main()
