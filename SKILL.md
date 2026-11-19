---
name: notebooklm-cli
description: Query NotebookLM notebooks via nlm_v3.py. 3-5s chat, 79 commands, per-notebook (-n) plumbing, selftest/surface/batch for agents.
version: 8.0.0
tags: [notebooklm, knowledge-extraction, agent-native, cli]
platforms: [linux, wsl]
---

# NotebookLM CLI (Agent-Native v8)

Token-efficient CLI for Google NotebookLM (Gemini notebook). Pure HTTP API via `notebooklm-py` 0.8.6 — no browser, 3-5s latency, 12 capability groups + 7 passthrough groups.

**v8 headline:** upstream bumped 0.8.1 → 0.8.6 (verified against the 0.8.6 CLI help). New: `nb copy`, `src search`, `research discover`, `src add-book` / `books` / `add-async` / `append` / `copy`, `art copy` / `choices`, `usage`, `src add --fallback-fetch`, `art generate --later` (audio, video, cinematic-video, slide-deck, report, flashcards, infographic, quiz; `--later` + `--wait` rejected; data-table / mind-map have no `--later`). Interactive sites (Nov 16 2026) are chat-triggered only — see below; there is no `site` generate type in 0.8.6.

**v7 headline fix:** `-n/--notebook` used to be accepted and IGNORED by most commands, so requests silently answered about the DEFAULT notebook. Every notebook-scoped command now forwards it (verified live). `status` is the one exception — upstream has no `--notebook` there.

**Agent entry points:** `selftest` (read-only 8-step readiness battery), `surface` (machine-readable command map, ~250 tokens), `batch` (several commands, one process), `doctor` (parsed session health).

**Script:** `nlm_v3.py` (this repo) — agent-native wrapper with structured JSON output.
**Backend:** `notebooklm-py` (pip package) — reverse-engineered HTTP API client.

## Setup

```bash
pipx install notebooklm-py
pipx inject notebooklm-py rookie-cookies
notebooklm login --browser-cookies auto --account EMAIL   # cookie auth (no OAuth)
# OR
python3 nlm_v3.py auth init --account EMAIL
```

## Invocation

```bash
# Shorthand — ask current notebook
nlm_v3.py "Your question here"

# Explicit ask (multi-turn, conversation persists)
nlm_v3.py ask -p "Plain text answer"            # Strip markdown
nlm_v3.py ask -n NOTEBOOK_ID "Question"          # Specific notebook

# All groups use subcommand syntax
nlm_v3.py <group> <action> [args...]
```

## Capability Groups

| Group | Alias | Commands |
|-------|-------|----------|
| notebook | nb | list, create, copy, rename, delete, use, status, summary, metadata |
| ask | (shorthand) | question, -p, -n, --new |
| prompts | prompt | AI-suggested prompts (--mode 1-10, --query) |
| source | src, ls | list, search, add, add-drive, add-drive-file, add-book, books, add-async, append, copy, guide, fulltext, get, delete, delete-by-title, clean, add-research, refresh, rename, stale, wait |
| research | — | status, discover, wait, cancel, import |
| artifact | art | list, generate, download, suggestions, get, delete, export, copy, choices, get-prompt, poll, rename, retry, wait |
| note | notes (list) | list, create, get, save, rename, delete |
| share | — | status, public, add, remove, view-level, update |
| history | — | --limit, --save, --show-all |
| configure | — | --mode, --persona, --response-length |
| auth | — | init, doctor, status |
| usage | — | [--categories] |
| clear | — | (reset conversation) |

**Passthrough groups** (forwarded to upstream): `label`, `collection`, `profile`,
`language`, `agent`, `skill`, `mcp`.

### Artifact Types
audio, video, cinematic-video, slide-deck, infographic, mind-map,
data-table, quiz, flashcards, report

### Download Formats
pdf, pptx (slide-deck); pdf, pptx, csv, json, markdown (others)

## Output Format

All commands return JSON with `"s":"ok"` or `"s":"err"`.
Large answers (>3000 chars) are saved to disk with a file pointer.

```json
{"s": "ok", "f": "answer text with [1][2] citations"}
{"s": "ok", "f": "/path/to/file.txt", "n": 5234}
{"s": "err", "e": "error message"}
```

## Pitfalls

- **Auth cookies go server-side-stale within ~2 weeks** (PSID/PSIDTS tokens). Check `nlm_v3.py auth status` (or bare `auth`) and re-run `nlm_v3.py auth init --account EMAIL` when uploads fail with `SourceProcessingError`.
- **`generate` takes a positional description** for all types EXCEPT `mind-map`,
  which uses `--instructions` + `--kind [interactive|note-backed]`. `--wait` is
  only valid on non-mind-map types.
- **`art generate --later`** queues audio, video, cinematic-video, slide-deck,
  report, flashcards, infographic, quiz for later (returns `scheduled`);
  `--later` + `--wait` is rejected; data-table / mind-map have no `--later`.
- **Interactive sites (Nov 16 2026) are chat-triggered, not a generate type:**
  `ask "make me a site …"`; `gen site` fails with that guidance. A site lists
  via `art list` as type `File`, status `completed`, with **no API URL** — open
  it from the web Studio panel. Keep `NOTEBOOKLM_TRANSPORT=curl_cffi`: without
  it, upstream 0.8.6 `artifact list`/`get` crash (`Invalid port: ':1]'`) on a
  notebook containing a site artifact (live-verified 2026-11-19).
- **`note create` now returns a real `id`** (fixed in notebooklm-py 0.8.1 — the
  old "id: null" bug is gone).
- **Delete/remove commands need `-y` in JSON mode** (upstream). The wrapper
  passes it automatically for note/artifact/source delete + share remove.
- **`clear` doesn't accept `--notebook`.** Use current context.
- **Source `fulltext` for image PDFs returns image URLs, not text.** Use AI chat for synthesis.
- **Partial ID matching works everywhere.**
- **Conversation rate limit ~12 comprehensive turns.** Use `clear` to reset.
