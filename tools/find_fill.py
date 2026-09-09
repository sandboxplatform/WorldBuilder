#!/usr/bin/env python3
"""
Find the seamless 'fill' tile in a terrain family.

Terrain in these packs is an autotile set: most variants are edges and corners,
and only one or two tile seamlessly for covering open ground. This scores each
1x1 variant by how well it matches itself when repeated (top row vs bottom row,
left column vs right column) and prints the best candidates.

    python tools/find_fill.py ext.single.terrains_and_fences.grass_1_
"""
import json, os, sys
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    prefix = sys.argv[1]
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    sel = [e for e in cat["assets"]
           if e["id"].startswith(prefix) and e["tiles"] == [1, 1] and "32" in e["paths"]]
    if not sel:
        sys.exit(f"no 1x1 assets under {prefix}")

    scored = []
    for e in sel:
        a = np.asarray(Image.open(os.path.join(base, e["paths"]["32"]))
                       .convert("RGBA")).astype(np.int16)
        if (a[:, :, 3] < 255).any():
            continue  # transparent pixels: not a ground fill
        # seam error when the tile is repeated against itself
        v = np.abs(a[:, 0, :3] - a[:, -1, :3]).mean()
        h = np.abs(a[0, :, :3] - a[-1, :, :3]).mean()
        # penalise tiles that are one flat colour edge-to-edge only on one axis
        scored.append((v + h, e["id"]))

    scored.sort()
    print(f"{len(scored)} opaque 1x1 candidates under {prefix}\nbest fills (lower = more seamless):")
    for s, i in scored[:8]:
        print(f"  {s:7.2f}  {i}")


if __name__ == "__main__":
    main()
