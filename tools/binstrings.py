"""Extract printable strings (ASCII + UTF-16LE) from a PE/binary and grep them.

Usage:
    python binstrings.py <file> [--grep PATTERN ...] [--min 6] [--out FILE]
"""
import re
import sys
import os

def strings(path, minlen=6):
    data = open(path, "rb").read()
    out = []
    # ASCII
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, data):
        out.append(m.group().decode("ascii", "replace"))
    # UTF-16LE
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){%d,}" % minlen, data):
        out.append(m.group().decode("utf-16le", "replace"))
    return out

def main():
    path = sys.argv[1]
    pats = []
    minlen = 6
    outfile = None
    i = 2
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--grep":
            i += 1
            pats.append(sys.argv[i])
        elif a == "--min":
            i += 1
            minlen = int(sys.argv[i])
        elif a == "--out":
            i += 1
            outfile = sys.argv[i]
        i += 1

    ss = strings(path, minlen)
    uniq = list(dict.fromkeys(ss))
    print(f"{os.path.basename(path)}: {len(ss)} strings, {len(uniq)} unique")
    if pats:
        rx = re.compile("|".join(pats), re.I)
        hits = [s for s in uniq if rx.search(s)]
        print(f"matched {len(hits)}")
        for s in hits[:400]:
            print(s)
    if outfile:
        with open(outfile, "w", encoding="utf-8") as f:
            f.write("\n".join(uniq))
        print(f"-> {outfile}")

if __name__ == "__main__":
    main()
