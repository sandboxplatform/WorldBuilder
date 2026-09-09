#!/usr/bin/env python3
"""
Tiled JSON <-> WorldBuilder neutral format.

GID decoding is the whole trick. A Tiled tile layer stores a flat array of GIDs.
GID 0 is empty; otherwise the tileset is the one with the greatest firstgid <= gid,
and the tile's position inside that tileset image is:

    local = gid - firstgid
    col, row = local % columns, local // columns

The top three bits of a GID are flip flags, so they must be masked off first.

Importing needs the reverse -- (sheet, col, row) -> asset id -- which comes from
catalog/sheet_xy.json. Any cell that does not resolve is reported, never guessed.
"""
import json, os

FLIP_H, FLIP_V, FLIP_D = 0x80000000, 0x40000000, 0x20000000
FLIP_MASK = FLIP_H | FLIP_V | FLIP_D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def decode_gid(gid):
    """Split a raw GID into (tile_id, flip_string)."""
    flips = ""
    if gid & FLIP_H:
        flips += "h"
    if gid & FLIP_V:
        flips += "v"
    return gid & ~FLIP_MASK, flips


def tileset_for(gid, tilesets):
    """The tileset a GID belongs to: greatest firstgid not above it."""
    best = None
    for ts in tilesets:
        if ts["firstgid"] <= gid and (best is None or ts["firstgid"] > best["firstgid"]):
            best = ts
    return best


def gid_to_cell(gid, tilesets):
    """(tileset, col, row, flips) for a raw GID, or None for an empty cell."""
    tid, flips = decode_gid(gid)
    if tid == 0:
        return None
    ts = tileset_for(tid, tilesets)
    if ts is None:
        return None
    local = tid - ts["firstgid"]
    cols = ts.get("columns") or 1
    return ts, local % cols, local // cols, flips


def sheet_name(ts):
    """A stable key for a tileset: its image basename, else its name."""
    img = ts.get("image")
    return os.path.basename(img) if img else ts.get("name", "?")


def load_reverse_index(path=None):
    """
    (sheet_basename, col, row) -> asset id, from catalog/sheet_xy.json.

    An asset spans several tiles; every covered cell maps back to it, with its
    top-left cell marked so an importer can place the object once.
    """
    path = path or os.path.join(ROOT, "catalog", "sheet_xy.json")
    if not os.path.exists(path):
        return {}, {}
    data = json.load(open(path))
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    index = {e["id"]: e for e in cat["assets"]}
    size = data["size"]

    cell_to_asset, origins = {}, {}
    for aid, loc in data["located"].items():
        sheet = index.get(loc["sheet"])
        if sheet is None or size not in sheet["paths"]:
            continue
        base = os.path.basename(sheet["paths"][size])
        cx, cy = loc["tile"]
        sw, sh = loc["span"]
        origins[(base, cx, cy)] = aid
        for dy in range(sh):
            for dx in range(sw):
                cell_to_asset.setdefault((base, cx + dx, cy + dy), aid)
    return cell_to_asset, origins


def describe(path):
    """Summarise a Tiled map: layers, tilesets, and GID coverage."""
    m = json.load(open(path))
    ts = m["tilesets"]
    out = {"size": [m["width"], m["height"]], "tile": m["tilewidth"],
           "tilesets": [(sheet_name(t), t["firstgid"], t.get("tilecount")) for t in ts],
           "layers": []}
    for L in m["layers"]:
        if L["type"] == "tilelayer":
            used = sum(1 for g in L["data"] if g)
            out["layers"].append((L["name"], "tile", used))
        else:
            out["layers"].append((L["name"], "object", len(L.get("objects", []))))
    return out


if __name__ == "__main__":
    import sys, pprint
    pprint.pp(describe(sys.argv[1]))
