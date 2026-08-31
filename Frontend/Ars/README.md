# CHILD/REN of the BLOOM — Ars front end

Static kiosk UI (HTML / CSS / JS + p5.js). No build step required.

## Local kiosk (Raspberry Pi / desktop with Ollama)

For the real installation, do **not** use `npm start` alone. Run the Python bridge so the chat UI talks to `ars_backend.py`:

```bash
cd CTC_Backend
python -m pip install -r requirements.txt
python ars_server.py
```

Open `http://127.0.0.1:8765/`.

That single process:
- serves this front end
- exposes `POST /api/chat` backed by Ollama + Child persona
- loads prayer / leading-question / video loops from `assets/docs/`
- keeps short per-session history and Excel logging

### Experience loop

After Landing → Sacred Place, the piece repeats:

1. **A child's prayer** — same line/section carousel as before, over the matching video
2. **Chat** opens with that row’s leading question
3. After **5** user turns, the next prayer + video begins

Prayer copy advances **line by line** from the Excel text (blank lines skipped).

Requires Ollama running locally with the configured model (default `llama3`).

## Local preview (UI only, no Ollama)

From this folder:

```bash
npm start
```

Or:

```bash
python -m http.server 8765
```

Open `http://127.0.0.1:8765/`. Chat replies will fail until `ars_server.py` is running.

## Azure App Service (Node)

This folder is static files only. On a **Node** App Service you must run a small static server.

### Deploy

1. Deploy the **contents** of `Frontend/Ars` so `index.html` is at the site root (`wwwroot/index.html`), not nested under another `Frontend/Ars` folder.
2. Runtime stack: **Node**.
3. Set **Startup Command** (Configuration → General settings):

**Linux:**

```bash
npx --yes serve -s -l $PORT .
```

**Windows:**

```bash
npx --yes serve -s -l %PORT% .
```

4. Save and **Restart** the Web App.
5. Open `https://<app-name>.azurewebsites.net/`.

### Why a startup command?

Node App Service does not serve `index.html` by itself. Without a start command (or `npm start` that binds to `PORT`), the site often shows an application error.

`serve` is pulled via `npx` on first start (outbound network required). Prefer binding to Azure’s `PORT` env var, not a hard-coded local port like `8765`.

### Smoke checks after deploy

- `/` loads the landing title
- `/assets/Title_Heading.png` returns 200
- `/js/vendor/p5.min.js` returns 200
- Poem / chat flows work over HTTPS

## Other static hosts

Point the host’s **publish directory** at `Frontend/Ars` (this folder).

- **Netlify / Vercel:** configs included (`netlify.toml`, `vercel.json`)
- **GitHub Pages:** publish this folder, or copy its contents to `docs/` / `gh-pages`
- **Any web server:** serve this directory as the site root; `index.html` is the entry

## Notes

- Asset paths are relative (`./css`, `./js`, `./assets`) so the app can live at a domain root.
- p5.js is vendored at `js/vendor/p5.min.js` (no CDN required for the sketch).
- Fonts still load from Google Fonts (needs network). For fully offline kiosks, download those font files next.
- Design reference files in `assets/` (`SAMPLE_*`, stylesheet PDF) are not required at runtime.
- Chat returns to the landing screen after 10 minutes with no submitted messages.
