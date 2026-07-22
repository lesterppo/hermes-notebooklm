#!/usr/bin/env python3
"""
NotebookLM agent-native CLI — comprehensive wrapper around notebooklm-py.

Groups: notebook, ask, source, research, artifact, note, share, history, configure, auth, clear

Output: {"s":"ok",...} | {"s":"err","e":"..."} 
Large outputs (>3000 chars) saved to ~/.hermes/nlm_output/ with file pointer.
"""
import sys, os, json, subprocess, pathlib, shlex, textwrap, time

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
    """Return success JSON."""
    d = {"s": "ok"}
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)

def _err(msg):
    """Return error JSON."""
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
    """Get default notebook ID from cache or env."""
    env = os.environ.get("NOTEBOOKLM_NOTEBOOK", "")
    if env:
        return env
    if NB_FILE.exists():
        return NB_FILE.read_text().strip()
    return ""

def _nb_args(nb):
    """Return ['--notebook', id] or [] if no notebook specified."""
    nid = nb or _default_nb()
    return ["--notebook", nid] if nid else []

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
        l = l.replace('\\\\ge', '≥').replace('\\\\le', '≤').replace('\\\\times', '×')
        lines.append(l)
    return '\n'.join(lines).strip()

def _json_or_text(out):
    """Try to parse as JSON, fall back to raw text."""
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return out

# ── notebook group ────────────────────────────────────────────

def _parse_list_result(out, key, item_keys, strip_date=True):
    """Parse a notebooklm --json list result. Returns (items_list, count) or (None, None) on parse failure."""
    data = _json_or_text(out)
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k in (key, "notebooks", "sources", "notes", "artifacts"):
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
            v = it.get(k, "")
            if strip_date and k in ("created_at",) and v:
                v = str(v)[:10]
            entry[k] = v
        clean.append(entry)
    return clean, count

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
        return _ok(id=data.get("id",""), title=data.get("title",""))
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
        sources = []
        for s in data.get("sources", []):
            sources.append({"id": s.get("id",""), "title": s.get("title",""),
                            "type": s.get("type",""), "status": s.get("status","")})
        return _ok(title=data.get("title",""), id=data.get("id",""),
                   created=str(data.get("created_at",""))[:10],
                   sources=sources, n_sources=len(sources))
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
        import re
        answer = re.sub(r'\*\*(.+?)\*\*', r'\1', answer)
        answer = re.sub(r'__(.+?)__', r'\1', answer)

    result = _maybe_file(answer, "answer")
    if isinstance(result, str) and result.startswith(str(OUT_DIR)):
        return _ok(f=result, n=len(answer))
    return _ok(f=result)

# ── source group ───────────────────────────────────────────────

def cmd_source_list(args):
    nb = _default_nb()
    out, err, rc = _run(["source", "list", "--json"] + _nb_args(nb), timeout=30)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "sources", ("id", "title", "type", "status"))
    return _ok(sources=items, n=count)

def cmd_source_add(args):
    usage = "usage: nlm.py source add [--type url|text|file|youtube] <value>"
    if not args:
        return _err(usage)
    stype = "url"
    value_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--type":
            i += 1
            if i < len(args):
                stype = args[i]
        else:
            value_parts.append(args[i])
        i += 1
    value = " ".join(value_parts)
    if not value:
        return _err(usage)
    out, err, rc = _run(["source", "add", "--json", value], timeout=120)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=data.get("id",""), title=data.get("title",""))
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
        return _ok(id=data.get("id",""), title=data.get("title",""),
                   type=data.get("type",""), status=data.get("status",""),
                   chars=data.get("character_count", 0))
    return _ok(raw=out)

def cmd_source_delete(args):
    if not args:
        return _err("usage: nlm.py source delete <id>")
    out, err, rc = _run(["source", "delete", args[0], "--json"], timeout=30)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_source_clean(args):
    out, err, rc = _run(["source", "clean", "--json"], timeout=60)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_source_add_research(args):
    usage = "usage: nlm.py source add-research [--mode fast|deep] [--no-wait] <query>"
    if not args:
        return _err(usage)
    mode = "fast"
    nowait = False
    nb = None
    query_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--mode":
            i += 1
            if i < len(args):
                mode = args[i]
        elif args[i] == "--no-wait":
            nowait = True
        elif args[i] == "-n" or args[i] == "--notebook":
            i += 1
            if i < len(args):
                nb = args[i]
        else:
            query_parts.append(args[i])
        i += 1
    query = " ".join(query_parts)
    if not query:
        return _err(usage)
    cmd = ["source", "add-research", "--mode", mode, "--json"]
    if nowait:
        cmd.append("--no-wait")
    cmd.extend(_nb_args(nb))
    cmd.append(query)
    out, err, rc = _run(cmd, timeout=90 if nowait else 600)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(status=data.get("status",""), task_id=data.get("task_id",""),
                   sources=data.get("sources",[]), n=len(data.get("sources",[])))
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
    usage = ("usage: nlm.py artifact generate <type> [--instructions <text>] [--kind note-backed|interactive]\n"
             "types: {}".format(", ".join(ARTIFACT_TYPES)))
    if not args:
        return _err(usage)
    atype = args[0]
    if atype not in ARTIFACT_TYPES:
        return _err("unknown type '{}'. Valid: {}".format(atype, ", ".join(ARTIFACT_TYPES)))
    instructions = None
    kind = None
    nb = None
    i = 1
    while i < len(args):
        if args[i] == "--instructions":
            i += 1
            if i < len(args):
                instructions = args[i]
        elif args[i] == "--kind":
            i += 1
            if i < len(args):
                kind = args[i]
        elif args[i] == "-n" or args[i] == "--notebook":
            i += 1
            if i < len(args):
                nb = args[i]
        i += 1

    cmd = ["generate", atype, "--json"]
    if instructions:
        cmd.extend(["--instructions", instructions])
    if kind:
        cmd.extend(["--kind", kind])
    cmd.extend(_nb_args(nb))
    out, err, rc = _run(cmd, timeout=120)
    if rc != 0:
        return _err(err or out[:500])
    data = _json_or_text(out)
    if isinstance(data, dict):
        note_id = data.get("note_id", "")
        mid = data.get("id", "")
        result = {"type": atype, "id": mid or note_id}
        if "mind_map" in data:
            result["mind_map"] = data["mind_map"]
        return _ok(**result)
    return _ok(raw=out)

def cmd_artifact_download(args):
    usage = ("usage: nlm.py artifact download <type> [--artifact <id>] [--format pdf|pptx] [--all] [--dry-run]\n"
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
        suggestions = [{"title": s.get("title",""), "description": s.get("description","")}
                       for s in data]
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
        return _ok(id=data.get("id",""), title=data.get("title",""),
                   type=data.get("type",""), status=data.get("status",""))
    return _ok(raw=out)

def cmd_artifact_delete(args):
    if not args:
        return _err("usage: nlm.py artifact delete <id>")
    out, err, rc = _run(["artifact", "delete", args[0], "--json"], timeout=30)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

# ── note group ──────────────────────────────────────────────────

def cmd_note_list(args):
    out, err, rc = _run(["note", "list", "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    items, count = _parse_list_result(out, "notes", ("id", "title", "content"), strip_date=False)
    clean = []
    for n in items:
        clean.append({"id": n.get("id",""), "title": n.get("title",""),
                       "preview": (n.get("content","") or "")[:80]})
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
    # note create takes content as positional arg, not --content
    cmd = ["note", "create", "--json"]
    if title:
        cmd.extend(["-t", title])
    cmd.append(content)
    out, err, rc = _run(cmd, timeout=30)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=data.get("id",""), title=data.get("title",""))
    return _ok(raw=out)

def cmd_note_get(args):
    if not args:
        return _err("usage: nlm.py note get <id>")
    out, err, rc = _run(["note", "get", "--json", args[0]], timeout=15)
    if rc != 0:
        return _err(err or out)
    data = _json_or_text(out)
    if isinstance(data, dict):
        return _ok(id=data.get("id",""), title=data.get("title",""),
                   content=data.get("content",""))
    return _ok(raw=out)

def cmd_note_save(args):
    if len(args) < 2:
        return _err("usage: nlm.py note save <id> <content>")
    nid = args[0]
    content = " ".join(args[1:])
    out, err, rc = _run(["note", "save", "--json", nid, content], timeout=30)
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
        return _ok(public=data.get("public",False), url=data.get("url",""),
                   view_level=data.get("view_level",""),
                   users=data.get("users",[]))
    return _ok(raw=out)

def cmd_share_public(args):
    if not args or args[0] not in ("enable", "disable"):
        return _err("usage: nlm.py share public enable|disable")
    out, err, rc = _run(["share", "public", "--{}".format(args[0]), "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_share_add(args):
    if len(args) < 2:
        return _err("usage: nlm.py share add <email> [--permission viewer|editor]")
    email = args[0]
    perm = "viewer"
    i = 1
    while i < len(args):
        if args[i] == "--permission":
            i += 1
            if i < len(args):
                perm = args[i]
        i += 1
    out, err, rc = _run(["share", "add", email, "--permission", perm, "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

def cmd_share_remove(args):
    if not args:
        return _err("usage: nlm.py share remove <email>")
    out, err, rc = _run(["share", "remove", args[0], "--json"], timeout=15)
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
    items, count = _parse_list_result(out, "turns", ("question", "answer"), strip_date=False)
    turns = []
    for t in items:
        turns.append({
            "question": (t.get("question","") or "")[:200],
            "answer_preview": (t.get("answer","") or "")[:200]
        })
    return _ok(turns=turns, n=count)

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
    """Refresh auth from browser cookies."""
    cookie_file = None
    if args:
        cookie_file = args[0]
    try:
        import browser_cookie3
    except ImportError:
        return _err("browser_cookie3 not installed. Run: pip install browser_cookie3")
    try:
        if cookie_file:
            cj = browser_cookie3.firefox(cookie_file=cookie_file)
        else:
            # Try Firefox first (WSL-friendly), fall back to Chrome
            try:
                cj = browser_cookie3.firefox()
            except Exception:
                cj = browser_cookie3.chrome()
        cookies = []
        for c in cj:
            if 'google' in (c.domain or '') and c.name:
                cookies.append({
                    "name": c.name, "value": c.value,
                    "domain": c.domain, "path": c.path or "/",
                    "expires": c.expires if (c.expires and c.expires > 0) else -1,
                    "secure": bool(c.secure), "httpOnly": True, "sameSite": "Lax"
                })
        STORAGE.parent.mkdir(parents=True, exist_ok=True)
        STORAGE.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2))
        return _ok(n_cookies=len(cookies))
    except Exception as e:
        return _err("auth init failed: {}".format(e))

def cmd_auth_doctor(args):
    out, err, rc = _run(["doctor", "--json"], timeout=15)
    if rc != 0:
        return _err(err or out)
    return _ok(raw=out)

# ── clear ───────────────────────────────────────────────────────

def cmd_clear(args):
    # clear doesn't accept --notebook; it operates on current context
    out, err, rc = _run(["clear"])
    if rc != 0:
        return _err(err or out)
    return _ok()

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
    "ask": {
        "ask": cmd_ask,
    },
    "source": {
        "list": cmd_source_list,
        "add": cmd_source_add,
        "guide": cmd_source_guide,
        "fulltext": cmd_source_fulltext,
        "get": cmd_source_get,
        "delete": cmd_source_delete,
        "clean": cmd_source_clean,
        "add-research": cmd_source_add_research,
    },
    "research": {
        "status": cmd_research_status,
        "wait": cmd_research_wait,
    },
    "artifact": {
        "list": cmd_artifact_list,
        "generate": cmd_artifact_generate,
        "download": cmd_artifact_download,
        "suggestions": cmd_artifact_suggestions,
        "get": cmd_artifact_get,
        "delete": cmd_artifact_delete,
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
}

USAGE = """Usage: nlm.py <group> <action> [args...]

Groups:
  notebook   create, rename, delete, list, use, status, summary, metadata
  ask        <question> [-p] [-n notebook] [--new]
  source     list, add, guide, fulltext, get, delete, clean, add-research
  research   status, wait
  artifact   list, generate, download, suggestions, get, delete
  note       list, create, get, save, rename, delete
  share      status, public, add, remove, view-level
  history    [--save] [--json] [--limit N] [--show-all]
  configure  [--mode MODE] [--persona TEXT] [--response-length LEN]
  auth       init [cookie_file], doctor
  clear      [notebook_id]

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
    single_actions = {"history": cmd_history, "configure": cmd_configure, "clear": cmd_clear, "ask": cmd_ask}

    if group in single_actions:
        print(single_actions[group](rest))
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
