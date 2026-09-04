# CHILD/REN of the BLOOM — Ars front end

Static kiosk UI (HTML / CSS / JS + p5.js). No build step required.

Canonical display size matches the source videos: **688×1032** (2:3), scaled uniformly to fit the browser window.

---

## Local kiosk (Raspberry Pi / desktop with Ollama)

For the real installation, do **not** use `npm start` alone. Run the Python bridge so chat and cue saves work:

```bash
cd CTC_Backend
python -m pip install -r requirements.txt
python ars_server.py
```

Open `http://127.0.0.1:8765/`.

That single process:

- serves this front end
- exposes chat APIs backed by Ollama + Child persona
- loads experience loops from `assets/docs/loops.json` (preferred when timed cues exist)
- accepts `PUT /api/loops` so the cue editor can save in place
- keeps short per-session history and Excel logging

Requires Ollama running locally with the configured model (default `llama3`).

### UI-only preview (no Ollama)

```bash
cd Frontend/Ars
npm start
```

Chat replies and in-place cue saves need `ars_server.py`.

---

## Visitor experience flow

```text
Landing
  → Sacred Place (disclaimer)
  → for each of 8 videos:
       A child's prayer  (timed lines over video with sound)
       → Chat            (leading question; 5 turns, except last loop = 1 offering)
  → Your prayer          (visitor's final offering, carousel)
  → Credits
  → Begin again → Landing
```

Notes:

- **The Portal** closing prayer is unused in the current flow.
- Prayer lines advance from `audioCues` start times synced to video audio.
- Authored cue = one reading line; the app may width-wrap long cues. Continuation lines use `wordTiming` / `wordStarts` when present.
- Chat returns to landing after **10 minutes** with no submitted messages.
- Message bubbles wrap; the chat panel does not scroll horizontally.

---

## Content: `loops.json`

Primary content file: `assets/docs/loops.json`.

Each loop typically has:

| Field | Purpose |
|-------|---------|
| `video` / `videoKey` | Filename under `assets/videos/` (e.g. `Video07Sound.mp4`) |
| `prayer` | Full prayer text (newline-separated; mirrored from cues) |
| `leadingQuestion` | First bot message in chat |
| `audioSync` | When true, prayer advances from video time |
| `audioCues[]` | `{ text, start, end, nowrap?, wordTiming?, wordStarts? }` |
| `wrapFraction` | Optional per-loop wrap width (else top-level `wrapFraction`, default `0.48`) |
| `wrapMode` | `"width"` (default) or `"punctuation"` (punctuation-first wrapping) |

Videos live in `assets/videos/` as `Video01Sound.mp4` … `Video08Sound.mp4`.

### Cue editor

Open `http://127.0.0.1:8765/cue-review.html` while `ars_server.py` is running.

- Rows are **visual lines** (same wrap rules as the app).
- Preview uses the same 688×1032 logical viewport as the kiosk.
- **Save** writes to `loops.json` via `PUT /api/loops` (button lights only when dirty).
- Without the API, Save falls back to downloading a JSON file.

### Whisper / alignment scripts

From `Frontend/Ars`:

| Script | Role |
|--------|------|
| `scripts/batch_align_all_prayers.py` | Transcribe all videos → raw Whisper + draft cues |
| `scripts/recase_from_docx.py` | Recase Whisper text using the Video Essay `.docx` |
| `scripts/bake_word_timings.py` | Attach per-word starts to cues |
| `scripts/fix_word_timings.py` | Remove invalid `0.0` / non-monotonic word times |
| `scripts/redo_earthvideo07.py` | Re-transcribe + rebuild loop 7 only |
| `scripts/refine_earthvideo07.py` | Split loop 7 into shorter timed lines from saved Whisper |

Raw Whisper JSON lives under `assets/docs/whisper_raw/`.

---

## Staff / install controls

### Fullscreen lock

**Click to begin** enters fullscreen and arms a staff lock.

- Escape always leaves browser fullscreen (cannot be blocked).
- The **Staff unlock** panel covers the UI immediately.
- Password: `children123` (constant `KIOSK_EXIT_PASSWORD` in `js/app.js`).
- Wrong password, **Return to kiosk**, or **1 minute idle** dismisses the panel and returns to kiosk mode.

### Jump shortcuts (not for visitors)

Use while **not** focused in a text field:

| Shortcut | Destination |
|----------|-------------|
| `Ctrl+Shift+1` … `8` | That video’s **prayer** |
| `Ctrl+Shift+Alt+1` … `8` | That video’s **chat** |
| `Ctrl+Shift+E` | Ending **Your prayer** |
| `Ctrl+Shift+C` | **Credits** |

Last chat: `Ctrl+Shift+Alt+8` (or `Ctrl+Shift+8` then **Skip**).

### Replacing videos

Overwrite `assets/videos/VideoXXSound.mp4` with the **same filename**. Hard-refresh. Re-run Whisper + cue review if the spoken take changed. See the [root README](../../README.md#replacing-a-video).

---

## Key front-end files

| Path | Role |
|------|------|
| `index.html` | Kiosk shell, fullscreen unlock panel |
| `cue-review.html` | Timed-line editor + app-matched preview |
| `js/app.js` | Scenes, video, prayer sync, chat, credits, staff shortcuts |
| `js/prayer-lines.js` | Shared wrap / cue expansion (app + cue review) |
| `js/api.js` | `/api/*` client with `loops.json` fallback + cache busting |
| `js/sketch.js` | p5 background + 688×1032 kiosk layout |
| `css/style.css` | Screens, poem, chat, credits, lock panel |
| `assets/docs/loops.json` | Experience content |
| `assets/logos/` | Credits partner marks |

---

## Azure App Service (Node)

This folder is static files only. On a **Node** App Service you must run a small static server.

1. Deploy the **contents** of `Frontend/Ars` so `index.html` is at the site root.
2. Runtime stack: **Node**.
3. Startup command:

**Linux:**

```bash
npx --yes serve -s -l $PORT .
```

**Windows:**

```bash
npx --yes serve -s -l %PORT% .
```

4. Restart the Web App.

On static hosts, `/api/loops` is unavailable; the app loads `assets/docs/loops.json` instead. Cue editor save-in-place requires the Python bridge.

### Smoke checks

- `/` loads the landing title
- `/assets/Title_Heading.png` returns 200
- `/js/vendor/p5.min.js` returns 200
- Prayer / chat / credits flow over HTTPS

---

## Other static hosts

Point the publish directory at `Frontend/Ars`.

- **Netlify / Vercel:** configs included (`netlify.toml`, `vercel.json`)
- **GitHub Pages / any web server:** serve this directory as site root

---

## Notes

- Asset paths are relative (`./css`, `./js`, `./assets`).
- p5.js is vendored at `js/vendor/p5.min.js`.
- Fonts load from Google Fonts (needs network). For offline kiosks, vendor those files.
- Design reference files (`SAMPLE_*`, stylesheet PDF) are not required at runtime.
- After editing `loops.json` on disk, refresh the app (API uses cache-busting). If the Python server was started before a manual file edit, prefer Save from cue review or restart `ars_server.py` so in-memory loops match disk.
