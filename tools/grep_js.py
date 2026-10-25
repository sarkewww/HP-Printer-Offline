"""Grep JS bundles for print/scan option enums and dump surrounding context."""
import os
import re
import sys

ROOT = r"C:\Program Files\WindowsApps\AD2F1837.myHP_61.52637.14262.0_x64__v10z8vjag6ke6\Weblets\webapps\root-web-mfe"

PATTERNS = sys.argv[1:] or [
    r"print-quality", r"print-color-mode", r"fitToPage", r"borderless",
    r'"copies"', r"mediaSize", r"sides",
]

rx = re.compile("|".join(PATTERNS), re.I)

def main():
    seen = set()
    files = []
    for dirpath, _, names in os.walk(ROOT):
        for n in names:
            if n.endswith(".js"):
                p = os.path.join(dirpath, n)
                try:
                    if os.path.getsize(p) < 2000:
                        continue
                except OSError:
                    continue
                files.append(p)
    files.sort(key=lambda p: -os.path.getsize(p))
    # only look at printer-related bundles first
    def score(p):
        s = 0
        for k in ("print", "scan", "toolkit", "device"):
            if k in p.lower():
                s += 1
        return -s
    files.sort(key=lambda p: (score(p), -os.path.getsize(p)))
    for p in files[:400]:
        try:
            t = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        hits = list(rx.finditer(t))
        if not hits:
            continue
        rel = p[len(ROOT) + 1:]
        print(f"\n===== {rel}  ({len(hits)} hits, {len(t)//1024} KiB)")
        for m in hits[:6]:
            a = max(0, m.start() - 160)
            b = min(len(t), m.end() + 220)
            snip = t[a:b].replace("\n", " ")
            key = snip[:80]
            if key in seen:
                continue
            seen.add(key)
            print("  ..." + snip + "...")

if __name__ == "__main__":
    main()
