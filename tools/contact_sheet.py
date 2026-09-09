#!/usr/bin/env python3
"""
Render a labelled contact sheet of catalog assets.

Two uses:
  * eyeball a terrain family to find its fill tile vs its edge tiles
  * feed a sheet to a vision pass to put names on the ~6,200 number-only singles

    python tools/contact_sheet.py out.png --prefix ext.single.terrains_and_fences.grass_1_
    python tools/contact_sheet.py out.png --pack int --category kitchen --limit 60
"""
import argparse, json, os, re, sys
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# whole-theme sheets and palettes swamp a contact sheet; skip unless --kind asks
BULK_KINDS = {"sheet", "palette", "design", "roombuilder", "layer", "premade"}


def natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--pack")
    ap.add_argument("--kind")
    ap.add_argument("--category")
    ap.add_argument("--size", default="32", choices=["16", "32", "48"])
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--cell", type=int, default=0, help="cell size in px (0 = auto)")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--offset", type=int, default=0, help="skip N matches (paging)")
    a = ap.parse_args()

    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    sel = [e for e in cat["assets"]
           if e["id"].startswith(a.prefix)
           and (a.pack is None or e["pack"] == a.pack)
           and (e["kind"] == a.kind if a.kind else e["kind"] not in BULK_KINDS)
           and (a.category is None or e["category"] == a.category)
           and a.size in e["paths"]]
    sel.sort(key=lambda e: natural(e["id"]))
    total = len(sel)
    sel = sel[a.offset:a.offset + a.limit]
    if not sel:
        sys.exit("no assets matched")

    ims = [(e, Image.open(os.path.join(base, e["paths"][a.size])).convert("RGBA"))
           for e in sel]
    cell = a.cell or min(128, max(max(im.width, im.height) for _, im in ims))
    pad, label = 10, 11
    cols = a.cols
    rows = (len(ims) + cols - 1) // cols
    W = pad + cols * (cell + pad)
    H = pad + rows * (cell + pad + label)
    sheet = Image.new("RGBA", (W, H), (28, 28, 38, 255))
    d = ImageDraw.Draw(sheet)

    for n, (e, im) in enumerate(ims):
        r, c = divmod(n, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + pad + label)
        d.rectangle([x - 1, y - 1, x + cell, y + cell], outline=(80, 80, 100, 255))
        # scale to fill the cell: integer factors when enlarging, to stay crisp
        k = min(cell / im.width, cell / im.height)
        if k >= 2:
            k = int(k)
        if k != 1:
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                           Image.NEAREST)
        # bottom-centre inside the cell, the way it would sit on a floor
        sheet.alpha_composite(im, (x + (cell - im.width) // 2, y + cell - im.height))
        d.text((x, y + cell + 1), e["name"][:max(6, cell // 6)], fill=(205, 205, 220, 255))

    if a.scale > 1:
        sheet = sheet.resize((sheet.width * a.scale, sheet.height * a.scale),
                             Image.NEAREST)
    sheet.convert("RGB").save(a.out)
    print(f"{a.out}: {len(ims)} of {total} matching assets "
          f"(offset {a.offset}), {sheet.width}x{sheet.height}")


if __name__ == "__main__":
    main()
