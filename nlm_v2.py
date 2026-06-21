#!/usr/bin/env python3
"""
NotebookLM v2 CLI — Page server client.
Usage: echo "prompt" | nlm_v2.py
       nlm_v2.py "prompt"
       
Requires nlm_v2_server.py running on :9874.
"""
import sys, os, json, time, subprocess, pathlib, urllib.request

HOME = pathlib.Path.home()
PORT = 9874
CFG = HOME / ".hermes" / "nlm_cache" / "notebook.txt"
CFG.parent.mkdir(parents=True, exist_ok=True)

def _health():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3)
        return True
    except: return False

def _ensure_server():
    if _health(): return
    server = HOME / ".hermes" / "scripts" / "nlm_server.py"
    if not server.exists():
        server = pathlib.Path(__file__).parent / "nlm_v2_server.py"
    subprocess.Popen([sys.executable, str(server)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(20):
        time.sleep(3)
        if _health(): return
    raise RuntimeError("Server failed to start")

def ask(prompt, timeout=120):
    _ensure_server()
    data = json.dumps({"prompt": prompt}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/query", data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {"e": str(e), "s": "err"}

def main():
    import argparse
    p = argparse.ArgumentParser(description="NotebookLM v2 CLI (page server)")
    p.add_argument("prompt", nargs="?", help="Question")
    p.add_argument("-s", "--save", help="Set default notebook ID")
    p.add_argument("--health", action="store_true")
    p.add_argument("-r", "--raw", action="store_true")
    args = p.parse_args()
    
    if args.save:
        CFG.parent.mkdir(parents=True, exist_ok=True)
        CFG.write_text(args.save)
        print(json.dumps({"s":"ok"}))
        return
    if args.health:
        print(json.dumps({"s":"ok" if _health() else "down"}))
        return
    
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        p.print_help(); return
    
    result = ask(prompt)
    if args.raw:
        print(result.get("f", json.dumps(result)))
    else:
        print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
