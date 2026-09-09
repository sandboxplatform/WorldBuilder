#!/usr/bin/env python3
"""Sanity-check catalog.json: unique ids, every path resolves, no stray tokens."""
import json, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
base = os.path.join(ROOT, cat["root"])
assets = cat["assets"]

ids = collections.Counter(e["id"] for e in assets)
dupes = [i for i, n in ids.items() if n > 1]
missing = [(e["id"], p) for e in assets for p in e["paths"].values()
           if not os.path.exists(os.path.join(base, p))]
dirty = [e["id"] for e in assets if re.search(r"\d+xx?\d+|_png$|__", e["id"])]
nopx = [e["id"] for e in assets if not e["px"]]

fails = 0
for label, bad in (("duplicate ids", dupes), ("missing files", missing),
                   ("ids with stray tokens", dirty), ("assets with no dimensions", nopx)):
    print(f"{label}: {len(bad)}")
    for b in bad[:5]:
        print("   ", b)
    fails += len(bad)

# coverage: how many source PNGs are reachable through the catalog
indexed = {p for e in assets for p in e["paths"].values()}
on_disk = {os.path.relpath(os.path.join(dp, fn), base)
           for dp, _, fs in os.walk(base) for fn in fs if fn.lower().endswith(".png")}
print(f"\nPNGs on disk: {len(on_disk)}")
print(f"PNGs referenced by the catalog: {len(indexed)}")
print(f"deliberately unindexed (alt shading / legacy / rpgmaker): {len(on_disk - indexed)}")
print(f"catalog paths not on disk: {len(indexed - on_disk)}")
print(f"\nlogical assets: {len(assets)}")
sys.exit(1 if fails else 0)
