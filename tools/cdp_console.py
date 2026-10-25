"""用 CDP 打开页面并抓取控制台报错 / 未捕获异常 / 关键元素是否存在。

用法： python cdp_console.py <url> [wait_seconds]
"""
import json
import subprocess
import sys
import time
import urllib.request

import websocket

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
PORT = 9333


def start_edge(profile):
    exe = next((p for p in EDGE_CANDIDATES if __import__("os").path.exists(p)), None)
    if not exe:
        raise SystemExit("Edge not found")
    proc = subprocess.Popen([
        exe, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
        f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
        "--remote-allow-origins=*", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1) as r:
                if r.status == 200:
                    return proc
        except Exception:
            continue
    proc.kill()
    raise SystemExit("Edge CDP not ready")


def main():
    url = sys.argv[1]
    wait = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    profile = r"C:\Users\user\AppData\Local\Temp\opencode\cdp-profile"
    proc = start_edge(profile)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=3) as r:
            targets = json.load(r)
        page = next(t for t in targets if t.get("type") == "page")
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10,
                                         origin=f"http://127.0.0.1:{PORT}")
        mid = [0]

        def send(method, params=None):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
            return mid[0]

        send("Runtime.enable")
        send("Log.enable")
        send("Page.enable")
        send("Page.navigate", {"url": url})

        problems = []
        deadline = time.time() + wait
        ws.settimeout(1.0)
        while time.time() < deadline:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                continue
            method = msg.get("method")
            params = msg.get("params") or {}
            if method == "Runtime.exceptionThrown":
                d = params.get("exceptionDetails") or {}
                exc = d.get("exception") or {}
                problems.append(("EXCEPTION", d.get("text", ""), exc.get("description", "")))
            elif method == "Log.entryAdded":
                e = params.get("entry") or {}
                if e.get("level") in ("error", "warning"):
                    problems.append((e.get("level", "").upper(), e.get("text", ""), e.get("url", "")))
            elif method == "Runtime.consoleAPICalled":
                if params.get("type") == "error":
                    args = [str(a.get("value", a.get("description", ""))) for a in params.get("args", [])]
                    problems.append(("CONSOLE", " ".join(args), ""))

        # 关键元素探针
        probe = """
        (() => {
          const q = (s) => document.querySelectorAll(s).length;
          return JSON.stringify({
            view: q('#view > *'),
            editPanel: q('.edit-panel'),
            editHidden: (document.querySelector('.edit-panel')||{}).hidden,
            editButtons: q('.edit-panel button'),
            rotateBtn: q('.edit-tools button'),
            sliders: q('.edit-sliders input[type=range]'),
            scanForm: q('.scan-options, .options-card, .scan-side'),
            scanSwitches: q('input[type=checkbox]'),
            selectTriggers: q('.select-trigger'),
            bodyText: (document.body.innerText || '').slice(0, 200)
          });
        })()
        """
        send("Runtime.evaluate", {"expression": probe, "returnByValue": True})
        dom = ""
        t0 = time.time()
        while time.time() - t0 < 3:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                continue
            if msg.get("id") == mid[0]:
                dom = ((msg.get("result") or {}).get("result") or {}).get("value") or ""
                break

        print("URL:", url)
        print("PROBLEMS:", len(problems))
        for p in problems[:25]:
            print(" -", p[0], "|", (p[1] or "")[:200], "|", (p[2] or "")[:200])
        print("DOM:", dom)
        ws.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
