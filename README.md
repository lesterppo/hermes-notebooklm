# Hermes NotebookLM — AI Agent Tools

Token-efficient CLI tools for AI agents to interact with Google NotebookLM
(aka **Gemini notebook**). **v4: Pure HTTP API via notebooklm-py. 3-5s latency. 39 commands across 7 groups.**

## Quick Start

```bash
# Install
pip install notebooklm-py browser_cookie3

# Auth (one-time)
notebooklm login
# OR: python3 nlm_v3.py auth init

# Use
python3 nlm_v3.py nb list                           # List notebooks
python3 nlm_v3.py nb use YOUR_NOTEBOOK_ID            # Set active notebook
python3 nlm_v3.py "What is in this notebook?"        # Ask a question
```

## Command Groups

| Group | Alias | Commands |
|-------|-------|----------|
| `notebook` | `nb` | list, create, rename, delete, use, status, summary, metadata |
| `ask` | (shorthand) | question, -p, -n |
| `source` | `src`, `ls` | list, add, guide, fulltext, get, delete, clean, add-research |
| `research` | — | status, wait |
| `artifact` | `art` | list, generate, download, suggestions, get, delete |
| `note` | `notes` (list) | list, create, get, save, rename, delete |
| `share` | — | status, public, add, remove, view-level |
| `history` | — | --limit, --save, --show-all |
| `configure` | — | --mode, --persona, --response-length |
| `auth` | — | init, doctor |
| `clear` | — | (reset conversation) |

### Artifact Types
`audio`, `video`, `cinematic-video`, `slide-deck`, `infographic`, `mind-map`,
`data-table`, `quiz`, `flashcards`, `report`

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
nlm_v3.py src add-research "MASH treatments 2026"    # Web search → import
nlm_v3.py src add-research --mode deep --no-wait "Q" # Deep research

# Artifacts
nlm_v3.py art list                                   # Generated artifacts
nlm_v3.py gen slide-deck --instructions "Key points" # Generate slide deck
nlm_v3.py dl slide-deck -a abc123 --format pdf       # Download as PDF
nlm_v3.py gen mind-map --instructions "Drug classes" # Generate mind map
nlm_v3.py gen audio --instructions "Deep dive"       # Generate podcast

# Notes
nlm_v3.py note create -t "Summary" "Content here"    # Create
nlm_v3.py notes                                      # List all
nlm_v3.py note get abc123                            # Read full content

# Sharing
nlm_v3.py share status                               # {"s":"ok","public":false,"users":[...]}
nlm_v3.py share public enable                        # Make public
nlm_v3.py share add user@example.com                 # Share with viewer

# History
nlm_v3.py history --limit 5                          # Last 5 Q&A turns
nlm_v3.py history --save                             # Save as note
```

## Architecture

```
AI Agent → nlm_v3.py (CLI wrapper) → notebooklm (notebooklm-py) → Google NotebookLM API
```

- **nlm_v3.py**: Agent-native subcommand wrapper (~930 lines). Token-efficient JSON output, file pointers for large responses, partial ID matching, comprehensive error handling.
- **notebooklm**: Upstream `notebooklm-py` CLI. Raw table output, interactive prompts. Use directly for exploratory work; use nlm_v3.py for agent automation.

## Dependencies

- `notebooklm-py` >= 0.7.3 — handles batchexecute API internally
- `browser_cookie3` — for cookie extraction (auth init only)
- Firefox or Chrome signed into notebooklm.google.com

## Pitfalls

- Auth cookies expire ~30 days. Re-run `nlm_v3.py auth init` or `notebooklm login`.
- `note create` JSON response has `id: null` (upstream bug in notebooklm-py v0.7.3). The note IS created — list notes to get the real ID.
- `clear` doesn't accept `--notebook` — it operates on current context.
- Source `fulltext` for image-based PDFs returns Google image URLs, not extracted text. Use AI chat for distilled knowledge.
- `generate` subcommands take `--instructions`, NOT positional prompt.
- Partial ID matching works everywhere — `abc` matches `abc123...`.
- `notebooklm-py` API was not affected by Google's May 2025 NotebookLM → Gemini notebook rebrand.

## Files

| File | Purpose |
|------|---------|
| `nlm_v3.py` | Agent-native CLI wrapper (v4, ~930 lines) |
| `nlm_v2.py` | v2 page-server client (HTTP POST, fallback) |
| `nlm_v2_server.py` | v2 Chromium daemon (Playwright, fallback) |
| `README.md` | This file |
| `SKILL.md` | Hermes agent skill definition |

## Upstream

Uses [notebooklm-py](https://github.com/teng-lin/notebooklm-py) for the HTTP API layer.
This repo provides the agent-native wrapper with token-efficient output, 7 capability groups, and structured JSON responses.
