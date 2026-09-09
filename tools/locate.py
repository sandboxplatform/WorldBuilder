#!/usr/bin/env python3
"""
Locate every single inside its grid-true parent theme sheet.

Why: Tiled tile layers address art by GID -- an index into a sheet image -- so an
exporter needs each asset's (sheet, column, row). The pre-cut singles lose that:
interior singles are cropped to pixel bounds, so ~36% are not even 32-multiples.

How: match the single back into its parent sheet. Comparison is RGB-only and
restricted to the single's opaque pixels, because shadows bleed across object
bounds in the sheets, so alpha does not agree even where the art does.

Speed: brute-force sliding is far too slow at this scale. Instead anchor on the
single's *rarest* colour within that sheet -- usually a handful of candidate
positions instead of millions.

    python tools/locate.py                 # everything, writes catalog/sheet_xy.json
    python tools/locate.py --theme kitchen # one theme, for checking
"""
import argparse, collections, json, os, sys, time
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "catalog", "sheet_xy.json")


def rgb32(path):
    """Load as an (h, w) uint32 array of packed RGB, plus the alpha channel."""
    a = np.asarray(Image.open(path).convert("RGBA"))
    rgb = (a[:, :, 0].astype(np.uint32) << 16 | a[:, :, 1].astype(np.uint32) << 8
           | a[:, :, 2].astype(np.uint32))
    return rgb, a[:, :, 3]


class Sheet:
    def __init__(self, path):
        self.rgb, _ = rgb32(path)
        self.h, self.w = self.rgb.shape
        vals, counts = np.unique(self.rgb, return_counts=True)
        self.freq = dict(zip(vals.tolist(), counts.tolist()))
        self._pos = {}

    def positions(self, colour):
        """Cached (y, x) arrays for every pixel of this colour."""
        if colour not in self._pos:
            ys, xs = np.nonzero(self.rgb == colour)
            self._pos[colour] = (ys, xs)
        return self._pos[colour]


_SHEET_CACHE = {}


def get_sheet(path):
    if path not in _SHEET_CACHE:
        _SHEET_CACHE[path] = Sheet(path)
    return _SHEET_CACHE[path]


def locate(sheet, path):
    """Return (x, y, score, n_candidates) of the single within the sheet."""
    rgb, alpha = rgb32(path)
    h, w = rgb.shape
    if h > sheet.h or w > sheet.w:
        return None
    # Only fully-opaque pixels are comparable. Shadows and antialiased edges are
    # semi-transparent, so in the sheet they are blended against whatever sits
    # behind them, while in the cropped single they are blended against nothing.
    oy, ox = np.nonzero(alpha == 255)
    if len(oy) < 4:
        return None
    ovals = rgb[oy, ox]

    # anchor on the opaque pixel whose colour is rarest in the sheet
    uniq = np.unique(ovals)
    best_colour, best_freq = None, None
    for c in uniq.tolist():
        f = sheet.freq.get(c)
        if f is None:
            return None            # a colour absent from the sheet: cannot match
        if best_freq is None or f < best_freq:
            best_colour, best_freq = c, f
    k = int(np.nonzero(ovals == best_colour)[0][0])
    ay, ax = int(oy[k]), int(ox[k])

    cy, cx = sheet.positions(best_colour)
    origins_y, origins_x = cy - ay, cx - ax
    keep = ((origins_y >= 0) & (origins_x >= 0)
            & (origins_y <= sheet.h - h) & (origins_x <= sheet.w - w))
    origins_y, origins_x = origins_y[keep], origins_x[keep]

    hits = []
    for y, x in zip(origins_y.tolist(), origins_x.tolist()):
        if (sheet.rgb[y + oy, x + ox] == ovals).all():
            hits.append((x, y))
            if len(hits) > 8:
                break
    if not hits:
        return None
    # prefer the top-left-most hit; ties are reported so they can be reviewed
    hits.sort(key=lambda p: (p[1], p[0]))
    return hits[0][0], hits[0][1], len(hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", help="limit to one category, e.g. kitchen")
    ap.add_argument("--size", default="32", choices=["16", "32", "48"])
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    assets = cat["assets"]
    sheets = {e["id"]: e for e in assets if e["kind"] == "sheet"}

    FALLBACKS = {
        "int": ["int.sheet.complete.complete", "int.roombuilder.complete.complete"],
        "ext": ["ext.sheet.complete.complete"],
        "office": ["office.roombuilder.office.room_builder_office"],
    }
    all_by_id = {e["id"]: e for e in assets}

    def candidates(pack, category):
        """Sheets to try, in order: the theme's own, then whole-pack sheets."""
        ids = [f"{pack}.sheet.{category}.sheet"] + FALLBACKS.get(pack, [])
        if pack == "office":
            ids.insert(1, "office.sheet.office.sheet")
        out = []
        for sid in ids:
            e = all_by_id.get(sid)
            if e is not None and a.size in e["paths"] and e not in out:
                out.append(e)
        return out

    todo = [e for e in assets
            if e["kind"] == "single" and a.size in e["paths"]
            and (a.theme is None or e["category"] == a.theme)]
    todo.sort(key=lambda e: e["category"])

    result, unresolved, ambiguous = {}, [], []
    t0 = time.time()
    by_cat = collections.defaultdict(list)
    for e in todo:
        by_cat[(e["pack"], e["category"])].append(e)

    T = int(a.size)
    for (pack, cat_name), items in sorted(by_cat.items()):
        cands = candidates(pack, cat_name)
        if not cands:
            unresolved += [(e["id"], "no parent sheet") for e in items]
            continue
        found = 0
        for e in items:
            path = os.path.join(base, e["paths"][a.size])
            hit = None
            for p in cands:
                sheet = get_sheet(os.path.join(base, p["paths"][a.size]))
                r = locate(sheet, path)
                if r is not None:
                    hit = (p, r)
                    break
            if hit is None:
                unresolved.append((e["id"], "no match"))
                continue
            p, (x, y, n) = hit
            result[e["id"]] = {
                "sheet": p["id"], "px": [x, y],
                "tile": [x // T, y // T],
                "span": [(x % T + e["px"][a.size][0] + T - 1) // T,
                         (y % T + e["px"][a.size][1] + T - 1) // T],
                "aligned": x % T == 0 and y % T == 0,
            }
            if n > 1:
                ambiguous.append((e["id"], n))
            found += 1
        print(f"  {pack}.{cat_name:<30s} {found}/{len(items)}", flush=True)

    json.dump({"size": a.size, "located": result,
               "unresolved": unresolved, "ambiguous": ambiguous},
              open(a.out, "w"), separators=(",", ":"))
    n = len(todo)
    print(f"\n{len(result)}/{n} located ({100*len(result)/max(n,1):.1f}%) "
          f"in {time.time()-t0:.0f}s")
    print(f"  ambiguous (multiple hits): {len(ambiguous)}")
    print(f"  unresolved: {len(unresolved)}")
    aligned = sum(1 for v in result.values() if v["aligned"])
    print(f"  grid-aligned: {aligned} ({100*aligned/max(len(result),1):.0f}%)")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
