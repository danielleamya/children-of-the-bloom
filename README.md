# CHILD/REN of the BLOOM

Interactive installation: timed prayer videos, generative chat (Ollama), credits, and optional hydroponics sensing.

This root `README.md` is the project landing page for Git/GitHub. Deeper module docs live in each folder.

---

## What’s in this repo

| Folder | Role | More docs |
|--------|------|-----------|
| [`Frontend/Ars`](Frontend/Ars) | Kiosk UI, videos, cue editor | [`Frontend/Ars/README.md`](Frontend/Ars/README.md) |
| [`CTC_Backend`](CTC_Backend) | Flask bridge + Child chat (Ollama) | [`CTC_Backend/README.md`](CTC_Backend/README.md) |
| [`Hydroponics`](Hydroponics) | Sensor polling + dashboard | [`Hydroponics/README.md`](Hydroponics/README.md) |

---

## How to run the kiosk

### Full install (recommended)

One process serves the UI, chat API, and cue-editor save:

```bash
cd CTC_Backend
python -m pip install -r requirements.txt
python ars_server.py
```

Open:

| URL | Purpose |
|-----|---------|
| [http://127.0.0.1:8765/](http://127.0.0.1:8765/) | Visitor kiosk |
| [http://127.0.0.1:8765/cue-review.html](http://127.0.0.1:8765/cue-review.html) | Cue / timing editor |

**Also required:** [Ollama](https://ollama.com/) running locally with the configured model (default `llama3`):

```bash
ollama pull llama3
ollama list
```

### UI-only preview

```bash
cd Frontend/Ars
npm start
```

Chat replies and **Save** in the cue editor will not work without `ars_server.py`.

### After code or content changes

- HTML/JS/CSS: hard-refresh the browser (`Ctrl+F5`). No server restart needed.
- `loops.json` saved via cue editor: refresh the kiosk; the API is updated in memory.
- Manual edits to `loops.json` on disk while the server is already running: either Save from cue review, or restart `ars_server.py`.
- Changes to `ars_server.py` / backend: restart the Python process.

---

## Visitor experience flow

```text
Landing
  → Sacred Place (disclaimer)
  → for each of 8 videos:
       A child's prayer   (lines timed to spoken audio)
       → Chat             (leading question; 5 turns; last loop = 1 offering)
  → Your prayer           (visitor’s final offering)
  → Credits
  → Begin again → Landing
```

Display size matches the videos: **688×1032** (2:3), scaled to fit the window.

---

## Added features (how they work)

### Timed prayers + audio sync

Each loop in `Frontend/Ars/assets/docs/loops.json` has `audioCues` with `start` / `end` (and often `wordTiming`). The kiosk advances poem lines from the video’s `currentTime`. Long lines may wrap; wrap continuations use per-word timings when present.

Shared wrap logic lives in `Frontend/Ars/js/prayer-lines.js` so the **app and cue editor stay aligned**.

### Cue review interface

URL: `/cue-review.html` (use with `ars_server.py`).

| Behavior | Detail |
|----------|--------|
| Purpose | Edit prayer line text and appearance times; preview like the kiosk |
| Layout | Left: editable lines. Right: app-matched preview (688×1032) |
| Rows | One row ≈ one on-screen line (not raw Whisper sentences) |
| Timing fields | Type a full number (e.g. `2.01`); focus selects the value for easy replace |
| Save | Enabled only when there are unsaved changes → `Saving…` → `Saved ✓` |
| Persist | `PUT /api/loops` writes `Frontend/Ars/assets/docs/loops.json` |
| Fallback | If the API is missing, Save downloads a JSON file instead |
| Re-wrap | Re-applies width wrapping after text edits |

Loop selector at the top switches videos 1–8. Nudge / Start=now / End=now / Split / Merge help refine sync.

### Fullscreen kiosk + password

| Step | What happens |
|------|----------------|
| Visitor clicks **Click to begin** | Browser enters fullscreen; staff lock is armed |
| Someone presses **Escape** | Browser always leaves fullscreen (cannot be blocked) |
| Immediately after | **Staff unlock** panel covers the experience |
| Correct password | Unlock and stay out of fullscreen |
| Wrong password | Panel closes; returns toward kiosk fullscreen |
| No submit for **1 minute** | Panel auto-dismisses the same way |
| **Return to kiosk** | Re-enters fullscreen without unlocking |

Password (staff only): **`children123`**  
Change it in `Frontend/Ars/js/app.js` → `KIOSK_EXIT_PASSWORD`.

### Staff section jumps (skip through the piece)

Use these while **not** typing in a chat/password field:

| Shortcut | Goes to |
|----------|---------|
| **Ctrl+Shift+1** … **Ctrl+Shift+8** | That video’s **prayer** |
| **Ctrl+Shift+Alt+1** … **Ctrl+Shift+Alt+8** | That video’s **chat** |
| **Ctrl+Shift+E** | Ending **Your prayer** |
| **Ctrl+Shift+C** | **Credits** |

Examples:

- Last chat quickly: **Ctrl+Shift+Alt+8**
- Or **Ctrl+Shift+8**, then **Skip** on the prayer screen
- End credits: **Ctrl+Shift+C**

### Credits

After **Your prayer**, Continue opens Credits (names/roles + partner logos). **Begin again** returns to Landing. The old **The Portal** section is not in the live flow.

### Chat behavior

- Messages wrap; no horizontal scroll in the chat panel.
- Idle **10 minutes** without a sent message → reset to Landing.
- Last video’s chat is a single prayer offering (no multi-turn bot reply), then **Your prayer**.

### Replacing a video

Videos are referenced by **fixed filenames**. To swap media:

1. Replace the file in `Frontend/Ars/assets/videos/` using the **same name**:
   - `Video01Sound.mp4` … `Video08Sound.mp4`
2. Hard-refresh the kiosk (and cue review if open).
3. **If timing/transcript must match the new take**, re-run Whisper alignment for that loop (see below), then fine-tune in cue review.  
   If you only swapped a re-encode with the same spoken performance, existing cues may still work—verify in cue review.

Map of loop → file (also in `loops.json` as `video` / `videoKey`):

| # | `videoKey` | Filename |
|---|------------|----------|
| 1 | Child01 | `Video01Sound.mp4` |
| 2 | Child02 | `Video02Sound.mp4` |
| 3 | Nana03 | `Video03Sound.mp4` |
| 4 | Phytoplankton | `Video04Sound.mp4` |
| 5 | ChildMe05 | `Video05Sound.mp4` |
| 6 | MassiveAlgal06 | `Video06Sound.mp4` |
| 7 | EarthVideo07 | `Video07Sound.mp4` |
| 8 | CosmicMother08 | `Video08Sound.mp4` |

Preferred resolution/aspect: **688×1032** (2:3) with spoken audio.

### Re-timing after a new take (optional)

From `Frontend/Ars` (needs `faster-whisper`, etc.):

```bash
# Example: rebuild loop 7 only
python scripts/redo_earthvideo07.py
python scripts/refine_earthvideo07.py
```

Or use the general pipeline: `batch_align_all_prayers.py` → `recase_from_docx.py` → `bake_word_timings.py` → `fix_word_timings.py`, then edit in cue review.

Essay casing source: `Frontend/Ars/assets/docs/Child_ren of the Bloom - Video Essay.docx`.

---

## Content locations

| Path | Purpose |
|------|---------|
| `Frontend/Ars/assets/docs/loops.json` | Prayers, cues, timings, leading questions |
| `Frontend/Ars/assets/videos/` | `Video01Sound.mp4` … `Video08Sound.mp4` (**Git LFS**) |
| `Frontend/Ars/assets/logos/` | Credits logos |
| `Frontend/Ars/assets/docs/whisper_raw/` | Raw Whisper transcripts |
| `Frontend/Ars/js/app.js` | Scenes, sync, lock, shortcuts |
| `Frontend/Ars/js/prayer-lines.js` | Shared line wrap / expansion |
| `Frontend/Ars/cue-review.html` | Timing editor |

### Git LFS (videos)

Prayer videos are large; this repo tracks `*.mp4` with [Git LFS](https://git-lfs.com/).

```bash
# One-time on each machine that clones or pushes videos
git lfs install
```

After cloning, LFS files download automatically if LFS is installed. Collaborators need LFS enabled on the remote (GitHub: repo → Settings → allow Git LFS / sufficient quota).

When adding or replacing a video, keep the same filename, then:

```bash
git add Frontend/Ars/assets/videos/VideoXXSound.mp4
git add .gitattributes   # if not already committed
# commit when ready — the file should show as an LFS pointer, not a full binary blob
```

Confirm a staged video is an LFS pointer:

```bash
git lfs ls-files
# or
git show :Frontend/Ars/assets/videos/Video07Sound.mp4 | Select-Object -First 5
# should start with: version https://git-lfs.github.com/spec/v1
```

---

## Deploy notes (static UI)

For Azure / Netlify / etc., publish the **contents** of `Frontend/Ars`. Static hosts serve the UI and `loops.json` but **not** live chat or cue Save—those need `ars_server.py` (or equivalent) on the install machine. See [`Frontend/Ars/README.md`](Frontend/Ars/README.md).

---

## Related docs

- Front-end deploy / smoke checks → [`Frontend/Ars/README.md`](Frontend/Ars/README.md)
- Chat API, knowledge bases, Dark Mother → [`CTC_Backend/README.md`](CTC_Backend/README.md)
- Hydroponics sensors → [`Hydroponics/README.md`](Hydroponics/README.md)
