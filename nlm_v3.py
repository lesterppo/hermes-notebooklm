#!/usr/bin/env python3
"""
NotebookLM agent CLI — thin wrapper around notebooklm-py.
Usage: echo "prompt" | nlm.py           # ask notebook (JSON output)
       nlm.py "prompt"                  # ask notebook
       nlm.py -p "prompt"               # plain text (no markdown)
       nlm.py -l                        # list notebooks
       nlm.py -s ID                     # set default notebook
       nlm.py --src                     # list sources
       nlm.py --src ID                  # get source full text
       nlm.py --guide ID                # AI source guide
       nlm.py --init                    # refresh auth from Firefox
       nlm.py --clear                   # start new conversation
Output: {"f":"answer","s":"done"} | {"e":"error","s":"err"}
"""
import sys, os, json, subprocess, pathlib

HOME = pathlib.Path.home()
NLM = str(HOME / ".local" / "bin" / "notebooklm")
CFG = HOME / ".hermes" / "nlm_cache" / "notebook.txt"
CFG.parent.mkdir(parents=True, exist_ok=True)
STORAGE = HOME / ".notebooklm" / "profiles" / "default" / "storage_state.json"

def _run(args, timeout=90):
    try:
        r = subprocess.run([NLM, "--quiet"] + args,
            capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 124

def init_auth():
    import browser_cookie3
    p = "REPLACE_WITH_YOUR_FIREFOX_COOKIES_PATH"
    cj = browser_cookie3.firefox(cookie_file=p)
    cookies = [{"name":c.name,"value":c.value,"domain":c.domain,"path":c.path or "/",
                "expires":c.expires if (c.expires and c.expires>0) else -1,
                "secure":bool(c.secure),"httpOnly":True,"sameSite":"Lax"}
               for c in cj if 'google' in c.domain and c.name and c.domain]
    STORAGE.parent.mkdir(parents=True, exist_ok=True)
    STORAGE.write_text(json.dumps({"cookies":cookies,"origins":[]}, indent=2))
    return len(cookies)

def ask(prompt, plain=False, notebook=None):
    """Ask notebook. Returns {f: answer, s: done|err}."""
    nb = notebook or (CFG.read_text().strip() if CFG.exists() else "YOUR_NOTEBOOK_ID")
    args = ["ask", "--notebook", nb, prompt]
    out, err, rc = _run(args, timeout=90)
    if rc != 0:
        return {"e": err or out[:200], "s": "err"}
    ans = []
    skip = ('resumed conversation:','continuing conversation:','conversation:','answer:','thinking:')
    for l in out.split('\n'):
        if l.lower().startswith(skip): continue
        if plain: l = l.replace('**','').replace('__','')
        l = l.replace('\\\\ge','≥').replace('\\\\le','≤')
        ans.append(l)
    return {"f": '\n'.join(ans).strip(), "s": "done"}

def main():
    import argparse
    p = argparse.ArgumentParser(description="NotebookLM agent CLI")
    p.add_argument("prompt", nargs="?", help="Question (stdin if piped)")
    p.add_argument("-p","--plain", action="store_true", help="Strip markdown from answer")
    p.add_argument("-l","--list", action="store_true", help="List notebooks")
    p.add_argument("-s","--save", help="Set default notebook ID")
    p.add_argument("--src", nargs="?", const="__list__", help="List sources, or get source full text by ID")
    p.add_argument("--guide", help="Get AI source guide by ID")
    p.add_argument("--init", action="store_true", help="Refresh auth from Firefox")
    p.add_argument("--clear", action="store_true", help="Start new conversation")
    p.add_argument("--status",action="store_true",help="Show current context")
    p.add_argument("-r","--raw", action="store_true", help="Raw text (no JSON wrapper)")
    args = p.parse_args()
    
    if args.init:
        n = init_auth()
        print(json.dumps({"s":"ok","n":n})); return
    if args.list:
        out,_,_ = _run(["list"]); print(out); return
    if args.save:
        CFG.parent.mkdir(parents=True, exist_ok=True)
        CFG.write_text(args.save)
        print(json.dumps({"s":"ok"})); return
    if args.src is not None:
        if args.src == "__list__":
            out,_,_ = _run(["source","list"])
        else:
            out,_,_ = _run(["source","fulltext",args.src], timeout=60)
        print(out); return
    if args.guide:
        out,_,_ = _run(["source","guide",args.guide], timeout=60)
        print(out); return
    if args.clear:
        _run(["clear"]); print(json.dumps({"s":"ok"})); return
    if args.status:
        out,_,_ = _run(["status"]); print(out); return
    
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        p.print_help(); return
    
    result = ask(prompt, plain=args.plain)
    if args.raw:
        print(result.get("f", json.dumps(result)))
    else:
        print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
