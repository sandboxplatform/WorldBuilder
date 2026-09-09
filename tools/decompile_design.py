#!/usr/bin/env python3
"""
Turn the pack's own room designs back into editable maps.

The Home_Designs and Office_Designs folders are the artist's finished rooms, and they
ship as separate layer PNGs -- the designer's own layering. Every cell in them came
from a sheet, so hashing each 32px cell of every sheet gives an exact reverse lookup:
image -> tile refs -> a map you can open in the editor and change.

This is the shortest route to rooms that look right: start from the artist's own
composition instead of trying to re-derive it.

    python tools/decompile_design.py --list
    python tools/decompile_design.py "Generic_Home_1" --out maps/generic_home_1.json
"""
import argparse, hashlib, json, os, re, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZE = "32"
T = 32
LAYER_ROLE = {1: "floor", 2: "furniture", 3: "overhead"}


def sheet_index():
    """content hash of each sheet tile -> tile ref."""
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    idx = {}
    kinds = {"sheet", "roombuilder"}
    for e in cat["assets"]:
        if e["kind"] not in kinds or SIZE not in e["paths"]:
            continue
        w, h = e["px"][SIZE]
        if w * h > 40_000_000:
            continue                       # the complete mega-sheets duplicate the rest
        im = Image.open(os.path.join(base, e["paths"][SIZE])).convert("RGBA")
        for r in range(h // T):
            for c in range(w // T):
                cell = im.crop((c*T, r*T, c*T+T, r*T+T))
                if cell.getbbox() is None:
                    continue
                k = hashlib.sha1(cell.tobytes()).digest()
                idx.setdefault(k, f"tile:{e['id']}#{c},{r}")
    return idx


def find_designs():
    out = {}
    for dirpath, _d, files in os.walk(os.path.join(ROOT, "images", "extracted")):
        if "Designs" not in dirpath or f"{T}x{T}" not in dirpath:
            continue
        for fn in files:
            m = re.match(r"(.+?)[_ ]?[Ll]ayer[_ ]?(\d+)", fn)
            if not m or not fn.endswith(".png"):
                continue
            name = re.sub(r"_?\d+x\d+$", "", m.group(1)).strip("_ ")
            out.setdefault(name, {})[int(m.group(2))] = os.path.join(dirpath, fn)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("design", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    designs = find_designs()
    if a.list or not a.design:
        print(f"{len(designs)} designs at {T}px:")
        for n in sorted(designs):
            print(f"  {n}  (layers {sorted(designs[n])})")
        return 0

    hit = next((n for n in designs if a.design.lower() in n.lower()), None)
    if not hit:
        sys.exit(f"no design matching {a.design!r}")
    layers = designs[hit]

    print(f"indexing sheets…", flush=True)
    idx = sheet_index()
    print(f"  {len(idx):,} distinct sheet tiles")

    first = Image.open(layers[sorted(layers)[0]]).convert("RGBA")
    W, H = first.width // T, first.height // T
    out_layers, missing_total, cells_total = [], 0, 0
    for n in sorted(layers):
        im = Image.open(layers[n]).convert("RGBA")
        pal, pi, grid = [], {}, [[-1]*W for _ in range(H)]
        missing = 0
        for r in range(min(H, im.height // T)):
            for c in range(min(W, im.width // T)):
                cell = im.crop((c*T, r*T, c*T+T, r*T+T))
                if cell.getbbox() is None:
                    continue
                cells_total += 1
                ref = idx.get(hashlib.sha1(cell.tobytes()).digest())
                if ref is None:
                    missing += 1
                    continue
                if ref not in pi:
                    pi[ref] = len(pal); pal.append(ref)
                grid[r][c] = pi[ref]
        missing_total += missing
        if pal:
            out_layers.append({"name": LAYER_ROLE.get(n, f"layer{n}"),
                               "role": "terrain", "palette": pal, "grid": grid})
        print(f"  layer {n} -> {LAYER_ROLE.get(n, n):9s} "
              f"{len(pal):4d} distinct tiles, {missing} unmatched")

    m = {"format": "worldbuilder-map/1", "tile": T, "size": [W, H],
         "background": "#12131a", "layers": out_layers,
         "regions": [], "collisions": [], "spawns": [], "pois": []}
    out = a.out or os.path.join(ROOT, "maps", f"design_{hit.lower()}.json")
    json.dump(m, open(out, "w"), indent=1)
    pct = 100 * (cells_total - missing_total) / max(1, cells_total)
    print(f"\n{hit}: {W}x{H} tiles -> {out}")
    print(f"  {pct:.1f}% of painted cells matched to sheet tiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
