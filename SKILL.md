---
name: notebooklm-cli
description: Query NotebookLM notebooks via nlm.py. 3-5s chat, 39 commands across 7 groups.
version: 4.0.0
tags: [notebooklm, knowledge-extraction, agent-native, cli]
platforms: [linux, wsl]
---

# NotebookLM CLI (Agent-Native v4)

Token-efficient CLI for Google NotebookLM (Gemini notebook). Pure HTTP API via `notebooklm-py` — no browser, 3-5s latency, 39 commands across 7 capability groups.

**Script:** `nlm_v3.py` (this repo) — agent-native wrapper with structured JSON output.
**Backend:** `notebooklm-py` (pip package) — reverse-engineered HTTP API client.

## Setup

```bash
pip install notebooklm-py browser_cookie3
notebooklm login                    # Interactive browser login
# OR
python3 nlm_v3.py auth init         # Extract cookies from existing browser session
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
| ask | (shorthand) | question, -p, -n |
| source | src, ls | list, add, guide, fulltext, get, delete, clean, add-research |
| research | — | status, wait |
| artifact | art | list, generate, download, suggestions, get, delete |
| note | notes (list) | list, create, get, save, rename, delete |
| share | — | status, public, add, remove, view-level |
| history | — | --limit, --save, --show-all |
| configure | — | --mode, --persona, --response-length |
| auth | — | init, doctor |
| clear | — | (reset conversation) |

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

- **Auth cookies expire ~30 days.** Re-run `nlm_v3.py auth init`.
- **`note create` JSON has `id: null`** (upstream v0.7.3 bug). Note IS created — list notes for real ID.
- **`clear` doesn't accept `--notebook`.** Use current context.
- **Source `fulltext` for image PDFs returns image URLs, not text.** Use AI chat for synthesis.
- **`generate` takes `--instructions`, not positional prompt.**
- **Partial ID matching works everywhere.**
- **Conversation rate limit ~12 comprehensive turns.**
