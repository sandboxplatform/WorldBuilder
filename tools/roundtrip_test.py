#!/usr/bin/env python3
"""
Round-trip test: Tiled -> neutral -> Tiled -> neutral, and compare the two
neutral maps. This is the acceptance test for the format and the addressing --
if a real hand-built map survives it, the format is expressive enough and GID
resolution is correct in both directions.

Comparing the neutral forms (rather than the Tiled JSON) is deliberate: tileset
ordering, gid numbering, object ids and unused tileset declarations are all free
choices of the exporter and carry no meaning.

    python tools/roundtrip_test.py ../WaterCooler/public/maps/*.json
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(script, *args):
    r = subprocess.run([PY, os.path.join(HERE, script), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def normalise(m):
    """Strip anything an exporter is free to choose differently."""
    out = {"tile": m["tile"], "size": m["size"], "layers": []}
    for L in sorted(m["layers"], key=lambda L: L["name"]):
        if L["role"] == "terrain":
            # compare resolved refs per cell, not palette indices
            pal = L["palette"]
            out["layers"].append({
                "name": L["name"], "role": "terrain",
                "cells": [[None if v == -1 else pal[v] for v in row] for row in L["grid"]]})
        else:
            out["layers"].append({
                "name": L["name"], "role": "objects",
                "placements": sorted(
                    [[p["id"], p["at"][0], p["at"][1], p.get("flip", "")]
                     for p in L["placements"]])})
    for k in ("collisions", "spawns", "pois", "regions"):
        v = m.get(k, [])
        out[k] = sorted(json.dumps(x, sort_keys=True) for x in v)
    return out


def diff(a, b):
    """Human-readable differences between two normalised maps."""
    problems = []
    if a["size"] != b["size"] or a["tile"] != b["tile"]:
        problems.append(f"size/tile differ: {a['tile']}px {a['size']} vs {b['tile']}px {b['size']}")
    la = {L["name"]: L for L in a["layers"]}
    lb = {L["name"]: L for L in b["layers"]}
    for name in sorted(set(la) | set(lb)):
        if name not in la or name not in lb:
            problems.append(f"layer {name!r} only in {'A' if name in la else 'B'}")
            continue
        A, B = la[name], lb[name]
        if A["role"] != B["role"]:
            problems.append(f"layer {name!r} role {A['role']} vs {B['role']}")
        elif A["role"] == "terrain":
            bad = sum(1 for ra, rb in zip(A["cells"], B["cells"])
                      for ca, cb in zip(ra, rb) if ca != cb)
            if bad:
                problems.append(f"layer {name!r}: {bad} cells differ")
        elif A["placements"] != B["placements"]:
            sa, sb = set(map(tuple, A["placements"])), set(map(tuple, B["placements"]))
            problems.append(f"layer {name!r}: {len(sa - sb)} only in A, {len(sb - sa)} only in B")
    for k in ("collisions", "spawns", "pois", "regions"):
        if a[k] != b[k]:
            problems.append(f"{k}: {len(a[k])} vs {len(b[k])}")
    return problems


def main():
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    tmp = tempfile.mkdtemp(prefix="wb_rt_")
    passed = failed = 0
    for p in paths:
        base = os.path.basename(p)
        A, tiled2, B = (os.path.join(tmp, base + s) for s in (".a.json", ".t.json", ".b.json"))
        rc, log = run("import_tiled.py", p, A)
        if not os.path.exists(A):
            print(f"FAIL {base}: import failed\n{log}")
            failed += 1
            continue
        note = " (lossy import)" if rc else ""
        rc2, log2 = run("export_tiled.py", A, tiled2, "--profile", "watercooler")
        rc3, log3 = run("import_tiled.py", tiled2, B)
        if not os.path.exists(B):
            print(f"FAIL {base}: re-import failed\n{log2}\n{log3}")
            failed += 1
            continue
        problems = diff(normalise(json.load(open(A))), normalise(json.load(open(B))))
        if problems:
            print(f"FAIL {base}{note}")
            for q in problems[:6]:
                print("      ", q)
            failed += 1
        else:
            print(f"pass {base}{note}")
            passed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
