#!/usr/bin/env python3
"""
Import a Tiled JSON map into the WorldBuilder neutral format.

Tile layers become terrain layers of tile refs (lossless -- every painted cell is
addressed exactly). Object layers carrying gids become object layers of placements.
Plain rectangle layers become collisions / spawns / pois / regions.

Tilesets are matched to catalog sheets by image basename, so a map that points at
its own copy of the packs still resolves.

    python tools/import_tiled.py ../WaterCooler/public/maps/office2.json out.json
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refs as refs_mod
import tiled_io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECT_LAYERS = {"collisions", "spawns", "pois", "transitions", "regions"}


def sheet_by_basename(size):
    """basename of a sheet image at this tile size -> catalog sheet id."""
    _cat, index = refs_mod.catalog()
    out = {}
    for e in index.values():
        if e["kind"] in ("sheet", "roombuilder") and size in e["paths"]:
            out[os.path.basename(e["paths"][size])] = e["id"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tiled")
    ap.add_argument("out")
    ap.add_argument("--background", default="#00000000")
    a = ap.parse_args()

    m = json.load(open(a.tiled))
    T = m["tilewidth"]
    size = str(T)
    cols, rows = m["width"], m["height"]
    by_base = sheet_by_basename(size)

    resolved, unresolved = {}, []
    for ts in m["tilesets"]:
        base = tiled_io.sheet_name(ts)
        sid = by_base.get(base)
        if sid:
            resolved[ts["firstgid"]] = sid
        else:
            unresolved.append(base)

    def ref_for(gid):
        cell = tiled_io.gid_to_cell(gid, m["tilesets"])
        if cell is None:
            return None, ""
        ts, col, row, flips = cell
        sid = resolved.get(ts["firstgid"])
        if sid is None:
            return None, flips
        return refs_mod.make_tile_ref(sid, col, row), flips

    layers, extras = [], {"collisions": [], "spawns": [], "pois": [], "regions": []}
    lost = 0

    for L in m["layers"]:
        name = L["name"]
        if L["type"] == "tilelayer":
            pal, pi = [], {}
            grid = [[-1] * cols for _ in range(rows)]
            for i, gid in enumerate(L["data"]):
                if not gid:
                    continue
                ref, _ = ref_for(gid)
                if ref is None:
                    lost += 1
                    continue
                if ref not in pi:
                    pi[ref] = len(pal)
                    pal.append(ref)
                grid[i // cols][i % cols] = pi[ref]
            if pal:
                layers.append({"name": name, "role": "terrain",
                               "palette": pal, "grid": grid})
            continue

        objs = L.get("objects", [])
        if name in RECT_LAYERS or not any(o.get("gid") for o in objs):
            for o in objs:
                rect = [round(o["x"] / T), round(o["y"] / T),
                        max(1, round(o.get("width", T) / T)),
                        max(1, round(o.get("height", T) / T))]
                if name == "collisions":
                    extras["collisions"].append(rect)
                elif name in ("spawns", "pois"):
                    extras[name].append({"name": o.get("name") or f"{name[:-1]}_{o['id']}",
                                         "at": rect[:2]})
                else:
                    extras["regions"].append(
                        {"name": o.get("name") or f"{name}_{o['id']}", "rect": rect})
            continue

        placements = []
        for o in objs:
            gid = o.get("gid")
            if not gid:
                continue
            ref, flips = ref_for(gid)
            if ref is None:
                lost += 1
                continue
            # Tiled anchors tile-objects at their BOTTOM-left corner
            x = round(o["x"] / T)
            y = round((o["y"] - o.get("height", T)) / T)
            p = {"id": ref, "at": [x, y]}
            if flips:
                p["flip"] = flips
            placements.append(p)
        if placements:
            layers.append({"name": name, "role": "objects", "placements": placements})

    out = {"format": "worldbuilder-map/1", "tile": T, "size": [cols, rows],
           "background": a.background, "layers": layers, **extras}
    json.dump(out, open(a.out, "w"), indent=1)

    print(f"imported {os.path.basename(a.tiled)} -> {a.out}")
    print(f"  {cols}x{rows} @ {T}px, {len(layers)} layers")
    print(f"  tilesets resolved: {len(resolved)}/{len(m['tilesets'])}")
    if unresolved:
        print(f"  UNRESOLVED tilesets: {unresolved}")
    if lost:
        print(f"  WARNING: {lost} cells/objects dropped (unresolved tileset)")
    return 1 if (unresolved or lost) else 0


if __name__ == "__main__":
    sys.exit(main())
