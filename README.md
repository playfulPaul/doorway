# Doorway — POC

A Harvest-Moon-meets-AI-magic prototype for ChatGPT Apps. See the sibling docs one level up for context:

- `../DOORWAY_KICKOFF.md` — what we're building and why.
- `../DOORWAY_POC_PLAN.md` — the 2-3 day plan.
- `../CHATGPT_APP_HANDOVER.md` — every platform gotcha we've learned the hard way.

This folder holds the code. **Day 0 scaffolding** — what's here now — gets you from zero to "ChatGPT loads the widget and shows a handshake message." No game yet; that's Day 1.

## What's in here

```
doorway/
├── README.md               # this file — Day 0 + Day 1 checklists
├── .gitignore
└── server/
    ├── doorway_mcp/
    │   ├── __init__.py
    │   ├── server.py       # MCP server: open_world, approach_milli, leave_milli
    │   ├── state.py        # Postgres + in-memory player state layer
    │   └── widgets/
    │       ├── doorway_v1.html   # Day 0 handshake (kept for reference; superseded)
    │       └── doorway_v2.html   # Day 1 widget (current)
    ├── requirements.txt
    ├── Procfile            # Railway start command
    ├── railway.json        # Railway build/deploy config
    ├── runtime.txt         # Python version pin (for Railway's Nixpacks)
    ├── .python-version     # Python version pin (for pyenv users)
    ├── schema.sql          # Postgres schema — applied on Day 0; used from Day 1
    └── smoke_test.sh       # curl-based local verification
```

Day 0's job was the platform handshake. Day 1's job is the world: a tiny room, two characters, a tap-to-move mechanic, and a clean transition into a (placeholder) conversation that survives a refresh.

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
- URL: `https://<your-url>/mcp/` — **include the trailing slash.** Without it, ChatGPT's MCP client doesn't follow Starlette's 307 redirect on POST and hangs until timeout. Curl and the smoke test *do* follow redirects silently, so the server looks fine when tested from your terminal — this is the #1 "server works but connector won't connect" cause.
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

**"Error creating connector — upstream connect error ... connection timeout"** when adding the server in ChatGPT, even though `/health` works in your browser and the smoke test passes. Trailing-slash issue — use `https://<your-url>/mcp/`, not `https://<your-url>/mcp`. ChatGPT's MCP client doesn't follow Starlette's 307 POST redirect, so the request silently stalls. Confirmed hazard — hit on Day 0, 2026-04-20.

**Connector added successfully, but the tool doesn't show up / tool call errors.** ChatGPT caches tool descriptors. Delete the connector, wait 30 seconds, re-add it. If that fails, bump the widget URI version in `server.py` (`doorway-v1` → `v2`) AND rename the widget HTML file, redeploy, re-add the connector. The full cache-busting ladder is in the handover doc.

**Widget loads but says "no tool output received yet".** ChatGPT invoked the tool but didn't pipe `structuredContent` to the widget. Almost always a `_meta` key mismatch — `openai/outputTemplate` in the tool's `_meta` must be string-identical to the resource URI. Re-run the smoke test and compare exactly.

**Widget never loads (widget area is blank or shows error).** Likely MIME type — must be `text/html+skybridge`, not plain `text/html`. Check `read_resource` in `server.py`.

See `../CHATGPT_APP_HANDOVER.md` for the full pitfalls list, roughly ordered by frequency.

---

## Day 1 checklist

Day 1 introduces a server-side state layer (`state.py`), three tools (`open_world`, `approach_milli`, `leave_milli`), and a new widget (`doorway-v2.html`) that renders a small room, two characters, and a placeholder conversation view.

You don't need to redo Day 0 — GitHub repo, Railway project, Postgres, and the dev-mode connector are already wired. Day 1 is just: push the code, re-add the connector to clear ChatGPT's widget cache, and run the gate test.

### 1. Local smoke test (~5 min)

From `server/`:

```bash
source .venv/bin/activate           # PowerShell: .\.venv\Scripts\Activate.ps1
uvicorn doorway_mcp.server:app --host 0.0.0.0 --port 8000
```

In a second terminal (Git Bash, or paste curl commands manually in PowerShell):

```bash
./smoke_test.sh
```

The smoke test now has 8 steps. **Three are new and matter most:**

- **Step 3** — `tools/list` returns three tools (`open_world`, `approach_milli`, `leave_milli`), each with `_meta` (underscore!) pointing at `ui://widget/doorway-v2.html`. The two widget-only tools must have `ui.visibility: ["app"]`.
- **Step 5** — calling `approach_milli` returns `mode: "in_conversation_with_milli"` in `structuredContent`.
- **Step 6** — calling `open_world` *again* (after step 5) returns the *same* mode. This is the persistence test in CLI form: state survived between tool calls.

If those three are green, the server is ready to push.

### 2. Push to GitHub → Railway auto-deploys

```bash
git add .
git commit -m "Day 1 — world, mode flip, state layer"
git push
```

Wait for Railway to redeploy (watch the Deployments tab; ~30-60s). Verify with:

```bash
./smoke_test.sh https://<your-railway-url>
```

Persistence on Railway is real — `DATABASE_URL` is auto-injected and `state.py` writes to Postgres. So if you call `approach_milli` once and then redeploy, the next `open_world` should still come back in conversation mode.

### 3. Re-add the ChatGPT connector (cache-bust)

The widget URI bumped from `doorway-v1` to `doorway-v2`. ChatGPT caches widget HTML by URI, so most of the time the URI bump alone is enough — but the safest path is to delete the connector and re-add it so descriptors refresh too.

- ChatGPT → Settings → Connectors → Doorway → **Delete**.
- Wait 30 seconds.
- Open `https://<your-railway-url>/health` in your browser (warm the dyno).
- ChatGPT → Connectors → Developer mode → Add MCP server → URL: `https://<your-railway-url>/mcp/` (**trailing slash**).

### 4. The Day 1 gate test

In a fresh ChatGPT chat with the Doorway connector enabled, type:

> Open Doorway.

You should see:

- A small dark room with a window (top-right area), a counter under it, a table in the middle, a door on the lower-left wall.
- Two figures: a blue "you" near the door, a warmer-toned Milli standing by the window with a small floating dot bobbing above her (the interaction hint).
- Tapping the floor moves you. Movement is local-only — no tool call fires for plain walking.
- Tapping Milli (or near her) walks you over to her, then a tool fires and the screen transitions into a conversation card: *"You're talking to Milli."* with a "Step away" button.
- Pressing "Step away" returns you to the room, standing slightly back from where Milli is.

**The gate**: leave the conversation open (mode = `in_conversation_with_milli`), then in *the same chat* (or a fresh one) say "Open Doorway" again. The widget should reload **directly into the conversation card**, not into the room. That's the proof that server state is the source of truth and the widget is a faithful renderer.

If the gate passes, Day 1 is done.

---

## Day 1 troubleshooting

**Widget loads but is empty / characters don't appear.** Probably the cache bit you — ChatGPT served the v1 HTML against the v2 URI somehow. Delete the connector, wait 30s, re-add. If that still fails, bump v2 → v3 in `server.py` AND rename `doorway_v2.html` → `doorway_v3.html`, redeploy, re-add.

**Tapping Milli does nothing.** Open the chat in a desktop browser, open dev tools → Console. Look for `[doorway] callTool failed`. If you see it, the widget tool call is being rejected — usually because `openai/widgetAccessible: true` is missing from one of the widget-only tools' `_meta`, or because `ui.visibility: ["app"]` isn't set right.

**The gate test fails — fresh "Open Doorway" snaps back to world mode.** Persistence isn't working. Check Railway's environment variables for `DATABASE_URL`. Open the Postgres service → Query tab → `SELECT * FROM players;` — the `mode` column should reflect your last action. If the table is empty or `DATABASE_URL` is missing, state's living in process memory and gets wiped on every Railway restart.

**Day 0 widget still shows up sometimes.** ChatGPT cached `doorway-v1` aggressively. Delete + re-add the connector usually fixes it. If not, the cache-busting ladder in `../CHATGPT_APP_HANDOVER.md` (URI bump → file rename → MCP route rename) is the escape hatch.

---

## What's next

Once Day 1 is green, Day 2 starts:

- Real conversation with Milli — the widget gets a chat surface, the server gets a `say_to_milli` tool that calls an LLM with Milli's brief.
- Tool calls for `give_item` / `receive_item` (the wildflower → recipe-card exchange).
- An `end_conversation` tool that writes a memory entry.

Day 2's gate is the inverse of Day 1's: did the conversation feel like Milli specifically, not a generic NPC? The plan (in `../DOORWAY_POC_PLAN.md`) goes deeper.
