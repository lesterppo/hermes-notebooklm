#!/usr/bin/env python3
"""
NotebookLM agent-native CLI — comprehensive wrapper around notebooklm-py.

Groups: notebook, ask, source, research, artifact, note, share, history,
configure, auth, clear, prompts, plus passthrough for label/collection/
profile/language/agent/skill/mcp.

Output: {"s":"ok",...} | {"s":"err","e":"..."}
Large outputs (>3000 chars) saved to ~/.hermes/nlm_output/ with file pointer.

v5 changelog (notebooklm-py 0.8.1):
  * Fixed JSON key unwrapping: `source get` / `source add` / `create` return
    data nested under a `"source"` / `"notebook"` key (was reading top-level).
  * Fixed `generate`: description is now POSITIONAL (upstream dropped
    `--instructions`); `--kind` removed.
  * Fixed `note save`: content now passed via `--content` (was positional).
  * Fixed `share status`: map `is_public`/`share_url`/`shared_users`.
  * Fixed `history`: parse `qa_pairs` (was `turns`).
  * Fixed `note list`: read `preview` key (was `content`).
  * Fixed `nb metadata`: cross-reference `source list` to attach source IDs.
  * Fixed `ask`: convert LaTeX tokens (\ge, \le, ...) to Unicode.
  * Added missing upstream subcommands (source add-drive/add-drive-file/
    delete-by-title/refresh/rename/stale/wait, artifact export/get-prompt/
    poll/rename/retry/wait, research cancel/import, share update) and
    generic passthrough for label/collection/profile/language/agent/skill/mcp.
  * `auth init` now prefers upstream `login --browser-cookies` (rookiepy).

v6 (2026-08-16):
  * `source add --type file` now detects a stale-session upload failure
    (source lands 'error' after a clean upload) and falls back to extracting
    the text as a pasted-text source, telling the user to re-login. Root cause
    of the underlying failure is stale Google cookies, not a server-side bug.
  * Added `auth status` (bare `auth` defaults to it): surfaces nominal cookie
    expiry + session-age staleness + a live RPC check, classifying
    healthy/expiring/expired/at-risk/broken with a re-login recommendation.

v7 (2026-09-20):
  * FIX: `-n/--notebook` was accepted but IGNORED by most commands (source,
    artifact, note, share, research, configure, status), so a request for one
    notebook silently answered about the DEFAULT notebook — producing wrong
    answers and, for `share status`, a wrong public-link report. Every command
    now parses and forwards it.
  * FIX: `artifact download` never passed a notebook at all.
  * Added `_split_nb()` so commands accept `-n <id>` in any position.
  * `status`/`doctor` now use upstream `--json` and return parsed fields
    instead of a rendered table / raw JSON string.
  * Parsed the leftover raw blobs (share public/view-level, note save/rename/
    delete, source delete, configure, clear).
  * New filters: `source list --label/--status/--limit`, `artifact list
    --type/--limit`, `prompts --source`.
  * New artifact types `fantasy-map` and `file`; new passthrough
    `generate revise-slide`.
  * Multi-account: `--profile NAME` (or NOTEBOOKLM_PROFILE) is applied as the
    upstream global profile flag, and `auth check/inspect/logout/refresh/
    import-cookies` now pass through.
  * `NOTEBOOKLM_CLI` env / PATH lookup for the upstream binary (CI-safe),
    `NOTEBOOKLM_TRANSPORT=curl_cffi` pinned (Google rejects some transports).
"""
import sys, os, json, subprocess, pathlib, re, time
import shutil

HOME = pathlib.Path.home()


def _find_nlm() -> str:
    """Locate the upstream CLI: NOTEBOOKLM_CLI > PATH > ~/.local/bin."""
    env = os.environ.get("NOTEBOOKLM_CLI")
    if env and os.path.exists(env):
        return env
    found = shutil.which("notebooklm")
    if found:
        return found
    return str(HOME / ".local" / "bin" / "notebooklm")


NLM = _find_nlm()
CFG_DIR = HOME / ".hermes" / "nlm_cache"
CFG_DIR.mkdir(parents=True, exist_ok=True)
NB_FILE = CFG_DIR / "notebook.txt"
OUT_DIR = HOME / ".hermes" / "nlm_output"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STORAGE = HOME / ".notebooklm" / "profiles" / "default" / "storage_state.json"

# Upstream account profile (multi-account). Overridable per-run with --profile,
# which main() strips from argv before dispatch.
PROFILE = os.environ.get("NOTEBOOKLM_PROFILE", "")

# ── helpers ──────────────────────────────────────────────────

def _run(args, timeout=90):
    """Run notebooklm CLI, return (stdout, stderr, returncode)."""
    cmd = [NLM, "--quiet"]
    # Profile is a GLOBAL upstream flag, so it has to precede the subcommand.
    if PROFILE:
        cmd += ["-p", PROFILE]
    cmd += args
    try:
        r = subprocess.run(cmd,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1",
                 "NOTEBOOKLM_TRANSPORT": os.environ.get("NOTEBOOKLM_TRANSPORT", "curl_cffi")})
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout after {}s".format(timeout), 124
    except FileNotFoundError:
        return "", "notebooklm binary not found at {} (set NOTEBOOKLM_CLI)".format(NLM), 127

def _ok(**kw):
    d = {"s": "ok"}
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)

def _err(msg):
    return json.dumps({"s": "err", "e": str(msg)[:500]}, ensure_ascii=False)

def _maybe_file(text, prefix="nlm"):
    """If text > 3000 chars, save to disk and return pointer."""
    if len(text) <= 3000:
        return text
    ts = int(time.time())
    fpath = OUT_DIR / "{}_{}.txt".format(prefix, ts)
    fpath.write_text(text)
    return str(fpath)

def _default_nb():
    env = os.environ.get("NOTEBOOKLM_NOTEBOOK", "")
    if env:
        return env
    if NB_FILE.exists():
        return NB_FILE.read_text().strip()
    return ""

def _nb_args(nb):
    nid = nb or _default_nb()
    return ["--notebook", nid] if nid else []

def _split_nb(args, keys=("-n", "--notebook")):
    """Pull `-n/--notebook <id>` out of an argument list, wherever it sits.

    Returns (notebook_or_None, remaining_args). Every notebook-scoped command
    goes through this: silently ignoring -n used to answer about the DEFAULT
    notebook, which is worse than erroring because the output looks valid.
    """
    nb = None
    rest = []
    i = 0
    while i < len(args):
        if args[i] in keys:
            if i + 1 < len(args):
                nb = args[i + 1]
                i += 2
                continue
            i += 1
            continue
        rest.append(args[i])
        i += 1
    return nb, rest

def _pick(args, *names, **kw):
    """Pop `--name value` (or `-x value`) pairs out of args -> (values, rest)."""
    vals = {}
    rest = []
    i = 0
    while i < len(args):
        if args[i] in names:
            key = args[i]
            if i + 1 < len(args):
                vals[key] = args[i + 1]
                i += 2
                continue
            i += 1
            continue
        rest.append(args[i])
        i += 1
    return vals, rest

def _clean_latex(text):
    """Convert common LaTeX math tokens to Unicode, strip math delimiters."""
    subs = {
        r"\geq": "≥", r"\leq": "≤", r"\ge": "≥", r"\le": "≤",
        r"\times": "×", r"\approx": "≈", r"\pm": "±", r"\mu": "μ",
        r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
        r"\cdot": "·", r"\rightarrow": "→", r"\leftarrow": "←",
        r"\propto": "∝", r"\ne": "≠", r"\equiv": "≡", r"\inf": "∞",
    }
    for k, v in subs.items():
        text = text.replace(k, v)
    text = re.sub(r"\\[()\[\]]", "", text)
    return text

def _answer_filter(out):
    """Strip status lines from notebooklm ask output."""
    skip_prefixes = (
        'resumed conversation:', 'continuing conversation:',
        'conversation:', 'answer:', 'thinking:'
    )
    lines = []
    for l in out.split('\n'):
        if l.lower().startswith(skip_prefixes):
            continue
        lines.append(_clean_latex(l))
    return '\n'.join(lines).strip()

def _json_or_text(out):
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return out

def _unwrap(data, *keys):
    """Descend into nested dict keys (e.g. data["source"]["id"])."""
    cur = data
    for k in keys:
        if isinstance(cur, dict) and isinstance(cur.get(k), dict):
            cur = cur[k]
        else:
            return cur
    return cur

def _parse_list_result(out, key, item_keys, strip_date=True):
    """Parse a notebooklm --json list result. Returns (items_list, count)."""
    data = _json_or_text(out)
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k in (key, "notebooks", "sources", "notes", "artifacts",
                  "qa_pairs", "shared_users", "labels", "collections"):
            if k in data:
                items = data[k]
                break
    count = len(items)
    if count == 0 and isinstance(data, dict):
        count = data.get("count", 0)
    clean = []
    for it in items:
        entry = {}
        for k in item_keys:
            v = it.get(k, "") if isinstance(it, dict) else ""
            if strip_date and k in ("created_at",) and v:
                v = str(v)[:10]
            entry[k] = v
        clean.append(entry)
    return clean, count

def _forward_group(group, action, action_args, timeout=90):
    """Generic forward: notebooklm --quiet <group> <action> --json <args>."""
    cmd = [group, action, "--json"]
    cmd.extend(action_args)
    out, err, rc = _run(cmd, timeout=timeout)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, (dict, list)):
        return _ok(result=data)
    return _ok(raw=out)

# ── notebook group ────────────────────────────────────────────

def cmd_notebook_list(args):
    nb, rest = _split_nb(args)
    cmd = ["list", "--json"]
    if "--limit" in rest:
        i = rest.index("--limit")
        if i + 1 < len(rest):
            cmd += ["--limit", rest[i + 1]]
    out, err, rc = _run(cmd)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "notebooks", ("id", "title", "created_at"))
    return _ok(notebooks=items, n=count)

def cmd_notebook_create(args):
    if not args:
        return _err("usage: nlm.py notebook create <title>")
    out, err, rc = _run(["create", "--json", " ".join(args)])
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        nb = _unwrap(data, "notebook")
        return _ok(id=nb.get("id", ""), title=nb.get("title", ""))
    return _ok(raw=out)

def cmd_notebook_rename(args):
    if len(args) < 2:
        return _err("usage: nlm.py notebook rename <id> <new_title>")
    nid, title = args[0], " ".join(args[1:])
    out, err, rc = _run(["rename", "-n", nid, "--json", title])
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_notebook_delete(args):
    if not args:
        return _err("usage: nlm.py notebook delete <id>")
    out, err, rc = _run(["delete", "-n", args[0], "-y", "--json"])
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def _resolve_nb_id(partial):
    """Expand a partial notebook id to the full one (falls back to the input)."""
    if len(partial) >= 36:
        return partial
    out, err, rc = _run(["list", "--json"], timeout=30)
    data = _json_or_text(out)
    items = data if isinstance(data, list) else (data.get("notebooks", []) if isinstance(data, dict) else [])
    for nb in items:
        if isinstance(nb, dict) and str(nb.get("id", "")).startswith(partial):
            return nb["id"]
    return partial


def cmd_notebook_use(args):
    nb, rest = _split_nb(args)
    if not rest:
        out, err, rc = _run(["status", "--json"] + _nb_args(nb))
        if rc == 0:
            data = _json_or_text(out)
            if isinstance(data, dict):
                return _ok(notebook=data.get("notebook_id") or _default_nb(),
                           cached_default=_default_nb())
        return _ok(notebook=_default_nb())
    nid = rest[0]
    out, err, rc = _run(["use", nid, "--json"])
    if rc == 0:
        full = _resolve_nb_id(nid)
        NB_FILE.write_text(full)
        return _ok(notebook=full, requested=nid)
    return _err(err or out)

def cmd_notebook_status(args):
    # NOTE: upstream `status` has no --notebook option (it reports the current
    # context), so -n is accepted here only to be reported back, never forwarded.
    nb, rest = _split_nb(args)
    out, err, rc = _run(["status", "--json"])
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(notebook_id=data.get("notebook_id") or _default_nb(),
                   title=data.get("notebook_title") or data.get("title") or "",
                   conversation_id=data.get("conversation_id", ""),
                   cached_default=_default_nb(),
                   requested=nb or None,
                   profile=data.get("profile", PROFILE or "default"))
    return _ok(raw=out, cached_default=_default_nb())

def cmd_notebook_summary(args):
    nb, rest = _split_nb(args)
    topics_flag = "--topics" in rest
    nb = nb or (rest[0] if rest else "") or _default_nb()
    cmd = ["summary", "--json"] + _nb_args(nb)
    if topics_flag:
        cmd.append("--topics")
    out, err, rc = _run(cmd, timeout=60)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        text = data.get("summary") or data.get("text") or ""
        res = {"summary": _maybe_file(text, "summary")}
        if data.get("topics"):
            res["topics"] = data["topics"]
        return _ok(**res)
    return _ok(summary=_maybe_file(out, "summary"))

def cmd_notebook_metadata(args):
    nb, rest = _split_nb(args)
    nb = nb or (rest[0] if rest else "") or _default_nb()
    out, err, rc = _run(["metadata", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        # Upstream metadata sources carry title/type/url but NOT id; enrich by
        # cross-referencing `source list` (matches on exact title).
        src_items = []
        raw_sources = data.get("sources", [])
        # Build title -> id map from source list.
        id_map = {}
        sout, serr, src_rc = _run(["source", "list", "--json"] + _nb_args(nb), timeout=30)
        if src_rc == 0:
            sdata = _json_or_text(sout)
            if isinstance(sdata, dict):
                for s in sdata.get("sources", []):
                    if isinstance(s, dict) and s.get("title"):
                        id_map[s["title"]] = s.get("id", "")
        for s in raw_sources:
            if not isinstance(s, dict):
                continue
            title = s.get("title", "")
            src_items.append({
                "id": id_map.get(title, s.get("id", "")),
                "title": title,
                "type": s.get("type", ""),
                "url": s.get("url") or "",
            })
        return _ok(title=data.get("title", ""), id=data.get("id", ""),
                   created=str(data.get("created_at", ""))[:10],
                   sources=src_items, n_sources=len(src_items))
    return _ok(raw=out)

# ── ask (chat) ─────────────────────────────────────────────────

def cmd_ask(args):
    plain = False
    nb = None
    prompt_parts = []
    i = 0
    while i < len(args):
        if args[i] == "-p" or args[i] == "--plain":
            plain = True
        elif args[i] == "-n" or args[i] == "--notebook":
            i += 1
            if i < len(args):
                nb = args[i]
        elif args[i] == "--new":
            prompt_parts.append("")
        else:
            prompt_parts.append(args[i])
        i += 1

    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        else:
            return _err("usage: nlm.py ask [-p] [-n notebook] <question>")

    nid = nb or _default_nb()
    cmd = ["ask", prompt]
    if nid:
        cmd = ["ask", "--notebook", nid, prompt]

    out, err, rc = _run(cmd, timeout=120)
    if rc != 0:
        return _err(err or out[:500])

    answer = _answer_filter(out)
    if plain:
        answer = re.sub(r'\*\*(.+?)\*\*', r'\1', answer)
        answer = re.sub(r'__(.+?)__', r'\1', answer)

    result = _maybe_file(answer, "answer")
    if isinstance(result, str) and result.startswith(str(OUT_DIR)):
        return _ok(f=result, n=len(answer))
    return _ok(f=result)

def cmd_suggest_prompts(args):
    """AI-suggested prompts for the notebook (new in notebooklm-py)."""
    mode = None
    query = None
    nb = None
    sources = []
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--mode":
            i += 1
            if i < len(args):
                mode = args[i]
        elif args[i] == "--query":
            i += 1
            if i < len(args):
                query = args[i]
        elif args[i] in ("-s", "--source"):
            i += 1
            if i < len(args):
                sources.append(args[i])
        elif args[i] in ("-n", "--notebook"):
            i += 1
            if i < len(args):
                nb = args[i]
        else:
            rest.append(args[i])
        i += 1
    cmd = ["suggest-prompts", "--json"]
    if mode:
        cmd.extend(["--mode", mode])
    if query:
        cmd.extend(["--query", query])
    for s in sources:
        cmd.extend(["--source", s])
    cmd.extend(_nb_args(nb))
    cmd.extend(rest)
    out, err, rc = _run(cmd, timeout=60)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, (dict, list)):
        return _ok(prompts=data)
    return _ok(raw=out)

# ── source group ─────────────────────────────────────────────

def cmd_source_list(args):
    nb, rest = _split_nb(args)
    cmd = ["source", "list", "--json"]
    for flag in ("--label", "--status", "--limit"):
        if flag in rest:
            i = rest.index(flag)
            if i + 1 < len(rest):
                cmd += [flag, rest[i + 1]]
    if "--no-truncate" in rest:
        cmd.append("--no-truncate")
    cmd += _nb_args(nb)
    out, err, rc = _run(cmd, timeout=30)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "sources", ("id", "title", "type", "status"))
    return _ok(sources=items, n=count)

def _extract_text(path):
    """Extract text from a file: PDF via pypdf, else plain UTF-8 read."""
    import pathlib
    p = pathlib.Path(path)
    try:
        if p.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(str(p))
            return "\n\n".join((pg.extract_text() or "") for pg in r.pages).strip()
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def _poll_source_status(sid, max_wait=45, nb=None):
    """Poll a source's status until ready/error. Returns the status string."""
    import time as _t
    nb_args = _nb_args(nb)
    deadline = _t.time() + max_wait
    while _t.time() < deadline:
        out, err, rc = _run(["source", "get", "--json", sid] + nb_args, timeout=30)
        data = _json_or_text(out)
        if isinstance(data, dict):
            st = (_unwrap(data, "source") or {}).get("status", "")
            if st in ("ready", "error"):
                return st
        _t.sleep(4)
    return "processing"


def _add_file_with_fallback(path, title=None, nb=None):
    """Upload a local file to NotebookLM. The binary upload succeeds normally
    when the profile's Google cookies are fresh. If the cookies have gone stale,
    NotebookLM accepts the upload but the source lands in status 'error'
    (surfacing as SourceProcessingError) — in that case, fall back to extracting
    the text and adding it as a pasted-text source, and signal that a re-login
    is needed (run `nlm.py auth init`)."""
    import pathlib
    p = pathlib.Path(path)
    nb_args = _nb_args(nb)
    cmd = ["source", "add", "--type", "file", "--json"] + nb_args
    if title:
        cmd.extend(["--title", title])
    cmd.append(str(p))
    out, err, rc = _run(cmd, timeout=120)
    data = _json_or_text(out)
    src = (_unwrap(data, "source") or {}) if isinstance(data, dict) else {}
    sid = src.get("id", "")
    if not sid:
        return _err(err or out or "file add failed")
    status = _poll_source_status(sid, nb=nb)
    if status == "ready":
        return _ok(id=sid, title=src.get("title", p.name), method="file")
    # fallback: stale cookies likely; extract text and re-add as a pasted-text source
    text = _extract_text(p)
    if not text:
        return _ok(id=sid, status=status, method="file-failed",
                   note="binary upload errored (stale NotebookLM cookies); re-login with `nlm.py auth init`; no text extractable")
    _run(["source", "delete", sid, "-y", "--json"] + nb_args, timeout=30)
    out2, err2, rc2 = _run(["source", "add", "--type", "text", "--json"] + nb_args + [text], timeout=120)
    data2 = _json_or_text(out2)
    src2 = (_unwrap(data2, "source") or {}) if isinstance(data2, dict) else {}
    sid2 = src2.get("id", "")
    return _ok(id=sid2, title=src2.get("title", p.name), method="text-fallback",
               n_chars=len(text),
               note="binary upload errored (stale NotebookLM cookies); re-login with `nlm.py auth init`; added as extracted text")


def cmd_source_add(args):
    usage = "usage: nlm.py source add [--type url|text|file|youtube] [--title T] [-n nb] <value>"
    if not args:
        return _err(usage)
    nb, args = _split_nb(args)
    stype = None
    title = None
    value_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--type":
            i += 1
            if i < len(args):
                stype = args[i]
        elif args[i] == "--title":
            i += 1
            if i < len(args):
                title = args[i]
        else:
            value_parts.append(args[i])
        i += 1
    value = " ".join(value_parts)
    if not value:
        return _err(usage)
    # local file → file upload with a text-extraction fallback for the stale-cookie
    # case (NotebookLM accepts the binary but leaves the source 'error' when the
    # profile's Google cookies have expired — re-login to fix)
    import pathlib
    if stype == "file" or (stype in (None, "url") and pathlib.Path(value).is_file()):
        return _add_file_with_fallback(value, title=title, nb=nb)
    cmd = ["source", "add", "--json"]
    if stype:
        cmd.extend(["--type", stype])
    if title:
        cmd.extend(["--title", title])
    cmd.extend(_nb_args(nb))
    cmd.append(value)
    out, err, rc = _run(cmd, timeout=120)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        src = _unwrap(data, "source")
        return _ok(id=src.get("id", ""), title=src.get("title", ""),
                   type=src.get("type", ""))
    return _ok(raw=out)

def cmd_source_guide(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py source guide <id> [-n nb]")
    out, err, rc = _run(["source", "guide", rest[0]] + _nb_args(nb), timeout=60)
    if rc != 0:
        return _err(err or out)
    return _ok(guide=_maybe_file(out, "guide"))

def cmd_source_fulltext(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py source fulltext <id> [-n nb]")
    out, err, rc = _run(["source", "fulltext", rest[0]] + _nb_args(nb), timeout=60)
    if rc != 0:
        return _err(err or out)
    return _ok(fulltext=_maybe_file(out, "fulltext"))

def cmd_source_get(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py source get <id> [-n nb]")
    out, err, rc = _run(["source", "get", "--json", rest[0]] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        src = _unwrap(data, "source")
        return _ok(id=src.get("id", ""), title=src.get("title", ""),
                   type=src.get("type", ""), status=src.get("status", ""),
                   url=src.get("url") or "")
    return _ok(raw=out)

def cmd_source_delete(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py source delete <id> [-n nb]")
    out, err, rc = _run(["source", "delete", rest[0], "-y", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=rest[0], deleted=bool(data.get("deleted", True)))
    return _ok(id=rest[0], raw=out)

def cmd_source_clean(args):
    nb, rest = _split_nb(args)
    out, err, rc = _run(["source", "clean", "--json"] + _nb_args(nb), timeout=60)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        scalar = {k: v for k, v in data.items() if not isinstance(v, (list, dict))}
        return _ok(**scalar)
    return _ok(raw=out)

def cmd_source_add_research(args):
    usage = ("usage: nlm.py source add-research [--mode fast|deep] [--from web|drive] "
             "[--import-all] [--cited-only] [--no-wait] <query>")
    if not args:
        return _err(usage)
    mode = "fast"
    from_src = None
    nowait = False
    import_all = "--import-all" in args
    cited_only = "--cited-only" in args
    nb = None
    query_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--mode":
            i += 1
            if i < len(args):
                mode = args[i]
        elif args[i] == "--from":
            i += 1
            if i < len(args):
                from_src = args[i]
        elif args[i] == "--no-wait":
            nowait = True
        elif args[i] in ("-n", "--notebook"):
            i += 1
            if i < len(args):
                nb = args[i]
        elif args[i] in ("--import-all", "--cited-only"):
            pass  # handled above
        else:
            query_parts.append(args[i])
        i += 1
    query = " ".join(query_parts)
    if not query:
        return _err(usage)
    cmd = ["source", "add-research", "--mode", mode, "--json"]
    if from_src:
        cmd.extend(["--from", from_src])
    if nowait:
        cmd.append("--no-wait")
    if import_all:
        cmd.append("--import-all")
    if cited_only:
        cmd.append("--cited-only")
    cmd.extend(_nb_args(nb))
    cmd.append(query)
    out, err, rc = _run(cmd, timeout=90 if nowait else 600)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(status=data.get("status", ""), task_id=data.get("task_id", ""),
                   sources=data.get("sources", []), n=len(data.get("sources", [])))
    return _ok(raw=out)

# ── research group ─────────────────────────────────────────────

def cmd_research_status(args):
    nb, rest = _split_nb(args)
    out, err, rc = _run(["research", "status", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(**(data if "status" in data else {"raw": out}),
                   notebook=nb or _default_nb())
    return _ok(raw=out)

def cmd_research_wait(args):
    nb, rest = _split_nb(args)
    import_all = "--import-all" in rest
    cmd = ["research", "wait", "--json"]
    if import_all:
        cmd.append("--import-all")
    cmd.extend(_nb_args(nb))
    out, err, rc = _run(cmd, timeout=600)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(status=data.get("status", ""),
                   n_sources=len(data.get("sources", []) or []))
    return _ok(raw=out)

# ── artifact group ─────────────────────────────────────────────

ARTIFACT_TYPES = [
    "audio", "video", "cinematic-video", "slide-deck", "infographic",
    "mind-map", "data-table", "quiz", "flashcards", "report",
    "fantasy-map", "file",
]

def cmd_artifact_list(args):
    nb, rest = _split_nb(args)
    cmd = ["artifact", "list", "--json"]
    for flag in ("--type", "--limit"):
        if flag in rest:
            i = rest.index(flag)
            if i + 1 < len(rest):
                cmd += [flag, rest[i + 1]]
    if "--no-truncate" in rest:
        cmd.append("--no-truncate")
    cmd += _nb_args(nb)
    out, err, rc = _run(cmd, timeout=30)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "artifacts", ("id", "title", "type", "status", "created_at"))
    return _ok(artifacts=items, n=count)

def cmd_artifact_generate(args):
    usage = ("usage: nlm.py artifact generate <type> [<description>] "
             "[--instructions <text>] [--format F] [--length L] [--language L] "
             "[--wait] [-n notebook]\n"
             "types: {}".format(", ".join(ARTIFACT_TYPES)))
    if not args:
        return _err(usage)
    atype = args[0]
    if atype not in ARTIFACT_TYPES:
        return _err("unknown type '{}'. Valid: {}".format(atype, ", ".join(ARTIFACT_TYPES)))
    description = None
    fmt = None
    length = None
    language = None
    kind = None
    append_text = None
    wait_flag = False
    nb = None
    i = 1
    while i < len(args):
        if args[i] == "--instructions":
            i += 1
            if i < len(args):
                description = args[i]
        elif args[i] == "--format":
            i += 1
            if i < len(args):
                fmt = args[i]
        elif args[i] == "--length":
            i += 1
            if i < len(args):
                length = args[i]
        elif args[i] == "--language":
            i += 1
            if i < len(args):
                language = args[i]
        elif args[i] == "--kind":
            i += 1
            if i < len(args):
                kind = args[i]
        elif args[i] == "--append":
            i += 1
            if i < len(args):
                append_text = args[i]
        elif args[i] == "--wait":
            wait_flag = True
        elif args[i] in ("-n", "--notebook"):
            i += 1
            if i < len(args):
                nb = args[i]
        else:
            # positional description (notebooklm-py 0.8.1 API for most types)
            description = (description + " " + args[i]).strip() if description else args[i]
        i += 1

    cmd = ["generate", atype, "--json"]
    # `mind-map` is the one type whose prompt is a FLAG (`--instructions`), not a
    # positional DESCRIPTION, and which has no `--wait` (interactive polls by
    # default). Every other type takes a positional description + `--wait`.
    if atype == "mind-map":
        if description:
            cmd.extend(["--instructions", description])
        if kind:
            cmd.extend(["--kind", kind])
        if language:
            cmd.extend(["--language", language])
    else:
        if description:
            cmd.append(description)
        if fmt:
            cmd.extend(["--format", fmt])
        if length:
            cmd.extend(["--length", length])
        if language:
            cmd.extend(["--language", language])
        if append_text:
            cmd.extend(["--append", append_text])
        if wait_flag:
            cmd.append("--wait")
    cmd.extend(_nb_args(nb))
    out, err, rc = _run(cmd, timeout=360 if wait_flag else 120)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, dict):
        # mind-map returns {mind_map, note_id, kind}; others return
        # {task_id, status, [url]} (pending) or {task_id, status:"completed", url}.
        if "mind_map" in data:
            return _ok(type=atype, id=data.get("note_id", ""), mind_map=data["mind_map"])
        result = {"type": atype, "task_id": data.get("task_id", ""),
                  "status": data.get("status", "")}
        if data.get("url"):
            result["url"] = data["url"]
        return _ok(**result)
    return _ok(raw=out)

def cmd_artifact_download(args):
    usage = ("usage: nlm.py artifact download <type> [--artifact <id>] [--format pdf|pptx] "
             "[--all] [--dry-run] [--name T] [-n nb]\n"
             "types: {}".format(", ".join(ARTIFACT_TYPES)))
    if not args:
        return _err(usage)
    atype = args[0]
    if atype not in ARTIFACT_TYPES:
        return _err("unknown type '{}'. Valid: {}".format(atype, ", ".join(ARTIFACT_TYPES)))
    nb, args = _split_nb(args[1:])
    aid = None
    fmt = None
    all_flag = False
    dry_run = False
    name = None
    i = 0
    while i < len(args):
        if args[i] == "--artifact" or args[i] == "-a":
            i += 1
            if i < len(args):
                aid = args[i]
        elif args[i] == "--format":
            i += 1
            if i < len(args):
                fmt = args[i]
        elif args[i] == "--all":
            all_flag = True
        elif args[i] == "--dry-run":
            dry_run = True
        elif args[i] == "--name":
            i += 1
            if i < len(args):
                name = args[i]
        i += 1

    cmd = ["download", atype, "--json", "--force"]
    if aid:
        cmd.extend(["-a", aid])
    if fmt:
        cmd.extend(["--format", fmt])
    if all_flag:
        cmd.append("--all")
    if dry_run:
        cmd.append("--dry-run")
    if name:
        cmd.extend(["--name", name])
    cmd.extend(_nb_args(nb))
    out, err, rc = _run(cmd, timeout=60)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, dict):
        path = data.get("output_path", "")
        status = data.get("status", "")
        return _ok(path=path, status=status)
    return _ok(raw=out)

def cmd_artifact_suggestions(args):
    nb, rest = _split_nb(args)
    out, err, rc = _run(["artifact", "suggestions", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, list):
        suggestions = [{"title": s.get("title", ""), "description": s.get("description", "")}
                       for s in data if isinstance(s, dict)]
        return _ok(suggestions=suggestions, n=len(suggestions))
    return _ok(raw=out)

def cmd_artifact_get(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py artifact get <id> [-n nb]")
    nb_args = _nb_args(nb)
    out, err, rc = _run(["artifact", "get", "--json", rest[0]] + nb_args, timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        art = _unwrap(data, "artifact")
        url = art.get("url", "") or art.get("download_url", "")
        if not url:
            # poll returns the CDN url for completed artifacts (get does not)
            try:
                pout, perr, prc = _run(["artifact", "poll", rest[0], "--json"] + nb_args, timeout=30)
                if prc == 0:
                    pdata = _json_or_text(pout)
                    if isinstance(pdata, dict):
                        inner = _unwrap(pdata, "result")
                        url = (inner.get("url", "") if isinstance(inner, dict) else "") \
                              or pdata.get("url", "") or ""
            except Exception:
                pass
        return _ok(id=art.get("id", ""), title=art.get("title", ""),
                   type=art.get("type", ""), status=art.get("status", ""),
                   url=url)
    return _ok(raw=out)

def cmd_artifact_delete(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py artifact delete <id> [-n nb]")
    out, err, rc = _run(["artifact", "delete", rest[0], "-y", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=rest[0], deleted=bool(data.get("deleted", True)))
    return _ok(id=rest[0], raw=out)

# ── note group ──────────────────────────────────────────────────

def cmd_note_list(args):
    nb, rest = _split_nb(args)
    out, err, rc = _run(["note", "list", "--json"] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "notes", ("id", "title", "preview"), strip_date=False)
    clean = []
    for n in items:
        clean.append({"id": n.get("id", ""), "title": n.get("title", ""),
                       "preview": (n.get("preview", "") or "")[:80]})
    return _ok(notes=clean, n=count, notebook=nb or _default_nb())

def cmd_note_create(args):
    usage = "usage: nlm.py note create [-t title] [-n nb] [content...]"
    nb, args = _split_nb(args)
    if not args:
        return _err(usage)
    title = None
    content_parts = []
    i = 0
    while i < len(args):
        if args[i] in ("-t", "--title"):
            i += 1
            if i < len(args):
                title = args[i]
        else:
            content_parts.append(args[i])
        i += 1
    content = " ".join(content_parts).strip()
    if not content:
        if not sys.stdin.isatty():
            content = sys.stdin.read().strip()
        if not content:
            return _err(usage + " (no content provided)")
    cmd = ["note", "create", "--json"] + _nb_args(nb)
    if title:
        cmd.extend(["-t", title])
    cmd.append(content)
    out, err, rc = _run(cmd, timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        note = _unwrap(data, "note")
        return _ok(id=note.get("id", ""), title=note.get("title", ""))
    return _ok(raw=out)

def cmd_note_get(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py note get <id> [-n nb]")
    out, err, rc = _run(["note", "get", "--json", rest[0]] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        note = _unwrap(data, "note")
        return _ok(id=note.get("id", ""), title=note.get("title", ""),
                   content=_maybe_file(note.get("content", "") or "", "note"))
    return _ok(raw=out)

def cmd_note_save(args):
    nb, rest = _split_nb(args)
    if len(rest) < 2:
        return _err("usage: nlm.py note save <id> <content> [-n nb]")
    nid = rest[0]
    content = " ".join(rest[1:])
    out, err, rc = _run(["note", "save", "--json", "--content", content, nid] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=data.get("id", nid), saved=bool(data.get("saved", True)),
                   n_chars=len(content))
    return _ok(id=nid, raw=out)

def cmd_note_rename(args):
    nb, rest = _split_nb(args)
    if len(rest) < 2:
        return _err("usage: nlm.py note rename <id> <new_title> [-n nb]")
    out, err, rc = _run(["note", "rename", "--json", rest[0], rest[1]] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=data.get("id", rest[0]), title=data.get("title", rest[1]),
                   renamed=bool(data.get("renamed", True)))
    return _ok(id=rest[0], raw=out)

def cmd_note_delete(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py note delete <id> [-n nb]")
    out, err, rc = _run(["note", "delete", rest[0], "-y", "--json"] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=rest[0], deleted=bool(data.get("deleted", True)))
    return _ok(id=rest[0], raw=out)

# ── share group ─────────────────────────────────────────────────

def cmd_share_status(args):
    nb, rest = _split_nb(args)
    out, err, rc = _run(["share", "status", "--json"] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        users = [{"email": u.get("email", ""), "permission": u.get("permission", ""),
                  "name": u.get("display_name", "")}
                 for u in data.get("shared_users", []) if isinstance(u, dict)]
        return _ok(notebook=nb or _default_nb(),
                   public=data.get("is_public", False),
                   access=data.get("access", ""),
                   url=data.get("share_url", ""),
                   view_level=data.get("view_level", ""),
                   users=users)
    return _ok(raw=out)

def cmd_share_public(args):
    nb, rest = _split_nb(args)
    if not rest or rest[0] not in ("enable", "disable"):
        return _err("usage: nlm.py share public enable|disable [-n nb]")
    out, err, rc = _run(["share", "public", "--{}".format(rest[0]), "--json"] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(public=bool(data.get("is_public", rest[0] == "enable")),
                   url=data.get("share_url") or "",
                   notebook=nb or _default_nb())
    return _ok(raw=out)

def cmd_share_add(args):
    nb, rest = _split_nb(args)
    if len(rest) < 1:
        return _err("usage: nlm.py share add <email> [--permission viewer|editor] [--no-notify] [-n nb]")
    email = rest[0]
    perm = "viewer"
    no_notify = False
    i = 1
    while i < len(rest):
        if rest[i] == "--permission":
            i += 1
            if i < len(rest):
                perm = rest[i]
        elif rest[i] == "--no-notify":
            no_notify = True
        i += 1
    cmd = ["share", "add", email, "--permission", perm, "--json"] + _nb_args(nb)
    if no_notify:
        cmd.append("--no-notify")
    out, err, rc = _run(cmd, timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(email=email, permission=perm,
                   added=bool(data.get("added", True)))
    return _ok(email=email, raw=out)

def cmd_share_remove(args):
    nb, rest = _split_nb(args)
    if not rest:
        return _err("usage: nlm.py share remove <email> [-n nb]")
    out, err, rc = _run(["share", "remove", rest[0], "-y", "--json"] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(email=rest[0], removed=bool(data.get("removed", True)))
    return _ok(email=rest[0], raw=out)

def cmd_share_view_level(args):
    nb, rest = _split_nb(args)
    if not rest or rest[0] not in ("full", "chat"):
        return _err("usage: nlm.py share view-level full|chat [-n nb]")
    out, err, rc = _run(["share", "view-level", rest[0], "--json"] + _nb_args(nb), timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(view_level=data.get("view_level", rest[0]))
    return _ok(raw=out)

# ── history ─────────────────────────────────────────────────────

def cmd_history(args):
    save_note = "--save" in args
    note_title = None
    show_all = "--show-all" in args
    limit = None
    nb = None
    i = 0
    while i < len(args):
        if args[i] in ("-t", "--note-title"):
            i += 1
            if i < len(args):
                note_title = args[i]
        elif args[i] in ("-l", "--limit"):
            i += 1
            if i < len(args):
                try:
                    limit = int(args[i])
                except ValueError:
                    pass
        elif args[i] in ("-n", "--notebook"):
            i += 1
            if i < len(args):
                nb = args[i]
        i += 1
    cmd = ["history", "--json"]
    if save_note:
        cmd.append("--save")
        if note_title:
            cmd.extend(["-t", note_title])
    if show_all:
        cmd.append("--show-all")
    if limit:
        cmd.extend(["-l", str(limit)])
    cmd.extend(_nb_args(nb))
    out, err, rc = _run(cmd, timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        conv_id = data.get("conversation_id", "")
        items = data.get("qa_pairs", [])
        turns = []
        for t in items:
            if not isinstance(t, dict):
                continue
            turns.append({
                "turn": t.get("turn", ""),
                "question": (t.get("question", "") or "")[:200],
                "answer_preview": (t.get("answer", "") or "")[:200],
            })
        return _ok(conversation_id=conv_id, turns=turns, n=len(turns))
    return _ok(raw=out)

# ── configure ───────────────────────────────────────────────────

def cmd_configure(args):
    nb, args = _split_nb(args)
    mode = None
    persona = None
    response_length = None
    i = 0
    while i < len(args):
        if args[i] == "--mode":
            i += 1
            if i < len(args):
                mode = args[i]
        elif args[i] == "--persona":
            i += 1
            if i < len(args):
                persona = args[i]
        elif args[i] == "--response-length":
            i += 1
            if i < len(args):
                response_length = args[i]
        i += 1
    # Upstream rejects a preset combined with a custom persona/response_length;
    # catching it here turns a raw VALIDATION_ERROR blob into a usable message.
    if mode and mode != "default" and (persona or response_length):
        return _err("--mode (preset) cannot be combined with --persona/--response-length. "
                    "Use either a preset or a custom persona.")
    cmd = ["configure", "--json"] + _nb_args(nb)
    if mode:
        cmd.extend(["--mode", mode])
    if persona:
        cmd.extend(["--persona", persona])
    if response_length:
        cmd.extend(["--response-length", response_length])
    out, err, rc = _run(cmd, timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(notebook=data.get("notebook_id") or nb or _default_nb(),
                   mode=data.get("mode"), persona=data.get("persona"),
                   response_length=data.get("response_length"),
                   configured=bool(data.get("configured", True)))
    return _ok(raw=out)

def cmd_doctor(args):
    """Session/profile health (upstream `doctor`), parsed."""
    fix = "--fix" in args
    cmd = ["doctor", "--json"]
    if fix:
        cmd.append("--fix")
    out, err, rc = _run(cmd, timeout=60)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        checks = data.get("checks", {}) or {}
        summary = {k: (v.get("status") if isinstance(v, dict) else v)
                   for k, v in checks.items()}
        # "warn" is advisory (e.g. headless_reauth is not installed), not a failure.
        failing = [k for k, v in summary.items()
                   if v not in ("pass", "ok", "skipped", "warn", None)]
        warnings = [k for k, v in summary.items() if v == "warn"]
        return _ok(profile=data.get("profile", PROFILE or "default"),
                   healthy=not failing, failing=failing, warnings=warnings,
                   checks=summary)
    return _ok(raw=out)

# ── auth ────────────────────────────────────────────────────────

def cmd_auth_init(args):
    """Refresh auth. Prefers upstream `login --browser-cookies` (rookiepy)."""
    account = None
    browser = "auto"
    i = 0
    while i < len(args):
        if args[i] in ("--account",):
            i += 1
            if i < len(args):
                account = args[i]
        elif args[i] in ("--browser",):
            i += 1
            if i < len(args):
                browser = args[i]
        i += 1
    cmd = ["login", "--browser-cookies", browser]
    if account:
        cmd.extend(["--account", account])
    out, err, rc = _run(cmd, timeout=60)
    if rc != 0:
        return _err(err or out[:500])
    last = (out or "").strip().splitlines()[-1][:200] if out else "auth stored"
    return _ok(message=last)

#: Google auth cookies whose staleness gates NotebookLM operations (esp. file upload).
#: The PSID / PSIDTS family are session tokens that rotate server-side and can go
#: stale long before their nominal browser ``expires`` timestamp lapses.
AUTH_COOKIE_NAMES = {
    "SID", "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID",
    "HSID", "SSID", "APISID",
    "OSID", "__Secure-OSID",
    "SIDCC", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "__Secure-ENID",
}


def _norm_expires(e):
    """Normalize a cookie ``expires`` to unix seconds, or None for session cookies."""
    if e is None or e == -1 or e <= 0:
        return None
    e = float(e)
    if e > 10**12:  # millisecond timestamp (known notebooklm-py storage-state bug)
        e = e / 1000.0
    return e


def cmd_auth_status(args):
    """Surface auth-cookie expiry and staleness. Usage: nlm.py auth status [--verbose]

    Reports three signals: (1) nominal expiry of the Google auth cookies,
    (2) how long ago the session state was last written (staleness proxy — the
    PSID/PSIDTS tokens are invalidated server-side within ~2 weeks regardless of
    nominal expiry), and (3) a live authenticated RPC to catch total breakage."""
    verbose = "--verbose" in args or "-v" in args
    now = time.time()

    if not STORAGE.exists():
        return _err("no storage_state.json at {} — run `nlm.py auth init`".format(STORAGE))
    try:
        data = json.loads(STORAGE.read_text())
    except Exception as e:
        return _err("failed to parse storage_state.json: {}".format(e))
    cookies = data.get("cookies", [])
    if not cookies:
        return _err("no cookies in storage_state.json — run `nlm.py auth init`")

    auth = [c for c in cookies if c.get("name") in AUTH_COOKIE_NAMES]
    expiring = []   # (name, domain, days_remaining)
    session_only = 0
    for c in auth:
        e = _norm_expires(c.get("expires", -1))
        if e is None:
            session_only += 1
            continue
        days = (e - now) / 86400.0
        expiring.append((c.get("name", ""), c.get("domain", ""), days))
    expiring.sort(key=lambda x: x[2])

    min_name, min_domain, min_days = expiring[0] if expiring else ("", "", None)

    # session state age (staleness proxy)
    age_days = (now - STORAGE.stat().st_mtime) / 86400.0

    # live authenticated RPC (weak signal: list may work even when the session
    # is server-side stale, but it catches deleted cookies / wrong account)
    live = "ok"
    out, err, rc = _run(["list", "--json"], timeout=30)
    if rc != 0:
        live = "fail"
    else:
        d = _json_or_text(out)
        if not isinstance(d, (dict, list)):
            live = "fail"

    # classify
    if min_days is not None and min_days < 0:
        status = "expired"
        rec = "re-login NOW: run `nlm.py auth init` or `notebooklm login`"
    elif live == "fail":
        status = "broken"
        rec = "auth broken (RPC failed) — re-login: run `nlm.py auth init`"
    elif min_days is not None and min_days < 7:
        status = "expiring"
        rec = "re-login within {:.0f} days: run `nlm.py auth init`".format(min_days)
    elif age_days > 14:
        status = "at-risk"
        rec = "session not refreshed in {:.0f} days (server-side staleness likely) — re-login: run `nlm.py auth init`".format(age_days)
    else:
        status = "healthy"
        rec = "no action needed"

    res = {
        "status": status,
        "recommendation": rec,
        "n_cookies": len(cookies),
        "auth_cookies": len(auth),
        "session_only_cookies": session_only,
        "min_expiry_days": round(min_days, 1) if min_days is not None else None,
        "min_expiry_cookie": min_name if min_name else None,
        "min_expiry_domain": min_domain if min_domain else None,
        "session_age_days": round(age_days, 1),
        "live_check": live,
    }
    if verbose:
        res["expiring"] = [
            {"name": n, "domain": d, "days": round(x, 1)}
            for n, d, x in expiring[:8]
        ]
    return _ok(**res)

# ── clear ───────────────────────────────────────────────────────

def cmd_clear(args):
    out, err, rc = _run(["clear"])
    if rc != 0:
        return _err(err or out)
    return _ok()

# ── passthrough groups (label/collection/profile/language/agent/skill/mcp) ──

PASSTHROUGH_GROUPS = {
    "label", "collection", "profile", "language", "agent", "skill", "mcp",
}

def cmd_passthrough(group, action, action_args):
    return _forward_group(group, action, action_args, timeout=90)

# ── agent-native extras: surface / selftest / batch ──────────────

def cmd_surface(args):
    """Machine-readable command map — cheap discovery for an agent (~250 tokens)."""
    groups = {g: sorted(a.keys()) for g, a in GROUP_MAP.items()}
    return _ok(groups=groups, passthrough=sorted(PASSTHROUGH_GROUPS),
               aliases=ALIASES, artifact_types=ARTIFACT_TYPES,
               notebook_flag="-n/--notebook (any position)",
               profile_flag="--profile NAME")

SELFTEST_STEPS = (
    ("auth", ["auth", "status"]),
    ("notebook_list", ["nb", "list"]),
    ("status", ["nb", "status"]),
    ("source_list", ["src", "list"]),
    ("artifact_list", ["art", "list"]),
    ("notes", ["notes"]),
    ("share", ["share", "status"]),
    ("doctor", ["doctor"]),
)

def cmd_selftest(args):
    """Read-only readiness check: run before trusting the tool in a pipeline."""
    only = args[0] if args else None
    results = []
    passed = 0
    for name, argv in SELFTEST_STEPS:
        if only and only != name:
            continue
        try:
            d = json.loads(dispatch(argv))
        except Exception as e:                      # pragma: no cover - defensive
            d = {"s": "err", "e": str(e)}
        ok = d.get("s") == "ok"
        passed += 1 if ok else 0
        entry = {"step": name, "ok": ok}
        if not ok:
            entry["e"] = str(d.get("e", ""))[:160]
        results.append(entry)
    return _ok(passed=passed, total=len(results), healthy=passed == len(results),
               steps=results)

def cmd_batch(args):
    """Run several commands in one process.

    `nlm.py batch "nb list" "src list -n <id>" "history -l 3"` → one JSON
    document with a `results` array, saving N process spawns. Specs are
    whitespace-split, so quote arguments that contain spaces inside the spec.
    """
    if not args:
        return _err("usage: nlm.py batch '<cmd>' ['<cmd>' ...]")
    out = []
    for spec in args:
        try:
            d = json.loads(dispatch(spec.split()))
        except Exception as e:
            d = {"s": "err", "e": str(e)}
        out.append({"cmd": spec, "ok": d.get("s") == "ok", "r": d})
    return _ok(results=out, n=len(out),
               n_ok=sum(1 for r in out if r["ok"]))

# ── dispatch ────────────────────────────────────────────────────

GROUP_MAP = {
    "notebook": {
        "list": cmd_notebook_list,
        "create": cmd_notebook_create,
        "rename": cmd_notebook_rename,
        "delete": cmd_notebook_delete,
        "use": cmd_notebook_use,
        "status": cmd_notebook_status,
        "summary": cmd_notebook_summary,
        "metadata": cmd_notebook_metadata,
    },
    "ask": {"ask": cmd_ask},
    "prompts": {"prompts": cmd_suggest_prompts},
    "source": {
        "list": cmd_source_list,
        "add": cmd_source_add,
        "add-drive": lambda a: _forward_group("source", "add-drive", a, timeout=120),
        "add-drive-file": lambda a: _forward_group("source", "add-drive-file", a, timeout=120),
        "guide": cmd_source_guide,
        "fulltext": cmd_source_fulltext,
        "get": cmd_source_get,
        "delete": cmd_source_delete,
        "delete-by-title": lambda a: _forward_group("source", "delete-by-title", a),
        "clean": cmd_source_clean,
        "add-research": cmd_source_add_research,
        "refresh": lambda a: _forward_group("source", "refresh", a, timeout=60),
        "rename": lambda a: _forward_group("source", "rename", a),
        "stale": lambda a: _forward_group("source", "stale", a),
        "wait": lambda a: _forward_group("source", "wait", a, timeout=300),
    },
    "research": {
        "status": cmd_research_status,
        "wait": cmd_research_wait,
        "cancel": lambda a: _forward_group("research", "cancel", a),
        "import": lambda a: _forward_group("research", "import", a, timeout=300),
    },
    "generate": {
        # Only the odd-one-out is wrapped; the rest are reached through
        # `artifact generate` (positional description + --wait).
        "revise-slide": lambda a: _forward_group("generate", "revise-slide", a, timeout=600),
    },
    "artifact": {
        "list": cmd_artifact_list,
        "generate": cmd_artifact_generate,
        "download": cmd_artifact_download,
        "suggestions": cmd_artifact_suggestions,
        "get": cmd_artifact_get,
        "delete": cmd_artifact_delete,
        "export": lambda a: _forward_group("artifact", "export", a, timeout=120),
        "get-prompt": lambda a: _forward_group("artifact", "get-prompt", a),
        "poll": lambda a: _forward_group("artifact", "poll", a),
        "rename": lambda a: _forward_group("artifact", "rename", a),
        "retry": lambda a: _forward_group("artifact", "retry", a, timeout=300),
        "wait": lambda a: _forward_group("artifact", "wait", a, timeout=600),
    },
    "note": {
        "list": cmd_note_list,
        "create": cmd_note_create,
        "get": cmd_note_get,
        "save": cmd_note_save,
        "rename": cmd_note_rename,
        "delete": cmd_note_delete,
    },
    "share": {
        "status": cmd_share_status,
        "public": cmd_share_public,
        "add": cmd_share_add,
        "remove": cmd_share_remove,
        "view-level": cmd_share_view_level,
        "update": lambda a: _forward_group("share", "update", a),
    },
    "history": {"history": cmd_history},
    "configure": {"configure": cmd_configure},
    "auth": {
        "init": cmd_auth_init,
        "doctor": cmd_doctor,
        "status": cmd_auth_status,
        # upstream auth surface, forwarded as-is
        "check": lambda a: _forward_group("auth", "check", a, timeout=120),
        "inspect": lambda a: _forward_group("auth", "inspect", a, timeout=120),
        "logout": lambda a: _forward_group("auth", "logout", a),
        "refresh": lambda a: _forward_group("auth", "refresh", a, timeout=120),
        "import-cookies": lambda a: _forward_group("auth", "import-cookies", a, timeout=120),
    },
    "doctor": {"doctor": cmd_doctor},
    "clear": {"clear": cmd_clear},
}

ALIASES = {
    "ls": "source list",
    "src": "source",
    "art": "artifact",
    "gen": "artifact generate",
    "dl": "artifact download",
    "notes": "note list",
    "nb": "notebook",
    "prompt": "prompts prompts",
}

USAGE = """Usage: nlm.py [--profile NAME] <group> <action> [args...]

Groups:
  notebook   create, rename, delete, list, use, status, summary, metadata
  ask        <question> [-p] [-n notebook] [--new]
  prompts    AI-suggested prompts (--mode 1-10, --query, -s source)
  source     list [--label L --status S --limit N], add, add-drive,
             add-drive-file, guide, fulltext, get, delete, delete-by-title,
             clean, add-research, refresh, rename, stale, wait
  research   status, wait, cancel, import
  artifact   list [--type T --limit N], generate, download, suggestions, get,
             delete, export, get-prompt, poll, rename, retry, wait
  generate   revise-slide (remaining generate types via `artifact generate`)
  note       list, create, get, save, rename, delete
  share      status, public, add, remove, view-level, update
  history    [--save] [--json] [--limit N] [--show-all]
  configure  [--mode MODE] [--persona TEXT] [--response-length LEN]
  auth       init [--account EMAIL] [--browser B], status [--verbose],
             doctor, check, inspect, logout, refresh, import-cookies
  doctor     [--fix]        session/profile health (parsed)
  selftest   [step]         read-only readiness battery (auth/list/status/...)
  surface                   machine-readable command map (cheap discovery)
  batch      '<cmd>' ...    run several commands in one process
  clear      [notebook_id]

Every notebook-scoped command accepts `-n/--notebook <id>` in any position.
`--profile NAME` (or NOTEBOOKLM_PROFILE) selects the upstream account profile.

Passthrough groups (forwarded to upstream): label, collection, profile,
  language, agent, skill, mcp

Aliases: ls=source list, src=source, art=artifact, gen=artifact generate,
         dl=artifact download, notes=note list, nb=notebook

Shorthand: nlm.py "question"  →  same as  nlm.py ask "question"

Output: JSON with "s":"ok" or "s":"err"."""


def dispatch(args):
    """Resolve aliases + dispatch one command, returning its JSON string.

    Split out of main() so `batch` / `selftest` can reuse the exact same
    resolution and error handling as a top-level invocation.
    """
    if not args:
        return USAGE

    # Resolve aliases
    first = args[0]
    if first in ALIASES:
        resolved = ALIASES[first].split()
        args = resolved + args[1:]

    group = args[0]
    rest = args[1:]

    # Shorthand: positional question → ask
    # Single-action groups: auto-dispatch action
    single_actions = {"history": cmd_history, "configure": cmd_configure,
                      "clear": cmd_clear, "ask": cmd_ask,
                      "prompts": cmd_suggest_prompts, "doctor": cmd_doctor,
                      "selftest": cmd_selftest, "surface": cmd_surface,
                      "batch": cmd_batch}

    if group in single_actions:
        return single_actions[group](rest)

    # Passthrough groups: forward <group> <action> --json <args> upstream
    if group in PASSTHROUGH_GROUPS:
        if not rest:
            return _err("group '{}' requires an action.".format(group))
        action = rest[0]
        action_args = rest[1:]
        return cmd_passthrough(group, action, action_args)

    # Shorthand: any unknown group with args → treat as question
    if group not in GROUP_MAP:
        return cmd_ask(args)

    actions = GROUP_MAP[group]
    if not rest:
        if group == "auth":
            return cmd_auth_status([])
        return _err("group '{}' requires an action. Valid: {}".format(
            group, ", ".join(actions.keys())))

    action = rest[0]
    action_args = rest[1:]

    if action not in actions:
        return _err("unknown action '{}' in group '{}'. Valid: {}".format(
            action, group, ", ".join(actions.keys())))

    try:
        return actions[action](action_args)
    except Exception as e:
        return _err(str(e))


def main():
    global PROFILE
    args = sys.argv[1:]

    if not args:
        print(USAGE)
        return

    # Global: --profile NAME (upstream account profile, must precede the command)
    for i, a in enumerate(args):
        if a in ("--profile", "-P") and i + 1 < len(args):
            PROFILE = args[i + 1]
            del args[i:i + 2]
            break

    if not args:
        print(USAGE)
        return

    print(dispatch(args))


if __name__ == "__main__":
    main()
