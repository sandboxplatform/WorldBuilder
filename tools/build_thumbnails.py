#!/usr/bin/env python3
"""
Build thumbnail atlases for the editor's pickers.

A native <select> cannot show images, so a picker with previews needs one image per
entry. Rather than loading 69 full sheets (one of them is 512x34048) just to draw
icons, the previews are baked once into two small atlases.

The thumbnail is ONE representative asset, not a crop of many: a postage stamp of a
whole tileset is unreadable. catalog/sheet_xy.json already records which individual
sprites live inside which sheet, so for most sheets the thumbnail is a real, named
asset from that sheet. Sheets with no located sprites (room-builder parts, UI,
autotiles) fall back to the fullest 2x2 tile block.

  thumbs_sheets.png   one representative object per sheet
  thumbs_cats.png     one representative sprite per singles category

    python tools/build_thumbnails.py
"""
import json, os
from PIL import Image
import numpy as np

# The sheets are ours and some are genuinely huge (512x34048); the DoS guard is
# aimed at untrusted uploads, not a local asset pack.
Image.MAX_IMAGE_PIXELS = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ED = os.path.join(ROOT, "editor")
CELL = 96
COLS = 12
T = 32


def variety(im):
    """Rough count of distinct colours -- guards against picking a flat block of
    floor when the sheet also contains real objects."""
    q = im.convert("RGB").quantize(colors=32).getcolors() or []
    return sum(1 for n, _ in q if n > 8)


def dense_block(im, tiles=2):
    """Fallback for gutterless tilesets: the fullest tiles x tiles block."""
    w, h = im.size
    side = min(tiles * T, w, h)
    if side <= 0:
        return im
    a = im.getchannel("A")
    best, best_score = (0, 0), -1.0
    for y in range(0, max(1, h - side + 1), T):
        for x in range(0, max(1, w - side + 1), T):
            box = a.crop((x, y, x + side, y + side))
            score = sum(box.histogram()[200:]) / float(side * side)
            if score > best_score:
                best_score, best = score, (x, y)
            if score > 0.98:
                break
    x, y = best
    return im.crop((x, y, x + side, y + side))


def fit(img, cell=CELL, pad=6):
    """Centre the sprite in a cell, upscaling at whole-pixel factors so the pixel
    art stays crisp rather than turning to mush."""
    box = img.getbbox()
    if box:
        img = img.crop(box)
    out = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
    if img.width == 0 or img.height == 0:
        return out
    avail = cell - 2 * pad
    k = min(avail / img.width, avail / img.height)
    if k >= 1:
        k = max(1, int(k))                  # integer zoom only
        w, h = img.width * k, img.height * k
        img = img.resize((w, h), Image.NEAREST)
    else:
        w, h = max(1, int(img.width * k)), max(1, int(img.height * k))
        img = img.resize((w, h), Image.LANCZOS)
    out.alpha_composite(img, ((cell - w) // 2, (cell - h) // 2))
    return out


def pack(images, path):
    rows = max(1, (len(images) + COLS - 1) // COLS)
    atlas = Image.new("RGBA", (COLS * CELL, rows * CELL), (0, 0, 0, 0))
    for i, im in enumerate(images):
        atlas.alpha_composite(im, ((i % COLS) * CELL, (i // COLS) * CELL))
    atlas.save(path)
    return atlas.size


def sprite_score(im):
    """How good a sprite is as the face of its category: solid, detailed, and big
    enough to see, without being a banner-sized strip."""
    box = im.getbbox()
    if not box:
        return -1.0
    c = im.crop(box)
    w, h = c.size
    if w < 12 or h < 12 or w > 6 * T or h > 6 * T:
        return -1.0
    a = np.asarray(c.getchannel("A"))
    cover = float((a > 128).mean())
    ratio = min(w, h) / float(max(w, h))
    return cover * min(variety(c), 20) * ratio * min(w * h, 96 * 96) ** 0.25


def first_frame(im):
    """Some sprites are undeclared frame sheets -- a fire truck drawn six times in a
    row, separated by blank columns. When a large sprite splits into three or more
    similar chunks along an axis, keep the first chunk."""
    a = np.asarray(im.getchannel("A")) > 128

    def chunks(occupied):
        out, run = [], None
        for i, v in enumerate(occupied):
            if v and run is None:
                run = i
            elif not v and run is not None:
                out.append((run, i)); run = None
        if run is not None:
            out.append((run, len(occupied)))
        return out

    def first_span(occupied, n):
        if n < 8 * T:
            return n
        cs = chunks(occupied)
        if len(cs) < 3:
            return n
        widths = [b - a_ for a_, b in cs]
        med = sorted(widths)[len(widths) // 2]
        if med < T or max(widths) > 2.5 * med:
            return n                        # uneven -- not a frame strip
        return cs[0][1]

    h, w = a.shape
    x1 = first_span(a.any(axis=0), w)
    y1 = first_span(a.any(axis=1), h)
    return im.crop((0, 0, x1, y1)) if (x1 < w or y1 < h) else im


def load_sprite(rec):
    im = Image.open(os.path.join(ROOT, rec["image"])).convert("RGBA")
    if rec.get("anim"):
        return im.crop((0, 0, rec["anim"]["frame"][0], rec["anim"]["frame"][1]))
    return first_frame(im)


def best_member(ids, by_id, limit=140):
    """The best-looking named sprite out of a list of ids, or None."""
    best, best_score = None, -1.0
    step = max(1, len(ids) // limit)
    for sid in sorted(ids)[::step]:
        rec = by_id.get(sid)
        if not rec:
            continue
        im = load_sprite(rec)
        sc = sprite_score(im)
        if sc > best_score:
            best_score, best = sc, im
    return best


def main():
    sheets = json.load(open(os.path.join(ED, "sheets.json")))
    singles = json.load(open(os.path.join(ED, "singles.json")))
    by_id = singles["byId"]

    # Which named sprites live in which sheet, so a sheet can be represented by a
    # real asset instead of an arbitrary crop.
    members = {}
    located = json.load(open(os.path.join(ROOT, "catalog", "sheet_xy.json")))["located"]
    for sid, loc in located.items():
        if sid in by_id:
            members.setdefault(loc["sheet"], []).append(sid)

    index, imgs, fell_back = {}, [], []
    for size, lst in sheets["sizes"].items():
        for s in lst:
            k = f"{size}:{s['id']}"
            if k in index:
                continue
            obj = best_member(members.get(s["id"], []), by_id)
            if obj is None:
                im = Image.open(os.path.join(ROOT, s["image"])).convert("RGBA")
                obj = dense_block(im)
                fell_back.append(s["id"])
            imgs.append(fit(obj))
            index[k] = len(imgs) - 1
    dims = pack(imgs, os.path.join(ED, "thumbs_sheets.png"))
    json.dump({"cell": CELL, "cols": COLS, "index": index},
              open(os.path.join(ED, "thumbs_sheets.json"), "w"))
    print(f"  sheets: {len(imgs)} thumbs, atlas {dims[0]}x{dims[1]}, "
          f"{len(set(fell_back))} used a tile block: {sorted(set(fell_back))}")

    singles = json.load(open(os.path.join(ED, "singles.json")))
    cidx, cimgs = {}, []
    for key, recs in singles["cats"].items():
        best, best_score = None, -1.0
        # Scan a bounded sample -- some categories hold hundreds of sprites.
        step = max(1, len(recs) // 60)
        for r in recs[::step]:
            im = load_sprite(r)
            sc = sprite_score(im)
            if sc > best_score:
                best_score, best = sc, im
        if best is None:
            # Every sprite failed the size filter (a category of nothing but big
            # vehicle strips); take the first one, frame-split like any other.
            best = load_sprite(recs[0])
        cimgs.append(fit(best))
        cidx[key] = len(cimgs) - 1
    dims = pack(cimgs, os.path.join(ED, "thumbs_cats.png"))
    json.dump({"cell": CELL, "cols": COLS, "index": cidx},
              open(os.path.join(ED, "thumbs_cats.json"), "w"))
    print(f"  categories: {len(cimgs)} thumbs, atlas {dims[0]}x{dims[1]}")


if __name__ == "__main__":
    main()
