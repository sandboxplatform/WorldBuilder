#!/usr/bin/env python3
"""
Export a WorldBuilder map to Tiled JSON.

Tilesets are derived from the refs the map actually uses: every sheet referenced
becomes one tileset, and firstgids are assigned in a stable order. Object refs are
resolved to their covering sheet tiles via catalog/sheet_xy.json where available;
refs that cannot be expressed as sheet tiles are reported rather than dropped
silently.

    python tools/export_tiled.py map.json out.json [--profile watercooler]
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refs as refs_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# WaterCooler's layer contract: which of its layers are tile layers, and which
# object layers hold sprites rather than plain rectangles.
PROFILES = {
    "watercooler": {
        "tile_layers": ["floor", "walls", "ground", "furniture", "objects", "overhead"],
        "object_layers": ["props", "props-over"],
        "rect_layers": ["collisions", "pois", "spawns", "transitions"],
    },
    "generic": {"tile_layers": None, "object_layers": None,
                "rect_layers": ["collisions", "pois", "spawns", "transitions"]},
}


def sheet_of(ref, size, xy):
    """(sheet_id, col, row) for a ref, or None if it cannot be placed in a sheet."""
    if refs_mod.is_tile_ref(ref):
        sid, col, row = refs_mod.parse_tile_ref(ref)
        return sid, col, row
    loc = xy.get(ref)
    if loc is None:
        return None
    return loc["sheet"], loc["tile"][0], loc["tile"][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mapfile")
    ap.add_argument("out")
    ap.add_argument("--profile", default="generic", choices=sorted(PROFILES))
    ap.add_argument("--image-prefix", default="../tilesets/",
                    help="path prefix written into each tileset's image field")
    a = ap.parse_args()

    m = json.load(open(a.mapfile))
    size = str(m["tile"])
    T = m["tile"]
    cols, rows = m["size"]
    _cat, index = refs_mod.catalog()

    xy_path = os.path.join(ROOT, "catalog", "sheet_xy.json")
    xy = json.load(open(xy_path))["located"] if os.path.exists(xy_path) else {}

    # collect the sheets this map needs, in first-use order
    order, unplaceable = [], []
    for L in m["layers"]:
        srcs = L["palette"] if L["role"] == "terrain" else [p["id"] for p in L["placements"]]
        for ref in srcs:
            got = sheet_of(ref, size, xy)
            if got is None:
                unplaceable.append(ref)
                continue
            if got[0] not in order:
                order.append(got[0])

    tilesets, firstgid = [], 1
    gid_base = {}
    for sid in order:
        e = index[sid]
        w, h = e["px"][size]
        c, r = w // T, h // T
        tilesets.append({
            "columns": c, "firstgid": firstgid,
            "image": a.image_prefix + os.path.basename(e["paths"][size]),
            "imagewidth": w, "imageheight": h, "margin": 0, "spacing": 0,
            "name": sid, "tilecount": c * r, "tilewidth": T, "tileheight": T,
        })
        gid_base[sid] = (firstgid, c)
        firstgid += c * r

    def gid(ref):
        got = sheet_of(ref, size, xy)
        if got is None:
            return 0
        sid, col, row = got
        base, c = gid_base[sid]
        return base + row * c + col

    prof = PROFILES[a.profile]
    layers, lid = [], 1
    for L in m["layers"]:
        if L["role"] == "terrain":
            pal = [gid(r) for r in L["palette"]]
            data = [0 if v == -1 else pal[v] for row in L["grid"] for v in row]
            layers.append({"type": "tilelayer", "name": L["name"], "id": lid,
                           "width": cols, "height": rows, "x": 0, "y": 0,
                           "opacity": 1, "visible": True, "data": data})
        else:
            objs = []
            for j, p in enumerate(L["placements"], 1):
                ref = p["id"]
                g = gid(ref)
                if not g:
                    continue
                _im, (fw, fh) = refs_mod.resolve(ref, size)
                objs.append({"gid": g, "id": lid * 1000 + j, "name": "", "type": "",
                             "rotation": 0, "visible": True,
                             "width": fw * T, "height": fh * T,
                             "x": p["at"][0] * T, "y": (p["at"][1] + fh) * T})
            layers.append({"type": "objectgroup", "name": L["name"], "id": lid,
                           "x": 0, "y": 0, "opacity": 1, "visible": True,
                           "draworder": "topdown", "objects": objs})
        lid += 1

    for name in prof["rect_layers"]:
        objs, n = [], 1
        if name == "collisions":
            for x, y, w, h in m.get("collisions", []):
                objs.append({"id": lid * 1000 + n, "name": "", "type": "", "rotation": 0,
                             "visible": True, "x": x * T, "y": y * T,
                             "width": w * T, "height": h * T}); n += 1
        elif name in ("pois", "spawns"):
            for o in m.get(name, []):
                objs.append({"id": lid * 1000 + n, "name": o["name"], "type": "",
                             "rotation": 0, "visible": True,
                             "x": o["at"][0] * T, "y": o["at"][1] * T,
                             "width": T, "height": T}); n += 1
        else:
            for o in m.get("regions", []):
                x, y, w, h = o["rect"]
                objs.append({"id": lid * 1000 + n, "name": o["name"], "type": "",
                             "rotation": 0, "visible": True, "x": x * T, "y": y * T,
                             "width": w * T, "height": h * T}); n += 1
        layers.append({"type": "objectgroup", "name": name, "id": lid, "x": 0, "y": 0,
                       "opacity": 1, "visible": True, "draworder": "topdown",
                       "objects": objs})
        lid += 1

    out = {"compressionlevel": -1, "width": cols, "height": rows,
           "tilewidth": T, "tileheight": T, "infinite": False,
           "orientation": "orthogonal", "renderorder": "right-down", "type": "map",
           "version": "1.10", "tiledversion": "1.11.2",
           "nextlayerid": lid, "nextobjectid": lid * 1000,
           "tilesets": tilesets, "layers": layers}
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"exported -> {a.out}: {len(tilesets)} tilesets, {len(layers)} layers")
    if unplaceable:
        u = sorted(set(unplaceable))
        print(f"  WARNING: {len(u)} ref(s) have no sheet position and were dropped: {u[:4]}")
    return 1 if unplaceable else 0


if __name__ == "__main__":
    sys.exit(main())
