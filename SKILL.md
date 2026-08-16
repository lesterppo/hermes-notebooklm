---
name: notebooklm-cli
description: Query NotebookLM notebooks via nlm.py. 3-5s chat, 60+ commands across 11 groups.
version: 5.0.0
tags: [notebooklm, knowledge-extraction, agent-native, cli]
platforms: [linux, wsl]
---

# NotebookLM CLI (Agent-Native v5)

Token-efficient CLI for Google NotebookLM (Gemini notebook). Pure HTTP API via `notebooklm-py` 0.8.1 — no browser, 3-5s latency, 60+ commands across 11 capability groups plus 7 passthrough groups.

**Script:** `nlm_v3.py` (this repo) — agent-native wrapper with structured JSON output.
**Backend:** `notebooklm-py` (pip package) — reverse-engineered HTTP API client.

## Setup

```bash
pipx install notebooklm-py
pipx inject notebooklm-py rookiepy
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
| notebook | nb | list, create, rename, delete, use, status, summary, metadata |
| ask | (shorthand) | question, -p, -n, --new |
| prompts | prompt | AI-suggested prompts (--mode 1-10, --query) |
| source | src, ls | list, add, add-drive, add-drive-file, guide, fulltext, get, delete, delete-by-title, clean, add-research, refresh, rename, stale, wait |
| research | — | status, wait, cancel, import |
| artifact | art | list, generate, download, suggestions, get, delete, export, get-prompt, poll, rename, retry, wait |
| note | notes (list) | list, create, get, save, rename, delete |
| share | — | status, public, add, remove, view-level, update |
| history | — | --limit, --save, --show-all |
| configure | — | --mode, --persona, --response-length |
| auth | — | init, doctor, status |
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
  only valid on non-mind-map types. (The old "`--instructions` for all types"
  behavior changed in notebooklm-py 0.8.1.)
- **`note create` now returns a real `id`** (fixed in notebooklm-py 0.8.1 — the
  old "id: null" bug is gone).
- **Delete/remove commands need `-y` in JSON mode** (upstream). The wrapper
  passes it automatically for note/artifact/source delete + share remove.
- **`clear` doesn't accept `--notebook`.** Use current context.
- **Source `fulltext` for image PDFs returns image URLs, not text.** Use AI chat for synthesis.
- **Partial ID matching works everywhere.**
- **Conversation rate limit ~12 comprehensive turns.** Use `clear` to reset.
