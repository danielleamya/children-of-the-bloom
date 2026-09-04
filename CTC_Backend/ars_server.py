#!/usr/bin/env python3
"""
Local HTTP bridge between the Ars kiosk front end and ars_backend.py.

Serves Frontend/Ars as static files and exposes:

    GET  /api/health
    GET  /api/loops            -> prayer / leading question / video segments
    PUT  /api/loops            -> persist cue-editor edits to loops.json
    POST /api/session          -> { "session_id": "..." }
    POST /api/chat             -> { "session_id", "message" }
    POST /api/session/reset    -> clear one session (or all if omitted)

Also serves /cue-review.html for timed prayer editing.

Designed for Raspberry Pi / desktop local runs (not public cloud).

Run from anywhere:

    python ars_server.py

Then open http://127.0.0.1:8765/
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

import ars_backend as backend

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "Frontend" / "Ars"
LOOPS_JSON = FRONTEND_DIR / "assets" / "docs" / "loops.json"
LOOPS_XLSX = FRONTEND_DIR / "assets" / "docs" / "conversational_template.xlsx"
VIDEOS_DIR = FRONTEND_DIR / "assets" / "videos"

HOST = "0.0.0.0"
PORT = 8765
DEFAULT_TURNS_PER_LOOP = 5

app = Flask(__name__, static_folder=None)
_sessions: dict[str, list[dict[str, str]]] = {}
_sessions_lock = threading.Lock()
_kb: list[dict[str, str]] = []
_loops_payload: dict[str, Any] = {"turnsPerLoop": DEFAULT_TURNS_PER_LOOP, "loops": [], "closing": None}


def _resolve_video(stem: str | None) -> str | None:
    if not stem:
        return None
    key = str(stem).strip()
    if not key or not VIDEOS_DIR.is_dir():
        return None

    # Already a full filename.
    if key.lower().endswith(".mp4"):
        exact_file = VIDEOS_DIR / key
        return exact_file.name if exact_file.is_file() else None

    # Prefer spoken takes when present (e.g. Child01_WithSound.mp4).
    if key.lower().endswith("_withsound"):
        exact = VIDEOS_DIR / f"{key}.mp4"
        if exact.is_file():
            return exact.name
    else:
        with_sound = VIDEOS_DIR / f"{key}_WithSound.mp4"
        if with_sound.is_file():
            return with_sound.name

    exact = VIDEOS_DIR / f"{key}.mp4"
    if exact.is_file():
        return exact.name

    matches = sorted(
        path.name
        for path in VIDEOS_DIR.glob("*.mp4")
        if path.stem.lower().startswith(key.lower())
        or key.lower() in path.stem.lower()
    )
    # Prefer any WithSound match when multiple exist.
    voiced = [m for m in matches if "withsound" in m.lower()]
    if voiced:
        return voiced[0]
    return matches[0] if matches else None


def _load_loops_from_xlsx(path: Path) -> dict[str, Any] | None:
    try:
        import openpyxl
    except ImportError:
        return None

    if not path.is_file():
        return None

    workbook = openpyxl.load_workbook(path, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return None

    loops: list[dict[str, Any]] = []
    closing: dict[str, Any] | None = None

    for row in rows[1:]:
        prayer, leading, video = (tuple(row) + (None, None, None))[:3]
        if not prayer:
            continue

        prayer_text = str(prayer).strip()
        leading_text = str(leading).strip() if leading else None
        video_key = str(video).strip() if video else None
        video_file = _resolve_video(video_key)
        entry = {
            "prayer": prayer_text,
            "leadingQuestion": leading_text,
            "video": video_file,
            "videoKey": video_key,
            "audioSync": bool(video_file and "withsound" in video_file.lower()),
        }
        if leading_text:
            loops.append(entry)
        else:
            closing = entry

    return {
        "turnsPerLoop": DEFAULT_TURNS_PER_LOOP,
        "loops": loops,
        "closing": closing,
    }


def _load_loops_from_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    data.setdefault("turnsPerLoop", DEFAULT_TURNS_PER_LOOP)
    data.setdefault("loops", [])
    data.setdefault("closing", None)
    return data


def load_experience_loops() -> dict[str, Any]:
    json_payload = _load_loops_from_json(LOOPS_JSON)
    xlsx_payload = _load_loops_from_xlsx(LOOPS_XLSX)

    # Prefer JSON when it carries timed prayer cues (editor / Whisper pipeline).
    json_loops = (json_payload or {}).get("loops") or []
    if json_payload and any(isinstance(loop, dict) and loop.get("audioCues") for loop in json_loops):
        return json_payload

    payload = xlsx_payload or json_payload
    if payload is None:
        return {
            "turnsPerLoop": DEFAULT_TURNS_PER_LOOP,
            "loops": [],
            "closing": None,
        }
    return payload


def _new_session_id() -> str:
    return secrets.token_urlsafe(16)


def _get_history(session_id: str) -> list[dict[str, str]]:
    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = []
        return _sessions[session_id]


@app.get("/api/health")
def health():
    ready = backend.check_ollama_ready()
    return jsonify(
        {
            "ok": ready,
            "model": backend.MODEL_NAME,
            "kb_entries": len(_kb),
            "loops": len(_loops_payload.get("loops") or []),
            "frontend": FRONTEND_DIR.is_dir(),
        }
    ), (200 if ready else 503)


@app.get("/api/loops")
def get_loops():
    return jsonify(_loops_payload)


@app.put("/api/loops")
@app.post("/api/loops")
def save_loops():
    """Persist edited loops.json from cue-review.html.

    Updates both the on-disk file and the in-memory payload so the next
    GET /api/loops (and a hard-refreshed kiosk) sees the new timings immediately.
    """
    global _loops_payload
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("loops"), list):
        return jsonify({"ok": False, "error": "Expected { loops: [...] }"}), 400

    payload.setdefault("turnsPerLoop", DEFAULT_TURNS_PER_LOOP)
    payload.setdefault("closing", _loops_payload.get("closing"))

    LOOPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOOPS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _loops_payload = payload
    return jsonify({"ok": True, "loops": len(payload.get("loops") or [])})


@app.post("/api/session")
def create_session():
    session_id = _new_session_id()
    with _sessions_lock:
        _sessions[session_id] = []
    return jsonify({"session_id": session_id})


@app.post("/api/session/reset")
def reset_session():
    payload = request.get_json(silent=True) or {}
    session_id = payload.get("session_id")

    with _sessions_lock:
        if session_id:
            _sessions.pop(str(session_id), None)
        else:
            _sessions.clear()

    return jsonify({"ok": True})


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id") or "").strip()
    message = str(payload.get("message") or "").strip()

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    if not message:
        return jsonify({"error": "message is required"}), 400

    history = _get_history(session_id)
    kb_match = backend.find_relevant_prayer(message, _kb)
    prompt = backend.build_user_prompt(message, kb_match)
    reply = backend.query_ollama(prompt, list(history))
    print(f"[DEBUG] Ollama reply: {repr(reply)}")

    if reply is None:
        return jsonify(
            {
                "error": "ollama_unavailable",
                "reply": "The spirits are quiet right now. Try again in a moment.",
            }
        ), 503

    backend.update_history(history, message, reply)
    backend.log_to_excel(message, reply, backend.LOG_FILE)

    return jsonify(
        {
            "session_id": session_id,
            "reply": reply,
            "kb_matched": bool(kb_match),
        }
    )


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path: str):
    target = FRONTEND_DIR / path
    if target.is_file():
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, "index.html")


def main() -> int:
    if not backend.check_python_dependencies():
        return 1

    if not FRONTEND_DIR.is_dir():
        print(f"[ERROR] front end folder not found: {FRONTEND_DIR}")
        return 1

    backend.ensure_knowledge_base_file(backend.CSV_KB_PATH)
    global _kb, _loops_payload
    _kb = backend.load_knowledge_base(backend.CSV_KB_PATH)
    _loops_payload = load_experience_loops()

    if not backend.check_ollama_ready():
        print("[WARNING] Ollama is not ready yet; /api/health will report ok=false.")
        print("Start Ollama and ensure the model is pulled, then retry chat requests.\n")

    print("Ars local server")
    print(f"  UI:      http://127.0.0.1:{PORT}/")
    print(f"  health:  http://127.0.0.1:{PORT}/api/health")
    print(f"  loops:   http://127.0.0.1:{PORT}/api/loops")
    print(f"  model:   {backend.MODEL_NAME}")
    print(f"  kb rows: {len(_kb)}")
    print(f"  segments:{len(_loops_payload.get('loops') or [])}")
    print(f"  turns:   {_loops_payload.get('turnsPerLoop', DEFAULT_TURNS_PER_LOOP)}")
    print(f"  front:   {FRONTEND_DIR}\n")

    app.run(host=HOST, port=PORT, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
