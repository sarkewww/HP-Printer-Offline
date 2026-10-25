"""用 Edge 的 CDP 抓页面运行时错误 + DOM 关键状态。

用法:
    python tools/cdp_probe.py "#/print" "#/scan"
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
PORT = 9333


def find_edge():
    for path in EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    raise SystemExit("Edge not found")


def start_edge(profile):
    proc = subprocess.Popen(
        [
            find_edge(),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=0.5):
                return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise SystemExit("Edge devtools did not start")


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=15)
        self.seq = 0
        self.events = []

    def send(self, method, **params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        return self.seq

    def drain(self, seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            self.ws.settimeout(max(0.05, end - time.time()))
            try:
                raw = self.ws.recv()
            except Exception:
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if "method" in msg:
                self.events.append(msg)

    def call(self, method, **params):
        mid = self.send(method, **params)
        end = time.time() + 20
        while time.time() < end:
            self.ws.settimeout(0.5)
            try:
                raw = self.ws.recv()
            except Exception:
                continue
            msg = json.loads(raw)
            if msg.get("id") == mid:
                return msg
            if "method" in msg:
                self.events.append(msg)
        return {}

    def eval(self, expr):
        res = self.call(
            "Runtime.evaluate",
            expression=expr,
            returnByValue=True,
            awaitPromise=True,
        )
        return (res.get("result", {}).get("result", {}) or {}).get("value")


def main():
    routes = sys.argv[1:] or ["#/print"]
    profile = os.path.join(tempfile.gettempdir(), "hp-cdp-profile")
    proc = start_edge(profile)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=5) as r:
            targets = json.load(r)
        page = next(t for t in targets if t.get("type") == "page")
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        cdp.call("Log.enable")
        cdp.call("Page.enable")

        for route in routes:
            cdp.events.clear()
            cdp.call("Page.navigate", url=f"http://127.0.0.1:8791/{route}")
            cdp.drain(5.0)
            print(f"\n===== {route} =====")
            errors = []
            for ev in cdp.events:
                m = ev.get("method")
                p = ev.get("params", {})
                if m == "Runtime.exceptionThrown":
                    d = p.get("exceptionDetails", {})
                    text = d.get("exception", {}).get("description") or d.get("text")
                    errors.append(f"EXCEPTION: {text}")
                elif m == "Log.entryAdded":
                    e = p.get("entry", {})
                    if e.get("level") in ("error", "warning"):
                        errors.append(f"{e.get('level').upper()}: {e.get('text')}")
                elif m == "Runtime.consoleAPICalled":
                    if p.get("type") in ("error", "warning"):
                        args = " ".join(
                            str(a.get("value") or a.get("description") or "")
                            for a in p.get("args", [])
                        )
                        errors.append(f"CONSOLE {p.get('type')}: {args}")
            if errors:
                for line in dict.fromkeys(errors):
                    print("  " + line)
            else:
                print("  (no errors)")

            facts = cdp.eval(
                """(() => {
                  const q = (s) => document.querySelectorAll(s).length;
                  const view = document.getElementById('view');
                  return {
                    hash: location.hash,
                    viewChildren: view ? view.children.length : -1,
                    modebar: q('.print-modebar'),
                    dropzone: q('.dropzone'),
                    editPanel: q('.edit-panel'),
                    editHidden: (() => { const e = document.querySelector('.edit-panel'); return e ? e.hidden : null; })(),
                    optionsGroups: q('.print-options .option-group'),
                    scanRoot: q('.view-scan'),
                    scanOptions: q('.scan-options'),
                    navItems: q('.nav-item'),
                    bodyText: (document.body.innerText || '').slice(0, 160).replace(/\\s+/g, ' ')
                  };
                })()"""
            )
            print("  DOM: " + json.dumps(facts, ensure_ascii=False))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
