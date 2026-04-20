# Doorway — POC

A Harvest-Moon-meets-AI-magic prototype for ChatGPT Apps. See the sibling docs one level up for context:

- `../DOORWAY_KICKOFF.md` — what we're building and why.
- `../DOORWAY_POC_PLAN.md` — the 2-3 day plan.
- `../CHATGPT_APP_HANDOVER.md` — every platform gotcha we've learned the hard way.

This folder holds the code. **Day 0 scaffolding** — what's here now — gets you from zero to "ChatGPT loads the widget and shows a handshake message." No game yet; that's Day 1.

## What's in here

```
doorway/
├── README.md               # this file — your Day 0 checklist
├── .gitignore
└── server/
    ├── doorway_mcp/
    │   ├── __init__.py
    │   ├── server.py       # MCP server with one placeholder tool (open_world)
    │   └── widgets/
    │       └── doorway_v1.html   # Day 0 handshake widget
    ├── requirements.txt
    ├── Procfile            # Railway start command
    ├── railway.json        # Railway build/deploy config
    ├── runtime.txt         # Python version pin (for Railway's Nixpacks)
    ├── .python-version     # Python version pin (for pyenv users)
    ├── schema.sql          # Postgres schema — Day 1+ uses it, not Day 0
    └── smoke_test.sh       # curl-based local verification
```

The only "game-shaped" thing here is a widget that says "handshake successful" when the platform is wired up correctly. Everything else is plumbing.

## Day 0 checklist

Run these in order. Stop if anything fails — don't try to power through to the next step.

### 1. Local install and smoke test (~15 min)

```bash
cd server
python -m venv .venv
source .venv/bin/activate           # Windows (Git Bash / WSL): same
                                    # Windows (PowerShell): .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn doorway_mcp.server:app --host 0.0.0.0 --port 8000
```

In a **second** terminal, from the same `server/` folder:

```bash
chmod +x smoke_test.sh
./smoke_test.sh
```

(On Windows without Git Bash, open `smoke_test.sh` and run the `curl` commands manually — or install WSL.)

**What to verify in the output:**

- `tools/list` returns `"_meta"` **with the underscore**. If it's `"meta"` without the underscore, the `_meta=` kwarg got serialized wrong — this is the single most common mistake on this platform and it silently breaks everything.
- `openai/outputTemplate` inside the tool's `_meta` matches `ui://widget/doorway-v1.html` exactly.
- `tools/call open_world` returns `structuredContent: {status: "ok", ...}`.
- `resources/read` returns `mimeType: "text/html+skybridge"` (with the `+skybridge` suffix — plain `text/html` will render inert).
- Widget `_meta` has both `ui.csp.*` AND `openai/widgetCSP.*` keys.

If those six things are green, local is good.

### 2. Create a GitHub repo

- Suggested name: `doorway` or `harvest-town-doorway`.
- Initialize git from **this `doorway/` folder**, not from the parent `Harvest Town/` folder — the docs in the parent belong to a different scope.

```bash
cd ..                      # now in the doorway/ folder
git init
git add .
git commit -m "Day 0 scaffolding"
# create the repo on github.com, then:
git remote add origin git@github.com:<you>/doorway.git
git push -u origin main
```

### 3. Create a Railway project

- Railway → New Project → Deploy from GitHub repo → select `doorway`.
- **Critical:** Railway Service Settings → General → **Root Directory** → set to `server`. Otherwise Railway looks for `requirements.txt` at the repo root and fails the build with a confusing error.
- Wait for deploy. Check the build log — verify it picked up Python 3.12.x. If it landed on 3.10, open a support thread with yourself: Railway occasionally ignores `runtime.txt`.

### 4. Add Postgres on Railway

Day 0's server doesn't use Postgres — it's all stateless — but Day 1's does, so set it up now while you're here.

- In the Railway project, click **New → Database → Add PostgreSQL**.
- Railway auto-injects `DATABASE_URL` into your service's environment.
- Apply the schema: click your new Postgres service → **Query** tab → paste the contents of `server/schema.sql` → Run.

### 5. Verify the Railway deployment

Get your Railway URL (something like `https://doorway-production.up.railway.app`). Then:

```bash
curl https://<your-url>/health
# expect: {"status":"ok","service":"doorway"}

./server/smoke_test.sh https://<your-url>
# expect: same verification output as step 1, but against Railway
```

If Railway returns HTML error pages or 502s, the service may be cold-starting — wait 30 seconds and retry. If it's persistently broken, check Railway logs for Python import errors (the handover doc calls out the `StreamableHTTPSessionManager` import path as a common gotcha).

### 6. Connect to ChatGPT as a dev-mode connector

- ChatGPT → Settings → **Connectors** → look for **"Developer mode"** (sometimes under Advanced; OpenAI renames this regularly).
- Enable Developer mode if it's off.
- **Create / Add MCP server** (the developer-mode path, NOT "Add custom connector" — that one demands OAuth and will refuse an unauthenticated server).
- URL: `https://<your-url>/mcp` (include the `/mcp` path).
- **Warm the server first:** open `https://<your-url>/health` in your browser before clicking Create. This wakes a sleeping Railway dyno so ChatGPT's handshake doesn't hit a cold start and time out.

### 7. The Day 0 success test

In ChatGPT, start a new conversation with the Doorway connector enabled. Type:

> Open Doorway.

ChatGPT should call the `open_world` tool. A widget should appear showing:

- Title: **Doorway**, subtitle **Day 0 — platform handshake**
- A green status box: *Doorway Day 0 handshake successful.*
- Diagnostics: "Host detected: yes", display mode, viewport dimensions, theme, locale, and the tool output JSON.

If you see this, **Day 0 is done.** Move on to Day 1 tomorrow.

---

## Troubleshooting

**The smoke test is red on `_meta`.** You have `meta=` somewhere instead of `_meta=` in `server.py`. Pydantic alias behaviour — the kwarg has to be underscored.

**"Unknown resource: ui://widget/doorway-v1.html"** in smoke test step 6. The `read_resource` handler is comparing `uri` (a pydantic AnyUrl object) directly against the string URI. Use `str(uri) == WIDGET_URI`.

**Railway build fails: "requirements.txt not found".** The service's Root Directory isn't set to `server`.

**Railway build picks Python 3.10.** `runtime.txt` was ignored. Double-check spelling: `python-3.12.3`, no extra whitespace. If it persists, set the Python version in Railway's environment variables: `NIXPACKS_PYTHON_VERSION=3.12.3`.

**Connector added successfully, but the tool doesn't show up / tool call errors.** ChatGPT caches tool descriptors. Delete the connector, wait 30 seconds, re-add it. If that fails, bump the widget URI version in `server.py` (`doorway-v1` → `v2`) AND rename the widget HTML file, redeploy, re-add the connector. The full cache-busting ladder is in the handover doc.

**Widget loads but says "no tool output received yet".** ChatGPT invoked the tool but didn't pipe `structuredContent` to the widget. Almost always a `_meta` key mismatch — `openai/outputTemplate` in the tool's `_meta` must be string-identical to the resource URI. Re-run the smoke test and compare exactly.

**Widget never loads (widget area is blank or shows error).** Likely MIME type — must be `text/html+skybridge`, not plain `text/html`. Check `read_resource` in `server.py`.

See `../CHATGPT_APP_HANDOVER.md` for the full pitfalls list, roughly ordered by frequency.

---

## What's next

Once Day 0 is green, Day 1 starts. The plan (in `../DOORWAY_POC_PLAN.md`):

- Widget renders a room with player + Milli sprites.
- Tap-to-move.
- Tapping Milli flips mode to `in_conversation_with_milli`.
- Widget re-renders into a placeholder conversation state.
- **No LLM chat yet.** Just the mechanical doorway.

Day 1's gate: can I tap Milli and cleanly see the widget shift into conversation mode, surviving a full refresh? If yes, Day 2 wires up the actual conversation.
