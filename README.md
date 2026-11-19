# Hermes NotebookLM — AI Agent Tools

Token-efficient CLI tools for AI agents to interact with Google NotebookLM
(aka **Gemini notebook**). **v8: Pure HTTP API via notebooklm-py 0.8.6. 79 commands across 12 groups + 7 passthrough groups.**

## Quick Start

```bash
# Install (pipx keeps notebooklm-py in an isolated venv)
pipx install notebooklm-py
pipx inject notebooklm-py rookie-cookies      # cookie auth (browser-cookie extraction)

# Auth (one-time) — reads cookies from a signed-in browser (no interactive OAuth)
notebooklm login --browser-cookies auto --account you@gmail.com
# OR via the wrapper (same thing):
python3 nlm_v3.py auth init --account you@gmail.com

# Use
python3 nlm_v3.py nb list                           # List notebooks
python3 nlm_v3.py nb use YOUR_NOTEBOOK_ID            # Set active notebook
python3 nlm_v3.py "What is in this notebook?"        # Ask a question
```

## Command Groups

| Group | Alias | Commands |
|-------|-------|----------|
| `notebook` | `nb` | list, create, copy, rename, delete, use, status, summary, metadata |
| `ask` | (shorthand) | question, -p, -n, --new |
| `prompts` | `prompt` | AI-suggested prompts (--mode 1-10, --query) |
| `source` | `src`, `ls` | list, search, add, add-drive, add-drive-file, add-book, books, add-async, append, copy, guide, fulltext, get, delete, delete-by-title, clean, add-research, refresh, rename, stale, wait |
| `research` | — | status, discover, wait, cancel, import |
| `artifact` | `art` | list, generate, download, suggestions, get, delete, export, copy, choices, get-prompt, poll, rename, retry, wait |
| `note` | `notes` (list) | list, create, get, save, rename, delete |
| `share` | — | status, public, add, remove, view-level, update |
| `history` | — | --limit, --save, --show-all |
| `configure` | — | --mode, --persona, --response-length |
| `auth` | — | init, doctor, status |
| `usage` | — | [--categories] (live compute usage) |
| `clear` | — | (reset conversation) |

**Passthrough groups** (forwarded straight to upstream `notebooklm`): `label`,
`collection`, `profile`, `language`, `agent`, `skill`, `mcp`.

### Artifact Types
`audio`, `video`, `cinematic-video`, `slide-deck`, `infographic`, `mind-map`,
`data-table`, `quiz`, `flashcards`, `report`

### Download Formats
`pdf`, `pptx` (slide-deck); `pdf`, `pptx`, `csv`, `json`, `markdown` (others)

## Output Format

All commands return JSON with `"s":"ok"` or `"s":"err"`.
Large answers (>3000 chars) saved to disk with file pointer.

```json
{"s": "ok", "f": "answer text with [1][2] citations"}
{"s": "ok", "f": "/path/to/file.txt", "n": 5234}
{"s": "err", "e": "error message"}
```

## Examples

```bash
# Notebook management
nlm_v3.py nb list                                    # {"s":"ok","notebooks":[...],"n":15}
nlm_v3.py nb create "My Research"                   # {"s":"ok","id":"abc123...","title":"My Research"}
nlm_v3.py nb summary                                 # AI synthesis of all sources

# Chat (multi-turn, 3-5s)
nlm_v3.py "What are the key findings?"               # Shorthand for ask
nlm_v3.py ask -p "Summarize in plain text"           # Strip markdown
nlm_v3.py ask -n OTHER_ID "Question"                 # Ask different notebook

# Source management
nlm_v3.py src list                                   # {"s":"ok","sources":[...],"n":20}
nlm_v3.py src guide abc123                           # AI summary + keywords
nlm_v3.py src add "https://..."                      # Add URL source
nlm_v3.py src add --type text "Some pasted content"  # Add text source
nlm_v3.py src add-research "MASH treatments 2026"    # Web search → import
nlm_v3.py src add-research --mode deep --from web --no-wait "Q"

# Artifacts (generate takes a positional description, except mind-map)
nlm_v3.py art list                                   # Generated artifacts
nlm_v3.py gen slide-deck "Key points" --wait         # Generate slide deck
nlm_v3.py gen mind-map --instructions "Drug classes" # mind-map uses --instructions
nlm_v3.py gen report "White paper" --format briefing-doc --wait
nlm_v3.py dl slide-deck -a abc123 --format pdf       # Download as PDF
nlm_v3.py art wait                                   # Wait for pending artifact

# Notes
nlm_v3.py note create -t "Summary" "Content here"    # Create
nlm_v3.py notes                                      # List all
nlm_v3.py note get abc123                            # Read full content

# Sharing
nlm_v3.py share status                               # {"s":"ok","public":true,"users":[...]}
nlm_v3.py share public enable                        # Make public
nlm_v3.py share add user@example.com                 # Share with viewer

# History
nlm_v3.py history --limit 5                          # Last 5 Q&A turns
nlm_v3.py history --save                             # Save as note

# New groups
nlm_v3.py label list                                 # Source labels
nlm_v3.py collection list                            # Account-level notebook groups
nlm_v3.py prompts --mode 4                           # AI-suggested chat questions
```

## Architecture

```
AI Agent → nlm_v3.py (CLI wrapper) → notebooklm (notebooklm-py) → Google NotebookLM API
```

- **nlm_v3.py**: Agent-native subcommand wrapper (~1900 lines). Token-efficient JSON output, file pointers for large responses, partial ID matching, comprehensive error handling, and a generic passthrough for the newest upstream groups.
- **notebooklm**: Upstream `notebooklm-py` CLI. Raw table output, interactive prompts. Use directly for exploratory work; use nlm_v3.py for agent automation.

## Dependencies

- `notebooklm-py` >= 0.8.6 — handles the batchexecute/RPC API internally
- `rookie-cookies` — browser cookie extraction (used by `notebooklm login --browser-cookies`)
- Firefox or Chrome signed into notebook.google.com

## Interactive sites (Gemini Notebook, Nov 16 2026)

Google launched interactive websites on Nov 16 2026: type **"make me a site"**
in a notebook's chat and describe it — visual explainers (interactive periodic
table, timeline), dashboards (quarterly sales), or project trackers. Web only,
18+, rolling out globally (up to 15 days from Nov 16); mobile coming soon.

There is **no typed artifact for it in notebooklm-py 0.8.6** (no `site` /
`canvas` generate type; upstream issue #1609 tracks the Canvas variant-5
groundwork). So this wrapper does not invent one:

```bash
nlm_v3.py ask -n <notebook> "make me a site: an interactive timeline of ..."  # trigger
nlm_v3.py art list -n <notebook>   # the site lists as type `File`, status `completed`, with no API URL
nlm_v3.py gen site "..."           # fails with the ask-trigger guidance above
```

Sharing a site by link requires viewers to have access to the **full notebook**;
public sharing needs a consumer Google account.

## v8 changes (2026-11-19)

Live-verified against upstream `notebooklm-py` 0.8.6 CLI help (not just the
changelog):

- Pinned upstream 0.8.1 → 0.8.6; `rookiepy` → `rookie-cookies`.
- New: `nb copy`, `src search`, `research discover`, `src add-book` /
  `books` / `add-async` / `append` / `copy`, `art copy` / `choices`, `usage`.
- `src add --fallback-fetch` / `--cleanup-on-failure` (0.8.4).
- `art generate --later` for audio, video, cinematic-video, slide-deck,
  report, flashcards, infographic, quiz (0.8.6 deferred generation; returns
  status `scheduled`; `--later` + `--wait` rejected; data-table / mind-map
  have no `--later` in 0.8.6).
- Interactive sites documented as chat-triggered (above); no invented type.
- Rename: upstream ADR-0028 defers the `gemini-notebook-py` dist/repo flip
  to a single 0.9.0 release; `import notebooklm`, `NOTEBOOKLM_*` env vars
  and the `notebooklm` CLI name are permanent — no rename action taken.

## v7 changes (2026-09-20)

Live testing found that most commands accepted `-n/--notebook` and then **ignored
it**, so a request for one notebook silently answered about the *default* notebook.
That is worse than an error: `share status -n X` reported X's sharing as if it were
the default notebook's, and `artifact download` never passed a notebook at all.
Every notebook-scoped command now parses and forwards `-n`, in any position.

Also in v7:

- `doctor [--fix]`, `selftest`, `surface`, `batch` (see below)
- `status` / `doctor` / `configure` / share+note+source mutations return parsed
  fields instead of a rendered table or a raw JSON string
- filters exposed: `source list --label/--status/--limit`,
  `artifact list --type/--limit`, `prompts -s/--source`, `--no-truncate`
- artifact types `fantasy-map`, `file`; `generate revise-slide`
- multi-account: `--profile NAME` (or `NOTEBOOKLM_PROFILE`), plus
  `auth check/inspect/logout/refresh/import-cookies`
- `NOTEBOOKLM_CLI` env / PATH lookup for the upstream binary, and
  `NOTEBOOKLM_TRANSPORT=curl_cffi` pinned (Google rejects some transports)

### Readiness + discovery commands

```
nlm.py selftest          # read-only battery: auth, list, status, sources, artifacts,
                         # notes, share, doctor → {"passed":8,"total":8,"healthy":true}
nlm.py surface           # machine-readable command map (~250 tokens) for agent discovery
nlm.py batch "nb list" "src list -n <id>" "history -l 3"
                         # several commands in ONE process → one JSON document
nlm.py doctor            # session/profile health, parsed (warn != failure)
```

`selftest` is the cheap gate to run before a pipeline depends on this tool; it
touches nothing destructive.

## Pitfalls

- **Auth cookies go server-side-stale within ~2 weeks** (the PSID/PSIDTS session tokens are invalidated by Google regardless of their ~365-day nominal `expires`). When uploads start failing with `SourceProcessingError`, check `nlm_v3.py auth status` (or bare `auth`) and re-run `nlm_v3.py auth init --account EMAIL` / `notebooklm login --browser-cookies auto --account EMAIL`. The `source add --type file` path auto-detects a stale-session failure and falls back to pasted-text, telling you to re-login.
- **Interactive sites are `File` artifacts with no API URL.** `art list` shows
  the generated site as type `File`, status `completed`, with no download URL
  — open it from the web Studio panel. And **do not drop the
  `NOTEBOOKLM_TRANSPORT=curl_cffi` pin**: with the default transport, upstream
  0.8.6 `artifact list` / `artifact get` crash with `Invalid port: ':1]'` on
  a notebook that contains a site artifact (live-verified 2026-11-19); with
  curl_cffi they work. This wrapper always pins it.
- **`generate` takes a positional description** for every type except `mind-map`, which takes `--instructions` and `--kind [interactive|note-backed]`. `--wait` is only valid on non-mind-map types.
- **Delete/remove commands need `-y` in JSON mode** (upstream). The wrapper passes it automatically.
- **`clear` doesn't accept `--notebook`** — it operates on current context.
- **Source `fulltext` for image-based PDFs returns Google image URLs, not extracted text.** Use AI chat for distilled knowledge.
- **Conversation rate limit ~12 comprehensive turns.** Start a fresh conversation with `nlm.py clear`.
- **Partial ID matching works everywhere** — `abc` matches `abc123...`.
- `notebooklm-py` API was not affected by Google's July 2026 NotebookLM → Gemini Notebook rebrand (wire protocol unchanged; old notebooklm.google.com redirects to notebook.google.com).

- **`-n/--notebook` is honoured everywhere now, but `status` is the exception** — upstream `status` has no `--notebook` option (it reports the current context), so `nlm.py nb status -n X` echoes the requested id without forwarding it. Use `nb metadata -n X` or `src list -n X` when you need facts about a specific notebook.

- **`--profile NAME` is global** — it is applied before the subcommand, so it works with every command (`nlm.py --profile work nb list`). Set `NOTEBOOKLM_PROFILE` to make it the default for a shell.

## Interop & UI automation

Two things to know if you reuse the auth state outside the CLI:

- **`storage_state.json` has millisecond `expires` timestamps** (upstream `notebooklm-py`
  bug — rookie-cookies returns ms, `_cookie_persistence.py` stores it verbatim). ~76/108
  cookies carry 13-digit values. Playwright rejects these ("Cookie should have a valid
  expires"). The CLI is unaffected (it reads the field itself); it only breaks direct
  Playwright reuse. Workaround: for any `expires > 253402300799` (year 9999 in seconds),
  divide by 1000.

- **Cookie injection does NOT authenticate a fresh browser.** Google binds session
  cookies to the originating browser's TLS state, so loading `storage_state.json` into
  a new Playwright context shows "Signed out" even with valid-looking cookies. For
  authenticated UI automation of `notebook.google.com`, use a **live signed-in CDP
  browser** (e.g. a Chrome instance with `--remote-debugging-port`), or run
  `notebooklm login` (interactive) which persists its own browser session. The CLI/HTTP
  path (this repo) does not need a browser at all.

## Files

| File | Purpose |
|------|---------|
| `nlm_v3.py` | Agent-native CLI wrapper (v7, ~1750 lines) |
| `tests/test_nlm_v3.py` | Offline unit tests (upstream CLI faked) — `python3 -m pytest tests/ -q` |
| `nlm_v2.py` | v2 page-server client (HTTP POST, fallback) |
| `nlm_v2_server.py` | v2 Chromium daemon (Playwright, fallback) |
| `README.md` | This file |
| `SKILL.md` | Hermes agent skill definition |

## Upstream

Uses [notebooklm-py](https://github.com/teng-lin/notebooklm-py) for the HTTP API layer.
This repo provides the agent-native wrapper with token-efficient output, 11 capability groups + 7 passthrough groups, and structured JSON responses.
