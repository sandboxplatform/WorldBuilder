#!/usr/bin/env python3
"""
Render paged contact sheets for the vision labelling pass, plus a manifest.

Each cell is numbered. The manifest maps (page, cell number) -> asset id, so labels
can be written against short numbers instead of long ids, and nothing depends on
reading tiny text out of an image.

    python tools/label_sheets.py --category kitchen --pack int
"""
import argparse, json, os, re, sys
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", required=True)
    ap.add_argument("--pack")
    ap.add_argument("--size", default="32")
    ap.add_argument("--cols", type=int, default=7)
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--cell", type=int, default=96)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--outdir", default=None)
    # Context is the default: labelling the kitchen theme showed that isolated
    # sprites are unidentifiable for modular pieces (48 flat coloured panels turned
    # out to be cupboard doors and worktops, which only the surrounding sheet
    # revealed). Sprites with no recovered sheet position fall back to isolated and
    # are tagged "iso".
    ap.add_argument("--no-context", dest="context", action="store_false",
                    default=True,
                    help="show isolated sprites instead of sheet neighbourhoods")
    ap.add_argument("--pad", type=int, default=1,
                    help="tiles of surrounding sheet to show either side")
    a = ap.parse_args()

    outdir = a.outdir or os.path.join(ROOT, "labelling", a.category)
    os.makedirs(outdir, exist_ok=True)

    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    sel = [e for e in cat["assets"]
           if e["kind"] == "single" and e["category"] == a.category
           and a.size in e["paths"] and (a.pack is None or e["pack"] == a.pack)]
    sel.sort(key=lambda e: natural(e["id"]))

    facets = {}
    fp = os.path.join(ROOT, "catalog", "facets.json")
    if os.path.exists(fp):
        facets = json.load(open(fp))["assets"]

    index = {e["id"]: e for e in cat["assets"]}
    located, sheet_cache = {}, {}
    xyp = os.path.join(ROOT, "catalog", "sheet_xy.json")
    if a.context and os.path.exists(xyp):
        located = json.load(open(xyp))["located"]

    def sheet_image(sid):
        if sid not in sheet_cache:
            e = index.get(sid)
            if e is None or a.size not in e["paths"]:
                sheet_cache[sid] = None
            else:
                sheet_cache[sid] = Image.open(
                    os.path.join(base, e["paths"][a.size])).convert("RGBA")
        return sheet_cache[sid]

    T = int(a.size)

    def render(e):
        """(image, has_context) for one asset."""
        loc = located.get(e["id"]) if a.context else None
        if loc:
            sh = sheet_image(loc["sheet"])
            if sh is not None:
                x, y = loc["px"]
                w, h = e["px"][a.size]
                p = a.pad * T
                x0, y0 = max(0, x - p), max(0, y - p)
                x1, y1 = min(sh.width, x + w + p), min(sh.height, y + h + p)
                crop = sh.crop((x0, y0, x1, y1))
                out = Image.new("RGBA", crop.size, (58, 58, 72, 255))
                out.alpha_composite(crop)
                dd = ImageDraw.Draw(out)
                dd.rectangle([x - x0, y - y0, x - x0 + w - 1, y - y0 + h - 1],
                             outline=(255, 90, 160, 255))
                return out, True
        return Image.open(os.path.join(base, e["paths"][a.size])).convert("RGBA"), False

    per = a.cols * a.rows
    manifest, pages = {}, (len(sel) + per - 1) // per
    CELL, PAD, LBL = a.cell, 10, 12

    for p in range(pages):
        chunk = sel[p * per:(p + 1) * per]
        W = PAD + a.cols * (CELL + PAD)
        H = PAD + ((len(chunk) + a.cols - 1) // a.cols) * (CELL + PAD + LBL) + 18
        im = Image.new("RGBA", (W, H), (24, 24, 32, 255))
        d = ImageDraw.Draw(im)
        d.text((PAD, 4), f"{a.category} - page {p+1}/{pages}", fill=(255, 200, 110, 255))
        for n, e in enumerate(chunk):
            r, c = divmod(n, a.cols)
            x = PAD + c * (CELL + PAD)
            y = 18 + PAD + r * (CELL + PAD + LBL)
            t, has_ctx = render(e)
            k = min(CELL / t.width, CELL / t.height)
            k = int(k) if k >= 2 else k
            if k != 1:
                t = t.resize((max(1, int(t.width * k)), max(1, int(t.height * k))),
                             Image.NEAREST)
            d.rectangle([x - 1, y - 1, x + CELL, y + CELL], outline=(85, 85, 105, 255))
            im.alpha_composite(t, (x + (CELL - t.width) // 2,
                                   y + (CELL - t.height) // 2 if has_ctx
                                   else y + CELL - t.height))
            num = n + 1
            d.text((x + 2, y + CELL + 1), str(num), fill=(255, 235, 150, 255))
            hint = (facets.get(e["id"], {}) or {}).get("placement")
            if hint:
                d.text((x + 22, y + CELL + 1), hint[:5], fill=(140, 165, 200, 255))
            if a.context and not has_ctx:
                d.text((x + CELL - 16, y + CELL + 1), "iso", fill=(210, 130, 90, 255))
            manifest[f"{p+1}:{num}"] = e["id"]
        if a.scale > 1:
            im = im.resize((im.width * a.scale, im.height * a.scale), Image.NEAREST)
        im.convert("RGB").save(os.path.join(outdir, f"page{p+1:02d}.png"))

    json.dump({"category": a.category, "size": a.size, "pages": pages,
               "cells": manifest}, open(os.path.join(outdir, "manifest.json"), "w"),
              indent=1)
    print(f"{len(sel)} assets -> {pages} pages in {outdir}")


if __name__ == "__main__":
    main()
