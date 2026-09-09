#!/usr/bin/env python3
"""
Render an exported Tiled map from its own atlas, using nothing from the catalog.

This is the export's acceptance test: if the picture matches the one the generator
produced, the atlas and the GID maths are correct and the output stands alone.

    python tools/render_tiled.py out/office_floor.json out.png
"""
import json, os, sys
from PIL import Image

FLIP_MASK = 0x80000000 | 0x40000000 | 0x20000000


def main():
    src, dst = sys.argv[1], sys.argv[2]
    m = json.load(open(src))
    T = m["tilewidth"]
    W, H = m["width"], m["height"]
    ts = m["tilesets"][0]
    atlas = Image.open(os.path.join(os.path.dirname(src), ts["image"])).convert("RGBA")
    cols = ts["columns"]
    canvas = Image.new("RGBA", (W * T, H * T), (18, 19, 26, 255))
    drawn = 0
    for L in m["layers"]:
        if L["type"] != "tilelayer":
            continue
        for i, gid in enumerate(L["data"]):
            g = gid & ~FLIP_MASK
            if g == 0:
                continue
            local = g - ts["firstgid"]
            sx, sy = (local % cols) * T, (local // cols) * T
            cell = atlas.crop((sx, sy, sx + T, sy + T))
            canvas.alpha_composite(cell, ((i % W) * T, (i // W) * T))
            drawn += 1
    canvas.convert("RGB").save(dst)
    print(f"{dst}: {canvas.width}x{canvas.height}, {drawn} tiles drawn from the atlas")


if __name__ == "__main__":
    main()
