---
name: notebooklm-cli
description: Query NotebookLM (Gemini notebook rebrand) via notebooklm-py. 3-5s latency, multi-turn, inline citations. Use for knowledge extraction from uploaded sources.
version: 3.2.0
---

# NotebookLM CLI (Agent-Native)

Query Google NotebookLM notebooks programmatically. Pure HTTP API (no browser),
3-5s latency, multi-turn conversations with inline citations.

> Note: Google rebranded NotebookLM as **Gemini notebook**. The product URL
> (`notebooklm.google.com`) and API are unchanged, so this tool works as-is.

## Setup (one-time)

```bash
pip install --break-system-packages notebooklm-py
python3 nlm_v3.py --init    # extract browser cookies → auth storage
python3 nlm_v3.py -s NOTEBOOK_ID   # set default notebook
```

`--init` extracts Google auth cookies from your browser (Firefox or Chrome).
You must be signed into notebooklm.google.com in that browser first.

## Invocation

```bash
# Ask question (JSON output):
echo "question" | python3 nlm_v3.py

# Plain text (no markdown formatting):
echo "question" | python3 nlm_v3.py -p

# Raw text output (no JSON wrapper):
echo "question" | python3 nlm_v3.py -r

# Argument mode:
python3 nlm_v3.py "question"
```

## Output Format

```json
{"f": "answer text with [1][2] inline citations", "s": "done"}
{"e": "error message", "s": "err"}
```

Always check `s` field: `"done"` = success, `"err"` = check `e`.

## Commands

| Flag | Action |
|------|--------|
| (stdin/arg) | Ask notebook (multi-turn, conversation persists) |
| `-p` | Strip markdown from answer |
| `-r` | Raw text output (no JSON wrapper) |
| `-l` | List all notebooks |
| `-s ID` | Set default notebook ID |
| `--new` | Start a fresh conversation (discard current thread) |
| `--clear` | Clear the current conversation thread |
| `--src` | List sources in current notebook |
| `--src ID` | Get source full text by ID |
| `--guide ID` | Get AI source guide by ID |
| `--summary` | AI-generated notebook summary (+ `--topics`) |
| `--metadata` | Notebook metadata + sources list |
| `--history` | Conversation history (or `--save` as note) |
| `--note TEXT` | Create a note (`-t TITLE` for title) |
| `--note-list` | List notes in current notebook |
| `--artifact` | List generated Studio artifacts |
| `--gen TYPE [ARGS]` | Generate Studio artifact; forwards ARGS to `notebooklm generate TYPE` (e.g. `--gen report "topic"`, `--gen mind-map --instructions "topic"`) |
| `--src-add URL/TEXT` | Add a source (URL, file path, or inline text) |
| `--src-del ID` | Delete a source by ID |
| `--src-clean` | Auto-remove duplicate/error/stale sources |
| `--share` | Show notebook sharing status |
| `--research` | Show Deep Research status for current notebook |
| `--init` | Refresh auth from browser cookies |

## Multi-Turn

Conversations persist across calls automatically. Each `ask` continues the
same thread. Use `--new` to start a fresh conversation.

## Dependencies

- `notebooklm-py` — handles batchexecute API internally (verified 0.7.2/0.7.3
  against the Gemini-notebook rebrand; both target `notebooklm.google.com`)
- `browser_cookie3` — for cookie extraction (--init only)
- Firefox or Chrome signed into notebooklm.google.com

## Pitfalls

- Auth cookies expire ~30 days. Re-run `--init`.
- Citations reference source numbers, not page numbers.
- Plain mode (-p) strips `**bold**` and `__italic__` but not all markdown.
- First query after --init may need `notebooklm use <id>` once.
