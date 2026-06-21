#!/usr/bin/env python3
"""
NotebookLM v2 Page Server — Daemonized Chromium browser for NotebookLM.
Usage: python3 nlm_v2_server.py [-p PORT] [-n NOTEBOOK_ID]
       python3 nlm_v2_server.py --stop
       python3 nlm_v2_server.py --foreground  (debug mode)

Architecture:
  Agent → nlm_v2.py (HTTP POST) → :9874 → Playwright → notebooklm.google.com

Requires: playwright, browser_cookie3, chromium
Setup:    playwright install chromium
          Ensure Firefox/Chrome is signed into notebooklm.google.com
"""
import sys, os, json, time, pathlib, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

HOME = pathlib.Path.home()
PORT = 9874
PID_FILE = HOME / ".hermes" / "nlm_server.pid"
NOTEBOOK_ID = "YOUR_NOTEBOOK_ID"  # Replace with your default notebook

# Browser cookie profile path — replace with your Firefox cookies.sqlite
COOKIE_DB = "REPLACE_WITH_YOUR_FIREFOX_COOKIES_PATH"

_pg = _ctx = _br = _pw = None

def init_browser():
    """Launch Chromium, auth via browser cookies, navigate to notebook."""
    global _pw, _br, _ctx, _pg
    import browser_cookie3
    from playwright.sync_api import sync_playwright
    
    cj = browser_cookie3.firefox(cookie_file=COOKIE_DB)
    cookies = []
    for c in cj:
        if 'google' in c.domain:
            ck = {'name': c.name, 'value': c.value, 'domain': c.domain,
                  'path': c.path or '/'}
            if c.secure: ck['secure'] = True
            cookies.append(ck)
    
    _pw = sync_playwright().start()
    _br = _pw.chromium.launch(headless=True,
        args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
    _ctx = _br.new_context(viewport={"width": 1920, "height": 1080})
    _ctx.add_cookies(cookies)
    _pg = _ctx.new_page()
    
    _pg.goto(f"https://notebooklm.google.com/notebook/{NOTEBOOK_ID}",
             wait_until="domcontentloaded", timeout=30000)
    _pg.wait_for_timeout(8000)

def query(prompt, timeout=90):
    """Type prompt into NotebookLM chat, wait for answer, extract text."""
    global _pg
    
    # Ensure page ready
    try: _pg.wait_for_selector('textarea', timeout=10000)
    except: return "Error: page not loaded"
    
    ta = _pg.locator('textarea').last
    try: ta.click(timeout=5000)
    except: return "Error: cannot interact with textarea"
    
    _pg.wait_for_timeout(500)
    ta.fill(prompt)
    _pg.wait_for_timeout(300)
    _pg.keyboard.press("Enter")
    
    # Wait for response (poll every 3s, exit on 6s stability)
    deadline = time.time() + timeout
    last_body, stable, body = "", 0, ""
    
    while time.time() < deadline:
        _pg.wait_for_timeout(3000)
        try: body = _pg.inner_text("body")
        except: continue
        
        thinking = any(x in body for x in [
            '思考中','Looking for','Pinpoint','Organizing',
            'Reading','Analyzing','Evaluating','Examining','Integrating'])
        
        if not thinking and len(body) > 2000:
            if body == last_body:
                stable += 1
                if stable >= 3: break
            else:
                last_body, stable = body, 0
    
    if not body: body = _pg.inner_text("body")
    
    # Extract answer (after prompt text, before UI chrome)
    lines = body.split('\n')
    prompt_short = prompt[:40]
    ans_start = 0
    for i, line in enumerate(lines):
        if prompt_short in line:
            ans_start = i + 1
            break
    
    ans = []
    stop = {'keep','儲存筆記','copy_all','thumb_up','thumb_down',
            '20 個來源','arrow_forward','工作室','stop'}
    for i in range(ans_start, len(lines)):
        l = lines[i].strip()
        if l in stop: break
        if l.startswith(('keep','thumb_','more_horiz','今天')): break
        if l and len(l) > 3: ans.append(l)
    
    return '\n'.join(ans).strip()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/health':
            self._json(200, {"status": "ok"})
        elif path == '/stop':
            self._json(200, {"status": "stopping"})
            os._exit(0)
    
    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')
        
        if path == '/query':
            try:
                data = json.loads(body) if body.startswith('{') else {}
            except:
                data = {}
            if not data:
                data = {k: v[0] for k, v in parse_qs(body).items()}
            prompt = data.get('prompt', '')
            if not prompt:
                self._json(400, {"e": "No prompt", "s": "err"})
                return
            # Switch notebook if specified
            nb = data.get('notebook', '')
            if nb and nb not in (_pg.url if _pg else ''):
                _pg.goto(f"https://notebooklm.google.com/notebook/{nb}",
                        wait_until="domcontentloaded", timeout=30000)
                _pg.wait_for_timeout(6000)
            try:
                answer = query(prompt)
                self._json(200, {"f": answer, "s": "done"})
            except Exception as e:
                self._json(500, {"e": str(e), "s": "err"})
    
    def _json(self, code, data):
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass
    
    def log_message(self, fmt, *args): pass

def main():
    import argparse
    p = argparse.ArgumentParser(description="NotebookLM v2 Page Server")
    p.add_argument('-p','--port',type=int,default=PORT)
    p.add_argument('-n','--notebook')
    p.add_argument('--stop',action='store_true')
    p.add_argument('--foreground',action='store_true',help="Don't daemonize")
    args = p.parse_args()
    
    global NOTEBOOK_ID
    if args.notebook: NOTEBOOK_ID = args.notebook
    
    if args.stop:
        if PID_FILE.exists():
            try:
                os.kill(int(PID_FILE.read_text().strip()), 15)
                PID_FILE.unlink()
                print("Stopped")
            except ProcessLookupError:
                PID_FILE.unlink()
                print("Stale PID removed")
        else:
            print("Not running")
        return
    
    # Check port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('127.0.0.1', args.port)); s.close()
    except:
        print(f"Port {args.port} in use", file=sys.stderr); sys.exit(1)
    
    # Daemonize
    if not args.foreground:
        if os.fork(): os._exit(0)
        os.setsid()
        if os.fork(): os._exit(0)
        fd = os.open(os.devnull, os.O_RDWR)
        for f in (0,1,2): os.dup2(fd, f)
        os.close(fd)
    
    init_browser()
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    
    server = HTTPServer(('127.0.0.1', args.port), Handler)
    server.serve_forever()

if __name__ == "__main__":
    main()
