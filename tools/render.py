#!/usr/bin/env python3
"""
Render a map file to a PNG.

A map is just asset ids plus tile positions -- no pixels, so it is small,
diffable and safe to share (the packs themselves are not redistributable).

    python tools/render.py maps/demo_street.json out.png [--size 32] [--scale 2]

Reads the neutral map format v1 -- see FORMAT.md. Terrain layers are a palette
plus a grid of indices; object layers are semantic placements.

Positions are tile coordinates of the asset's TOP-LEFT tile. Assets taller than
their footprint (the tightly-cropped interior singles) are bottom-aligned to the
footprint so they sit on the floor rather than float.
"""
import argparse, json, os, sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refs as refs_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_catalog():
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    return cat, {e["id"]: e for e in cat["assets"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mapfile")
    ap.add_argument("out")
    ap.add_argument("--size", default="32", choices=["16", "32", "48"])
    ap.add_argument("--scale", type=int, default=1, help="nearest-neighbour upscale")
    a = ap.parse_args()

    cat, index = load_catalog()
    base = os.path.join(ROOT, cat["root"])
    m = json.load(open(a.mapfile))

    # Sprites are exported on padded canvases (every Modern Office single is a 2x3
    # canvas whatever its content). The generator allocates footprints from the
    # *content* bounds, so draw the content where it was placed rather than
    # bottom-aligning the whole canvas.
    bboxes = {}
    fpath = os.path.join(ROOT, "catalog", "facets.json")
    if os.path.exists(fpath):
        for aid, rec in json.load(open(fpath))["assets"].items():
            bb = rec.get("pixel_facets", {}).get("bbox")
            if bb:
                bboxes[aid] = bb

    tile = int(a.size)
    cols, rows = m["size"]
    canvas = Image.new("RGBA", (cols * tile, rows * tile),
                       m.get("background", "#00000000"))

    missing = []

    def draw(ref, cx, cy, off=(0, 0)):
        if refs_mod.check(ref, a.size):
            missing.append(ref)
            return
        im, (_fw, fh) = refs_mod.resolve(ref, a.size)
        bb = bboxes.get(ref)
        # objects may carry a sub-tile pixel offset: the pack's own room designs place
        # furniture off the grid, and snapping everything is what makes a room look stiff
        px, py = cx * tile + off[0], cy * tile + off[1]
        if bb:
            # place so the sprite's content lands exactly where it was put
            canvas.alpha_composite(im, (px - bb[0], py - bb[1]))
        else:
            # bottom-align inside the footprint so cropped sprites rest on the floor
            canvas.alpha_composite(im, (px, py + fh * tile - im.height))

    for layer in m["layers"]:
        if layer["role"] == "terrain":
            pal = layer["palette"]
            for y, row in enumerate(layer["grid"]):
                for x, v in enumerate(row):
                    if v != -1:
                        draw(pal[v], x, y)
        # a terrain layer carries placements too: whole objects dropped onto a tile
        # layer keep their own entry rather than being flattened into the grid
        for p in layer.get("placements", []):
            draw(p["id"], p["at"][0], p["at"][1], tuple(p.get("off", (0, 0))))

    if a.scale > 1:
        canvas = canvas.resize((canvas.width * a.scale, canvas.height * a.scale),
                               Image.NEAREST)
    canvas.save(a.out)
    print(f"rendered {a.out}  {canvas.width}x{canvas.height}")
    if missing:
        print(f"WARNING: {len(missing)} unresolved id(s): {sorted(set(missing))[:5]}",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
