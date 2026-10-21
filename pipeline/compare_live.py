#!/usr/bin/env python3
"""Compare the page just built with the page that is live, and list what differs."""
import json, re, sys, urllib.request

def data(text):
    return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', text, re.S).group(1))

live = data(urllib.request.urlopen("https://snfsales.abc-ri.org/", timeout=90).read().decode("utf-8", "replace"))
new = data(open(sys.argv[1] if len(sys.argv) > 1 else "index.html").read())
diffs = []
def walk(a, b, path=""):
    if len(diffs) > 400: return
    if path in ("/meta/built", "/meta/updated"): return
    if type(a) is not type(b): diffs.append(f"{path}: type {type(a).__name__} vs {type(b).__name__}"); return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a: diffs.append(f"{path}/{k}: only in new")
            elif k not in b: diffs.append(f"{path}/{k}: only in live")
            else: walk(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list):
        if len(a) != len(b): diffs.append(f"{path}: {len(a)} items live vs {len(b)} new")
        for i in range(min(len(a), len(b))): walk(a[i], b[i], f"{path}[{i}]")
    elif a != b:
        diffs.append(f"{path}: live {a!r} vs new {b!r}")
walk(live, new)
import collections, re as _re
groups = collections.Counter(_re.sub(r"\[\d+\]", "[]", d.split(":")[0]) for d in diffs)
print(f"{len(diffs)} difference(s) between the live page and this build")
for g, n in groups.most_common(6): print(f"  {g}: {n}")
for d in diffs[:3]: print("  example: " + d)
