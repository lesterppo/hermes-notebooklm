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
"""
import sys, os, json, subprocess, pathlib, re, time

HOME = pathlib.Path.home()
NLM = str(HOME / ".local" / "bin" / "notebooklm")
CFG_DIR = HOME / ".hermes" / "nlm_cache"
CFG_DIR.mkdir(parents=True, exist_ok=True)
NB_FILE = CFG_DIR / "notebook.txt"
OUT_DIR = HOME / ".hermes" / "nlm_output"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STORAGE = HOME / ".notebooklm" / "profiles" / "default" / "storage_state.json"

# ── helpers ──────────────────────────────────────────────────

def _run(args, timeout=90):
    """Run notebooklm CLI, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run([NLM, "--quiet"] + args,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout after {}s".format(timeout), 124
    except FileNotFoundError:
        return "", "notebooklm binary not found at {}".format(NLM), 127

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
    out, err, rc = _run(["list", "--json"])
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

def cmd_notebook_use(args):
    if not args:
        out, err, rc = _run(["status", "--json"])
        if rc == 0:
            return _ok(raw=out)
        return _ok(notebook=_default_nb())
    nid = args[0]
    out, err, rc = _run(["use", nid])
    if rc == 0:
        NB_FILE.write_text(nid)
        return _ok(notebook=nid)
    return _err(err or out)

def cmd_notebook_status(args):
    out, err, rc = _run(["status"])
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_notebook_summary(args):
    nb = args[0] if args else _default_nb()
    out, err, rc = _run(["summary"] + _nb_args(nb), timeout=60)
    if rc != 0:
        return _err(err or out)
    return _ok(summary=_maybe_file(out, "summary"))

def cmd_notebook_metadata(args):
    nb = args[0] if args else _default_nb()
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
    nb = _default_nb()
    out, err, rc = _run(["source", "list", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "sources", ("id", "title", "type", "status"))
    return _ok(sources=items, n=count)

def cmd_source_add(args):
    usage = "usage: nlm.py source add [--type url|text|file|youtube] [--title T] <value>"
    if not args:
        return _err(usage)
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
    cmd = ["source", "add", "--json"]
    if stype:
        cmd.extend(["--type", stype])
    if title:
        cmd.extend(["--title", title])
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
    if not args:
        return _err("usage: nlm.py source guide <id>")
    out, err, rc = _run(["source", "guide", args[0]], timeout=60)
    if rc != 0:
        return _err(err or out)
    return _ok(guide=_maybe_file(out, "guide"))

def cmd_source_fulltext(args):
    if not args:
        return _err("usage: nlm.py source fulltext <id>")
    out, err, rc = _run(["source", "fulltext", args[0]], timeout=60)
    if rc != 0:
        return _err(err or out)
    return _ok(fulltext=_maybe_file(out, "fulltext"))

def cmd_source_get(args):
    if not args:
        return _err("usage: nlm.py source get <id>")
    out, err, rc = _run(["source", "get", "--json", args[0]], timeout=30)
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
    if not args:
        return _err("usage: nlm.py source delete <id>")
    out, err, rc = _run(["source", "delete", args[0], "-y", "--json"], timeout=30)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_source_clean(args):
    out, err, rc = _run(["source", "clean", "--json"], timeout=60)
    if rc != 0:
        return _err(err or out)
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
    nb = _default_nb()
    out, err, rc = _run(["research", "status", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_research_wait(args):
    import_all = "--import-all" in args
    nb = _default_nb()
    cmd = ["research", "wait", "--json"]
    if import_all:
        cmd.append("--import-all")
    cmd.extend(_nb_args(nb))
    out, err, rc = _run(cmd, timeout=600)
    if rc != 0:
        return _err(err or out[:500])
    return _ok(raw=out)

# ── artifact group ─────────────────────────────────────────────

ARTIFACT_TYPES = [
    "audio", "video", "cinematic-video", "slide-deck", "infographic",
    "mind-map", "data-table", "quiz", "flashcards", "report"
]

def cmd_artifact_list(args):
    nb = _default_nb()
    out, err, rc = _run(["artifact", "list", "--json"] + _nb_args(nb), timeout=30)
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
             "[--all] [--dry-run] [--name T]\n"
             "types: {}".format(", ".join(ARTIFACT_TYPES)))
    if not args:
        return _err(usage)
    atype = args[0]
    if atype not in ARTIFACT_TYPES:
        return _err("unknown type '{}'. Valid: {}".format(atype, ", ".join(ARTIFACT_TYPES)))
    aid = None
    fmt = None
    all_flag = False
    dry_run = False
    name = None
    i = 1
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
    out, err, rc = _run(["artifact", "suggestions", "--json"], timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, list):
        suggestions = [{"title": s.get("title", ""), "description": s.get("description", "")}
                       for s in data if isinstance(s, dict)]
        return _ok(suggestions=suggestions, n=len(suggestions))
    return _ok(raw=out)

def cmd_artifact_get(args):
    if not args:
        return _err("usage: nlm.py artifact get <id>")
    out, err, rc = _run(["artifact", "get", "--json", args[0]], timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        art = _unwrap(data, "artifact")
        return _ok(id=art.get("id", ""), title=art.get("title", ""),
                   type=art.get("type", ""), status=art.get("status", ""))
    return _ok(raw=out)

def cmd_artifact_delete(args):
    if not args:
        return _err("usage: nlm.py artifact delete <id>")
    out, err, rc = _run(["artifact", "delete", args[0], "-y", "--json"], timeout=30)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

# ── note group ──────────────────────────────────────────────────

def cmd_note_list(args):
    out, err, rc = _run(["note", "list", "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "notes", ("id", "title", "preview"), strip_date=False)
    clean = []
    for n in items:
        clean.append({"id": n.get("id", ""), "title": n.get("title", ""),
                       "preview": (n.get("preview", "") or "")[:80]})
    return _ok(notes=clean, n=count)

def cmd_note_create(args):
    usage = "usage: nlm.py note create [-t title] [content...]"
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
    cmd = ["note", "create", "--json"]
    if title:
        cmd.extend(["-t", title])
    cmd.append(content)
    out, err, rc = _run(cmd, timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=data.get("id", ""), title=data.get("title", ""))
    return _ok(raw=out)

def cmd_note_get(args):
    if not args:
        return _err("usage: nlm.py note get <id>")
    out, err, rc = _run(["note", "get", "--json", args[0]], timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=data.get("id", ""), title=data.get("title", ""),
                   content=data.get("content", ""))
    return _ok(raw=out)

def cmd_note_save(args):
    if len(args) < 2:
        return _err("usage: nlm.py note save <id> <content>")
    nid = args[0]
    content = " ".join(args[1:])
    out, err, rc = _run(["note", "save", "--json", "--content", content, nid], timeout=30)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_note_rename(args):
    if len(args) < 2:
        return _err("usage: nlm.py note rename <id> <new_title>")
    out, err, rc = _run(["note", "rename", "--json", args[0], args[1]], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_note_delete(args):
    if not args:
        return _err("usage: nlm.py note delete <id>")
    out, err, rc = _run(["note", "delete", args[0], "-y", "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

# ── share group ─────────────────────────────────────────────────

def cmd_share_status(args):
    out, err, rc = _run(["share", "status", "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        users = [{"email": u.get("email", ""), "permission": u.get("permission", ""),
                  "name": u.get("display_name", "")}
                 for u in data.get("shared_users", []) if isinstance(u, dict)]
        return _ok(public=data.get("is_public", False),
                   access=data.get("access", ""),
                   url=data.get("share_url", ""),
                   view_level=data.get("view_level", ""),
                   users=users)
    return _ok(raw=out)

def cmd_share_public(args):
    if not args or args[0] not in ("enable", "disable"):
        return _err("usage: nlm.py share public enable|disable")
    out, err, rc = _run(["share", "public", "--{}".format(args[0]), "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_share_add(args):
    if len(args) < 1:
        return _err("usage: nlm.py share add <email> [--permission viewer|editor] [--no-notify]")
    email = args[0]
    perm = "viewer"
    no_notify = False
    i = 1
    while i < len(args):
        if args[i] == "--permission":
            i += 1
            if i < len(args):
                perm = args[i]
        elif args[i] == "--no-notify":
            no_notify = True
        i += 1
    cmd = ["share", "add", email, "--permission", perm, "--json"]
    if no_notify:
        cmd.append("--no-notify")
    out, err, rc = _run(cmd, timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_share_remove(args):
    if not args:
        return _err("usage: nlm.py share remove <email>")
    out, err, rc = _run(["share", "remove", args[0], "-y", "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_share_view_level(args):
    if not args or args[0] not in ("full", "chat"):
        return _err("usage: nlm.py share view-level full|chat")
    out, err, rc = _run(["share", "view-level", args[0], "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
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
    cmd = ["configure", "--json"]
    if mode:
        cmd.extend(["--mode", mode])
    if persona:
        cmd.extend(["--persona", persona])
    if response_length:
        cmd.extend(["--response-length", response_length])
    out, err, rc = _run(cmd, timeout=15)
    if rc != 0:
        return _err(err or out)
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

def cmd_auth_doctor(args):
    out, err, rc = _run(["doctor", "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

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
        "doctor": cmd_auth_doctor,
    },
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

USAGE = """Usage: nlm.py <group> <action> [args...]

Groups:
  notebook   create, rename, delete, list, use, status, summary, metadata
  ask        <question> [-p] [-n notebook] [--new]
  prompts    AI-suggested prompts for the notebook (--mode 1-10, --query)
  source     list, add, add-drive, add-drive-file, guide, fulltext, get,
             delete, delete-by-title, clean, add-research, refresh, rename,
             stale, wait
  research   status, wait, cancel, import
  artifact   list, generate, download, suggestions, get, delete, export,
             get-prompt, poll, rename, retry, wait
  note       list, create, get, save, rename, delete
  share      status, public, add, remove, view-level, update
  history    [--save] [--json] [--limit N] [--show-all]
  configure  [--mode MODE] [--persona TEXT] [--response-length LEN]
  auth       init [--account EMAIL] [--browser B], doctor
  clear      [notebook_id]

Passthrough groups (forwarded to upstream): label, collection, profile,
  language, agent, skill, mcp

Aliases: ls=source list, src=source, art=artifact, gen=artifact generate,
         dl=artifact download, notes=note list, nb=notebook

Shorthand: nlm.py "question"  →  same as  nlm.py ask "question"

Output: JSON with "s":"ok" or "s":"err"."""


def main():
    args = sys.argv[1:]

    if not args:
        print(USAGE)
        return

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
                      "prompts": cmd_suggest_prompts}

    if group in single_actions:
        print(single_actions[group](rest))
        return

    # Passthrough groups: forward <group> <action> --json <args> upstream
    if group in PASSTHROUGH_GROUPS:
        if not rest:
            print(_err("group '{}' requires an action.".format(group)))
            return
        action = rest[0]
        action_args = rest[1:]
        print(cmd_passthrough(group, action, action_args))
        return

    # Shorthand: any unknown group with args → treat as question
    if group not in GROUP_MAP:
        print(cmd_ask(args))
        return

    actions = GROUP_MAP[group]
    if not rest:
        print(_err("group '{}' requires an action. Valid: {}".format(group, ", ".join(actions.keys()))))
        return

    action = rest[0]
    action_args = rest[1:]

    if action not in actions:
        print(_err("unknown action '{}' in group '{}'. Valid: {}".format(action, group, ", ".join(actions.keys()))))
        return

    try:
        print(actions[action](action_args))
    except Exception as e:
        print(_err(str(e)))


if __name__ == "__main__":
    main()
