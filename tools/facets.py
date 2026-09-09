#!/usr/bin/env python3
"""
Derive structured facets for every catalogued asset.

The pack's own folders group by *theme* (kitchen, graveyard, city_props) -- that is
the vendor's shelf layout, not a way to find things. To build worlds from prompts you
need to ask "a two-seater sofa", "something wooden that sits on a desk", "a road tile
that tiles seamlessly". That needs facets.

Two independent sources, deliberately kept apart so they can be trusted differently:

  name facets    parsed from the pack's own filenames. Free, deterministic, and
                 available for the ~6,200 exterior/office singles that are named.
  pixel facets   measured from the art. Objective, available for *everything*,
                 and the only signal for the ~6,200 number-only interior singles
                 until the vision pass labels them.

Neither invents meaning. Anything uncertain is left absent rather than guessed, so a
later pass can fill it in without having to distrust what is already here.

    python tools/facets.py                     # all assets -> catalog/facets.json
    python tools/facets.py --category kitchen  # one theme, printed
"""
import argparse, collections, json, os, re, sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "catalog", "facets.json")

# ---------------------------------------------------------------- name vocabulary
COLOUR = {"brown", "green", "blue", "grey", "gray", "white", "red", "orange",
          "yellow", "black", "pink", "purple", "beige", "cyan", "golden", "silver"}
SIZE = {"small", "medium", "big", "large", "tall", "short", "mini", "long"}
FACING = {"left", "right", "up", "down", "front", "back", "side", "lateral",
          "diagonal", "vertical", "horizontal"}
PART = {"modular", "corner", "middle", "edge", "top", "bottom", "center", "centre",
        "layer", "part", "piece", "end", "inner", "outer", "upper", "lower"}
STATE = {"open", "closed", "full", "empty", "broken", "on", "off", "lit", "unlit",
         "old", "new", "dirty", "clean", "used", "dead", "cut", "damaged"}
MATERIAL = {"wood", "wooden", "glass", "metal", "stone", "brick", "sand", "water",
            "concrete", "plastic", "marble", "bamboo", "steel"}
NOISE = {"vers", "version", "example", "variant", "variation", "sprite", "alt",
         "props", "prop", "single", "singles"}
# plain adjectives: never a concept on their own, so "deep_water" reduces to water
ADJECTIVE = {"deep", "shallow", "wide", "narrow", "thin", "thick", "round",
             "square", "curved", "straight", "flat", "steep", "double", "triple"}
MODIFIERS = COLOUR | SIZE | FACING | PART | STATE | MATERIAL | NOISE | ADJECTIVE

CANON = {"gray": "grey", "wooden": "wood", "centre": "center"}


# Words that are both a material and a thing in their own right ("deep_water",
# "sand", "stone_wall"). Stripping them as modifiers destroys the concept, so the
# final token of a name is always kept as part of the concept even when it also
# reads as a modifier.
def name_facets(name):
    """Split a pack-given name into concept plus modifier facets."""
    toks = [t for t in name.split("_") if t]
    out = collections.defaultdict(list)
    core, variant = [], None
    for t in toks:
        if t.isdigit():
            variant = int(t)          # trailing numbers are variant indices
            continue
        c = CANON.get(t, t)
        if c in ADJECTIVE:
            continue
        if c in COLOUR:
            out["colour"].append(c)
        elif c in SIZE:
            out["size_class"].append(c)
        elif c in FACING:
            out["facing"].append(c)
        elif c in PART:
            out["part"].append(c)
        elif c in STATE:
            out["state"].append(c)
        elif c in MATERIAL:
            out["material"].append(c)
        elif c in NOISE:
            pass
        else:
            core.append(c)
    # Colours and materials double as things in their own right ("deep_water" is
    # water; "sand" is sand). Fall back to them only when nothing else survived --
    # so "binary_number_orange" stays binary_number, but "deep_water" becomes water.
    if not core:
        core = [t for t in out.get("material", [])] or [t for t in out.get("colour", [])]

    f = {k: sorted(set(v)) for k, v in out.items()}
    if core:
        f["concept"] = "_".join(core)
        f["head"] = core[-1]          # crude but useful: the last word is the noun
    if variant is not None:
        f["variant"] = variant
    if "modular" in f.get("part", []):
        f["modular"] = True
    return f


# ---------------------------------------------------------------- shadow signals
# Interiors and Office ship a Shadowless copy of every single. Diffing the two
# isolates the drop shadow, which is a strong, objective signal:
#   * a shadow at all  -> the object stands on the floor
#   * no shadow        -> it is wall-mounted, an overlay, or a floor decal
#   * the shadow's box -> where the object actually meets the ground, which is the
#                         collision footprint rather than the full sprite bounds
# Exteriors have no Shadowless variants, but they *are* named, so the two halves of
# the library are covered by different signals.
def shadowless_index(base):
    """normalised basename -> shadowless file path."""
    root = os.path.join(base, "moderninteriors-win", "1_Interiors")
    out = {}
    for dirpath, _d, files in os.walk(root):
        if "Shadowless" not in dirpath:
            continue
        for fn in files:
            if fn.endswith(".png"):
                out[fn.replace("Shadowless_", "")] = os.path.join(dirpath, fn)
    return out


def shadow_facets(path, shadowless):
    """Compare a sprite with its shadowless twin to isolate the drop shadow."""
    twin = shadowless.get(os.path.basename(path))
    if twin is None:
        return {}
    a = np.asarray(Image.open(path).convert("RGBA"))
    b = np.asarray(Image.open(twin).convert("RGBA"))
    if a.shape != b.shape:
        return {}
    diff = (a != b).any(axis=2)
    if not diff.any():
        return {"has_shadow": False}
    ys, xs = np.nonzero(diff)
    return {
        "has_shadow": True,
        # the shadow's bounding box, in pixels, within the sprite
        "shadow_bbox": [int(xs.min()), int(ys.min()),
                        int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
    }


# ------------------------------------------------------------------ pixel facets
def pixel_facets(path, tile):
    """Measure facets straight off the art. Objective, works for unnamed assets."""
    a = np.asarray(Image.open(path).convert("RGBA"))
    h, w = a.shape[:2]
    alpha = a[:, :, 3]
    solid = alpha == 255
    if not solid.any():
        return {"empty": True}

    ys, xs = np.nonzero(alpha > 0)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    f = {
        "px": [w, h],
        "bbox": [x0, y0, x1 - x0 + 1, y1 - y0 + 1],
        "coverage": round(float(solid.mean()), 3),
        # what the sprite touches tells you where it belongs
        "touches_bottom": bool((alpha[-1] > 0).any()),
        "touches_top": bool((alpha[0] > 0).any()),
        "full_bleed": bool(alpha.min() == 255),
    }

    # Surface finish, from local pixel-to-pixel variation. Office desks come in
    # smooth, grained and woven finishes that are otherwise identical objects, so
    # this is a style facet rather than a concept split -- it is what lets a
    # generated room pick furniture that matches.
    rgbi = a[:, :, :3].astype(np.int16)
    pair = (alpha[:, 1:] == 255) & (alpha[:, :-1] == 255)
    if pair.sum() >= 32:
        tex = float(np.abs(rgbi[:, 1:] - rgbi[:, :-1]).mean(axis=2)[pair].mean())
        f["texture"] = round(tex, 2)
        f["finish"] = "smooth" if tex < 3 else ("grained" if tex < 9 else "woven")

    # dominant colours by area -- the basis for style/tone matching
    rgb = a[:, :, :3][solid]
    if len(rgb):
        packed = (rgb[:, 0].astype(np.uint32) << 16 | rgb[:, 1].astype(np.uint32) << 8
                  | rgb[:, 2].astype(np.uint32))
        vals, counts = np.unique(packed, return_counts=True)
        order = np.argsort(-counts)[:5]
        f["palette"] = [f"#{int(vals[i]):06x}" for i in order]
        f["n_colours"] = int(len(vals))

    # Does it tile seamlessly as ground? Two conditions, because matching edges
    # alone is not enough: a ball centred on a plain background has matching edges
    # but repeats as a grid of balls rather than reading as terrain.
    if f["full_bleed"] and w == tile and h == tile:
        rgbf = a[:, :, :3].astype(np.int16)
        seam = (np.abs(rgbf[:, 0] - rgbf[:, -1]).mean()
                + np.abs(rgbf[0, :] - rgbf[-1, :]).mean())
        # homogeneity: spread of 8x8 block means. Terrain is uniform across the
        # tile; a tile with a distinct object in it is not.
        b = tile // 4
        blocks = rgbf[: b * 4, : b * 4].reshape(4, b, 4, b, 3).mean(axis=(1, 3))
        spread = float(blocks.reshape(-1, 3).std(axis=0).mean())
        f["seam"] = round(float(seam), 2)
        f["block_spread"] = round(spread, 2)
        f["tileable"] = bool(seam < 6.0 and spread < 12.0)
    return f


def placement_hint(nf, pf):
    """A single coarse guess at where a thing goes. Absent when unclear."""
    if pf.get("empty"):
        return None
    if pf.get("has_shadow") is True:
        return "floor"
    if pf.get("has_shadow") is False and not pf.get("tileable"):
        return "mounted"
    if pf.get("tileable") or "ground" in nf.get("concept", "") \
            or nf.get("head") in ("sidewalk", "asphalt", "grass", "dirt", "floor"):
        return "terrain"
    if pf.get("touches_top") and not pf.get("touches_bottom"):
        return "mounted"        # hangs: signs, lamps, wall art, ceiling fixtures
    if pf.get("touches_bottom"):
        return "floor"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category")
    ap.add_argument("--pack")
    ap.add_argument("--size", default="32", choices=["16", "32", "48"])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    sel = [e for e in cat["assets"]
           if a.size in e["paths"]
           and (a.category is None or e["category"] == a.category)
           and (a.pack is None or e["pack"] == a.pack)
           and e["kind"] in ("single", "animated")]
    if a.limit:
        sel = sel[: a.limit]

    tile = int(a.size)
    out = {}
    shadowless = shadowless_index(base)
    for e in sel:
        path = os.path.join(base, e["paths"][a.size])
        nf = {} if re.fullmatch(r"n\d+", e["name"]) else name_facets(e["name"])
        pf = pixel_facets(path, tile)
        pf.update(shadow_facets(path, shadowless))
        rec = {"name_facets": nf, "pixel_facets": pf}
        # frame strips are not single sprites, so the placement heuristics
        # (which read sprite edges) would misread them
        if e["kind"] != "animated":
            hint = placement_hint(nf, pf)
            if hint:
                rec["placement"] = hint
        out[e["id"]] = rec

    json.dump({"size": a.size, "assets": out}, open(a.out, "w"), separators=(",", ":"))

    named = sum(1 for r in out.values() if r["name_facets"].get("concept"))
    place = collections.Counter(r.get("placement") for r in out.values())
    tileable = sum(1 for r in out.values() if r["pixel_facets"].get("tileable"))
    print(f"{len(out)} assets -> {a.out}")
    print(f"  with a parsed concept: {named} ({100*named/max(len(out),1):.0f}%)")
    print(f"  placement hints: {dict(place)}")
    print(f"  seamlessly tileable: {tileable}")


if __name__ == "__main__":
    main()
