#!/usr/bin/env python3
"""
Read, write and validate WorldBuilder maps (see FORMAT.md).

    python tools/mapfmt.py maps/demo_street.json        # validate
    python tools/mapfmt.py maps/old.json --migrate out.json
"""
import argparse, json, os, sys

sys_path = os.path.dirname(os.path.abspath(__file__))
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
import refs as refs_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMAT = "worldbuilder-map/1"
ROLES = ("terrain", "objects")


def load_catalog():
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    return {e["id"]: e for e in cat["assets"]}


def validate(m, index=None):
    """Return a list of human-readable problems; empty means valid."""
    errs = []
    if m.get("format") != FORMAT:
        errs.append(f"format must be {FORMAT!r}, got {m.get('format')!r}")
    tile = m.get("tile")
    if tile not in (16, 32, 48):
        errs.append(f"tile must be 16, 32 or 48, got {tile!r}")
    size = m.get("size")
    if not (isinstance(size, list) and len(size) == 2
            and all(isinstance(v, int) and v > 0 for v in size)):
        errs.append(f"size must be [cols, rows] of positive ints, got {size!r}")
        return errs
    cols, rows = size

    def known(aid, where):
        if index is None:
            return True
        problem = refs_mod.check(aid, str(tile))
        if problem:
            errs.append(f"{where}: {problem}")
            return False
        return True

    for i, L in enumerate(m.get("layers", [])):
        where = f"layer[{i}] {L.get('name', '?')!r}"
        role = L.get("role")
        if role not in ROLES:
            errs.append(f"{where}: role must be one of {ROLES}, got {role!r}")
            continue

        if role == "terrain":
            pal = L.get("palette", [])
            grid = L.get("grid", [])
            # optional editor hint: which cells came from one multi-tile stamp, so
            # the editor can erase them as a unit. Renderers ignore it.
            groups = L.get("groups")
            if groups is not None and len(groups) != rows:
                errs.append(f"{where}: groups has {len(groups)} rows, map is {rows}")
            for aid in pal:
                known(aid, where + " palette")
            if len(grid) != rows:
                errs.append(f"{where}: grid has {len(grid)} rows, map is {rows}")
            for r, row in enumerate(grid):
                if len(row) != cols:
                    errs.append(f"{where}: grid row {r} has {len(row)} cells, map is {cols}")
                    continue
                for c, v in enumerate(row):
                    if v != -1 and not (0 <= v < len(pal)):
                        errs.append(f"{where}: grid[{r}][{c}]={v} outside palette "
                                    f"of {len(pal)}")
        else:
            for j, p in enumerate(L.get("placements", [])):
                pw = f"{where} placement[{j}]"
                aid, at = p.get("id"), p.get("at")
                if not (isinstance(at, list) and len(at) == 2):
                    errs.append(f"{pw}: 'at' must be [x, y], got {at!r}")
                    continue
                x, y = at
                if not (0 <= x < cols and 0 <= y < rows):
                    errs.append(f"{pw}: {aid!r} at {at} is outside the {cols}x{rows} map")
                known(aid, pw)
                if p.get("flip") not in (None, "h", "v", "hv"):
                    errs.append(f"{pw}: bad flip {p['flip']!r}")
                off = p.get("off")
                if off is not None and not (isinstance(off, list) and len(off) == 2
                                            and all(isinstance(v, int) for v in off)):
                    errs.append(f"{pw}: 'off' must be [dx, dy] pixels, got {off!r}")

    ov = m.get("collisionOverrides")
    if ov is not None and not isinstance(ov, list):
        errs.append("collisionOverrides must be a list of [cell, solid] pairs")
    for key in ("collisions",):
        for j, r in enumerate(m.get(key, [])):
            if not (isinstance(r, list) and len(r) == 4):
                errs.append(f"{key}[{j}] must be [x, y, w, h], got {r!r}")
    for key in ("spawns", "pois", "regions"):
        for j, o in enumerate(m.get(key, [])):
            if "name" not in o:
                errs.append(f"{key}[{j}] has no name")
    return errs


def migrate(old):
    """Lift the pre-v1 demo shape ({layers:[{tiles:[[id,x,y],...]}]}) into v1."""
    layers = []
    for L in old.get("layers", []):
        entries = L.get("tiles", [])
        ids = [e[0] for e in entries]
        # a layer that covers every cell with few distinct ids is terrain
        cols, rows = old["size"]
        if len(entries) >= cols * rows and len(set(ids)) <= 16:
            pal = sorted(set(ids))
            pi = {a: i for i, a in enumerate(pal)}
            grid = [[-1] * cols for _ in range(rows)]
            for aid, x, y in entries:
                if 0 <= x < cols and 0 <= y < rows:
                    grid[y][x] = pi[aid]
            layers.append({"name": L["name"], "role": "terrain",
                           "palette": pal, "grid": grid})
        else:
            layers.append({"name": L["name"], "role": "objects",
                           "placements": [{"id": a, "at": [x, y]}
                                          for a, x, y in entries]})
    return {"format": FORMAT, "tile": old.get("tile", 32), "size": old["size"],
            "background": old.get("background", "#00000000"), "layers": layers,
            "regions": [], "collisions": [], "spawns": [], "pois": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mapfile")
    ap.add_argument("--migrate", metavar="OUT", help="convert a pre-v1 map to v1")
    ap.add_argument("--no-catalog", action="store_true",
                    help="skip asset-id checks")
    a = ap.parse_args()

    m = json.load(open(a.mapfile))
    if a.migrate:
        m = migrate(m)
        json.dump(m, open(a.migrate, "w"), indent=1)
        print(f"migrated -> {a.migrate}")

    index = None if a.no_catalog else load_catalog()
    errs = validate(m, index)
    if errs:
        print(f"{len(errs)} problem(s):")
        for e in errs[:40]:
            print("  ", e)
        sys.exit(1)
    n_terr = sum(1 for L in m["layers"] if L["role"] == "terrain")
    n_obj = sum(len(L.get("placements", [])) for L in m["layers"])
    print(f"valid: {m['size'][0]}x{m['size'][1]} @ {m['tile']}px, "
          f"{len(m['layers'])} layers ({n_terr} terrain), {n_obj} placements")


if __name__ == "__main__":
    main()
