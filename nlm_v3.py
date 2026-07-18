#!/usr/bin/env python3
"""
NotebookLM agent CLI — thin wrapper around notebooklm-py.
Usage: echo "prompt" | nlm.py           # ask notebook (JSON output)
       nlm.py "prompt"                  # ask notebook
       nlm.py -p "prompt"               # plain text (no markdown)
       nlm.py -r "prompt"               # raw text (no JSON wrapper)
       nlm.py -l                        # list notebooks
       nlm.py -s ID                     # set default notebook
       nlm.py --new                     # start fresh conversation
       nlm.py --clear                   # clear the current conversation thread
       nlm.py --src                     # list sources
       nlm.py --src ID                  # get source full text
       nlm.py --guide ID               # AI source guide
       nlm.py --summary [--topics]      # AI notebook summary
       nlm.py --metadata               # notebook + sources metadata
       nlm.py --history [--save]        # conversation history (save as note)
       nlm.py --note TEXT -t TITLE      # create a note
       nlm.py --note-list              # list notes
       nlm.py --artifact               # list Studio artifacts
       nlm.py --gen TYPE TOPIC ...      # generate a Studio artifact
                                         #   forwards extra args to
                                         #   `notebooklm generate TYPE`
                                         #   e.g. --gen report "topic"
                                         #        --gen mind-map --instructions "topic"
       nlm.py --src-add URL|TEXT       # add a source
       nlm.py --src-del ID             # delete a source
       nlm.py --src-clean              # remove dup/error/stale sources
       nlm.py --share                  # sharing status
       nlm.py --research               # Deep Research status
       nlm.py --init                   # refresh auth from Firefox

Output envelope for agent parsing:
  {"f": "answer text", "s": "done"} | {"e": "error", "s": "err"}
Raw (-r), list (-l), and structured commands print the underlying output
verbatim (notebooklm-py's own rich formatting) so the agent can read it
directly.

Verified against the "Gemini notebook" rebrand (notebooklm.google.com
unchanged) with notebooklm-py 0.7.2/0.7.3.
"""
import sys, os, json, subprocess, pathlib, argparse

HOME = pathlib.Path.home()
NLM = str(HOME / ".local" / "bin" / "notebooklm")
CFG = HOME / ".hermes" / "nlm_cache" / "notebook.txt"
CFG.parent.mkdir(parents=True, exist_ok=True)
STORAGE = HOME / ".notebooklm" / "profiles" / "default" / "storage_state.json"


def _run(args, timeout=120, as_bytes=False):
    """Run the notebooklm binary; return (stdout, stderr, rc)."""
    try:
        r = subprocess.run([NLM, "--quiet"] + args,
                           capture_output=True, text=(not as_bytes),
                           timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 124


def init_auth():
    import browser_cookie3
    p = "REPLACE_WITH_YOUR_FIREFOX_COOKIES_PATH"
    cj = browser_cookie3.firefox(cookie_file=p)
    cookies = [{"name": c.name, "value": c.value, "domain": c.domain,
                "path": c.path or "/",
                "expires": c.expires if (c.expires and c.expires > 0) else -1,
                "secure": bool(c.secure), "httpOnly": True, "sameSite": "Lax"}
               for c in cj if 'google' in c.domain and c.name and c.domain]
    STORAGE.parent.mkdir(parents=True, exist_ok=True)
    STORAGE.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2))
    return len(cookies)


def _default_nb():
    return CFG.read_text().strip() if CFG.exists() else "YOUR_NOTEBOOK_ID"


def _sync_context(nb):
    """Set notebooklm-py's active notebook context (persisted) so every
    subcommand resolves the right notebook without per-command --notebook
    placement quirks. Idempotent; failures are non-fatal."""
    if not nb or nb == "YOUR_NOTEBOOK_ID":
        return
    try:
        subprocess.run([NLM, "use", nb],
                       capture_output=True, text=True, timeout=30)
    except Exception:
        pass


def ask(prompt, plain=False):
    """Ask notebook. Returns {f: answer, s: done|err}.

    Relies on notebooklm-py's active context (set via _sync_context)."""
    args = ["ask", prompt]
    out, err, rc = _run(args, timeout=120)
    if rc != 0:
        return {"e": err or out[:200], "s": "err"}
    ans = []
    skip = ('resumed conversation:', 'continuing conversation:',
            'conversation:', 'answer:', 'thinking:')
    for line in out.split('\n'):
        if line.lower().startswith(skip):
            continue
        if plain:
            line = line.replace('**', '').replace('__', '')
        line = line.replace('\\\\ge', '≥').replace('\\\\le', '≤')
        ans.append(line)
    return {"f": '\n'.join(ans).strip(), "s": "done"}


def main():
    p = argparse.ArgumentParser(description="NotebookLM agent CLI")
    p.add_argument("prompt", nargs="?", help="Question (stdin if piped)")
    p.add_argument("-p", "--plain", action="store_true",
                   help="Strip markdown from answer")
    p.add_argument("-l", "--list", action="store_true", help="List notebooks")
    p.add_argument("-s", "--save", help="Set default notebook ID")
    p.add_argument("--new", action="store_true",
                   help="Start a fresh conversation (discard current thread)")
    p.add_argument("--src", nargs="?", const="__list__",
                   help="List sources, or get source full text by ID")
    p.add_argument("--guide", help="Get AI source guide by ID")
    p.add_argument("--summary", action="store_true",
                   help="AI-generated notebook summary")
    p.add_argument("--topics", action="store_true",
                   help="Include suggested topics (with --summary)")
    p.add_argument("--metadata", action="store_true",
                   help="Notebook metadata + sources list")
    p.add_argument("--history", action="store_true",
                   help="Conversation history (or --save as note)")
    p.add_argument("--note", help="Create a note with this text (-t for title)")
    p.add_argument("--note-list", action="store_true", help="List notes")
    p.add_argument("--artifact", action="store_true",
                   help="List generated Studio artifacts")
    p.add_argument("--gen", nargs="+", metavar=("TYPE", "TOPIC"),
                   help="Generate Studio artifact: --gen TYPE TOPIC ...")
    p.add_argument("--src-add", help="Add a source (URL, file path, or text)")
    p.add_argument("--src-del", help="Delete a source by ID")
    p.add_argument("--src-clean", action="store_true",
                   help="Remove duplicate/error/stale sources")
    p.add_argument("--share", action="store_true", help="Sharing status")
    p.add_argument("--research", action="store_true",
                   help="Deep Research status for current notebook")
    p.add_argument("--init", action="store_true",
                   help="Refresh auth from Firefox")
    p.add_argument("--clear", action="store_true",
                   help="Clear the current conversation thread")
    p.add_argument("--status", action="store_true", help="Show current context")
    p.add_argument("-r", "--raw", action="store_true",
                   help="Raw text (no JSON wrapper)")
    p.add_argument("-n", "--notebook", help="Operate on a specific notebook ID")
    p.add_argument("--json-out", action="store_true",
                   help="Request JSON from notebooklm-py where supported")
    p.add_argument("--save-as-note", action="store_true",
                   help="Save the next ask answer as a note")
    p.add_argument("-t", "--title", help="Title for --note / --history --save")
    args = p.parse_args()

    # Resolve the active notebook: explicit -n wins, else the saved default.
    nb = args.notebook or _default_nb()

    # Auth refresh
    if args.init:
        n = init_auth()
        print(json.dumps({"s": "ok", "n": n}))
        return

    # Default notebook context
    if args.save:
        CFG.write_text(args.save)
        _sync_context(args.save)
        print(json.dumps({"s": "ok"}))
        return
    if args.clear:
        # Reset the server-side conversation thread (notebooklm clear).
        # Does NOT delete the saved default notebook.
        out, err, rc = _run(["clear"], timeout=30)
        print(json.dumps({"s": "ok" if rc == 0 else "err",
                           "e": (err or out)[:200] if rc != 0 else None}))
        return

    # Sync notebooklm-py's active context so every subcommand below resolves
    # the right notebook without per-command --notebook placement quirks.
    _sync_context(nb)

    # Read-only / structured commands route straight to notebooklm-py and
    # print its native output (rich tables / JSON) so the agent can parse.
    if args.list:
        out, _, _ = _run(["list"])
        print(out)
        return

    if args.status:
        out, _, _ = _run(["status"])
        print(out)
        return

    if args.summary:
        cmd = ["summary"] + (["--topics"] if args.topics else [])
        if args.json_out:
            cmd += ["--json"]
        out, err, rc = _run(cmd, timeout=120)
        print(out or err)
        return

    if args.metadata:
        cmd = ["metadata"] + (["--json"] if args.json_out else [])
        out, err, rc = _run(cmd, timeout=120)
        print(out or err)
        return

    if args.history:
        cmd = ["history"]
        if args.save:
            cmd += ["--save"]
            if args.title:
                cmd += ["--note-title", args.title]
        if args.json_out:
            cmd += ["--json"]
        out, err, rc = _run(cmd, timeout=120)
        print(out or err)
        return

    if args.note is not None:
        cmd = ["note", "create", args.note]
        if args.title:
            cmd += ["-t", args.title]
        if args.json_out:
            cmd += ["--json"]
        out, err, rc = _run(cmd, timeout=60)
        print(out or err)
        return

    if args.note_list:
        cmd = ["note", "list"] + (["--json"] if args.json_out else [])
        out, err, rc = _run(cmd, timeout=60)
        print(out or err)
        return

    if args.artifact:
        cmd = ["artifact", "list"] + (["--json"] if args.json_out else [])
        out, err, rc = _run(cmd, timeout=120)
        print(out or err)
        return

    if args.gen:
        # --gen TYPE TOPIC [extra args...]
        gtype = args.gen[0]
        rest = args.gen[1:]
        cmd = ["generate", gtype] + rest
        out, err, rc = _run(cmd, timeout=300)
        print(out or err)
        return

    if args.src is not None:
        if args.src == "__list__":
            out, err, rc = _run(["source", "list"], timeout=60)
        else:
            out, err, rc = _run(["source", "fulltext", args.src], timeout=120)
        print(out or err)
        return

    if args.guide:
        out, err, rc = _run(["source", "guide", args.guide], timeout=120)
        print(out or err)
        return

    if args.src_add:
        cmd = ["source", "add", args.src_add]
        if args.json_out:
            cmd += ["--json"]
        out, err, rc = _run(cmd, timeout=120)
        print(out or err)
        return

    if args.src_del:
        out, err, rc = _run(["source", "delete", args.src_del, "-y"], timeout=60)
        print(out or err)
        return

    if args.src_clean:
        out, err, rc = _run(["source", "clean"], timeout=120)
        print(out or err)
        return

    if args.share:
        out, err, rc = _run(["share", "status"], timeout=60)
        print(out or err)
        return

    if args.research:
        out, err, rc = _run(["research", "status"], timeout=60)
        print(out or err)
        return

    # Ask (the default action)
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        p.print_help()
        return

    if args.new:
        _run(["clear"], timeout=30)  # reset server-side thread

    if args.save_as_note:
        out, err, rc = _run(["ask", "--save-as-note", prompt], timeout=120)
        print(out or err)
        return

    result = ask(prompt, plain=args.plain)
    if args.raw:
        print(result.get("f", json.dumps(result)))
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
