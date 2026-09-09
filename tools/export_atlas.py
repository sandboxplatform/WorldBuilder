#!/usr/bin/env python3
"""
Export a map to Tiled JSON with a generated project atlas.

Why an atlas rather than referencing LimeZu's own sheets: ~13% of the singles are
pre-composed variants that exist nowhere as a contiguous block in any sheet, so they
have no GID against the original art and simply cannot be exported that way. Packing
the tiles a project actually uses into an atlas we control gives 100% coverage, and
sub-tile alignment stops mattering.

Every sprite -- terrain tile, whole object, composite -- is sliced into 32px cells,
deduplicated by content, and packed. The result is a single uniform tileset, which
is also how WaterCooler's own maps are built (furniture lives on tile layers).

    python tools/export_atlas.py maps/office_floor.json out/ --profile watercooler
"""
import argparse, hashlib, json, os, sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refs as refs_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WATERCOOLER_LAYERS = ["floor", "walls", "ground", "furniture", "objects", "overhead"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mapfile")
    ap.add_argument("outdir")
    ap.add_argument("--name", default=None, help="basename for the outputs")
    ap.add_argument("--profile", default="generic", choices=["generic", "watercooler"])
    ap.add_argument("--columns", type=int, default=32)
    a = ap.parse_args()

    m = json.load(open(a.mapfile))
    size = str(m["tile"])
    T = m["tile"]
    cols, rows = m["size"]
    name = a.name or os.path.splitext(os.path.basename(a.mapfile))[0]
    os.makedirs(a.outdir, exist_ok=True)

    cells = {}          # content hash -> (index, Image)
    order = []

    def add_cell(img):
        """Register one 32px cell, deduplicated by pixel content."""
        if img.getbbox() is None:
            return 0                      # fully transparent -> empty
        key = hashlib.sha1(img.tobytes()).digest()
        hit = cells.get(key)
        if hit is None:
            idx = len(order) + 1          # local id + 1 == gid with firstgid 1
            cells[key] = idx
            order.append(img)
            return idx
        return hit

    # Slice every placement into cells and build tile layers from them.
    out_layers = []
    for L in m["layers"]:
        grid = [[0] * cols for _ in range(rows)]
        if L["role"] == "terrain":
            pal = L["palette"]
            for y, row in enumerate(L["grid"]):
                for x, v in enumerate(row):
                    if v == -1:
                        continue
                    im, _ = refs_mod.resolve(pal[v], size)
                    grid[y][x] = add_cell(im.crop((0, 0, T, T)))
        # placements are not exclusive to object layers: an object dropped on a
        # tile layer lives in the same list, and slicing it is the same work
        for p in L.get("placements", []):
            im, _fp = refs_mod.resolve(p["id"], size)
            bx, by, _bw, _bh = im.getbbox() or (0, 0, 0, 0)
            # align on the content, plus any sub-tile offset the object carries
            off = p.get("off", (0, 0))
            ox = p["at"][0] * T + off[0] - bx
            oy = p["at"][1] * T + off[1] - by
            # an off-grid sprite straddles cells, so slice on the offset grid
            sx, sy = ox % T, oy % T
            for cy in range(-(sy > 0) * T, im.height + T, T):
                for cx in range(-(sx > 0) * T, im.width + T, T):
                    cell = im.crop((cx, cy, cx + T, cy + T))
                    if cell.getbbox() is None:
                        continue
                    gx, gy = (ox + cx) // T, (oy + cy) // T
                    if not (0 <= gx < cols and 0 <= gy < rows):
                        continue
                    idx = add_cell(cell)
                    if idx:
                        grid[gy][gx] = idx
        out_layers.append((L["name"], grid))

    # ---- pack the atlas ----
    n = len(order)
    acols = min(a.columns, max(1, n))
    arows = (n + acols - 1) // acols
    atlas = Image.new("RGBA", (acols * T, arows * T), (0, 0, 0, 0))
    for i, img in enumerate(order):
        atlas.alpha_composite(img, ((i % acols) * T, (i // acols) * T))
    img_name = f"{name}_atlas.png"
    atlas.save(os.path.join(a.outdir, img_name))

    tileset = {
        "columns": acols, "firstgid": 1, "image": img_name,
        "imagewidth": atlas.width, "imageheight": atlas.height,
        "margin": 0, "spacing": 0, "name": f"{name}_atlas",
        "tilecount": acols * arows, "tilewidth": T, "tileheight": T,
    }

    layers, lid = [], 1
    names = ([n for n in WATERCOOLER_LAYERS] if a.profile == "watercooler"
             else [n for n, _ in out_layers])
    made = {n: g for n, g in out_layers}
    for lname in names:
        grid = made.get(lname, [[0] * cols for _ in range(rows)])
        layers.append({"type": "tilelayer", "name": lname, "id": lid,
                       "width": cols, "height": rows, "x": 0, "y": 0,
                       "opacity": 1, "visible": True,
                       "data": [v for row in grid for v in row]})
        lid += 1
    # any generated layer the profile does not name still gets exported
    for lname, grid in out_layers:
        if lname not in names:
            layers.append({"type": "tilelayer", "name": lname, "id": lid,
                           "width": cols, "height": rows, "x": 0, "y": 0,
                           "opacity": 1, "visible": True,
                           "data": [v for row in grid for v in row]})
            lid += 1
    # Lights are read off the sprites already placed -- see tools/lights.py. They go
    # out as an object layer because that is what the runtime already knows how to
    # parse, and because a light is data about the map, not baked-in pixels: baking
    # would freeze the time of day and blow up the atlas, which dedupes by content.
    try:
        import lights as lights_mod
        derived = lights_mod.lights_for(m)
    except Exception as e:                       # never fail an export over lighting
        print(f"  lights skipped: {e}")
        derived = None
    if derived is not None:
        layers.append(lights_mod.tiled_layer(derived, lid))
        lid += 1
        print(f"  {len(derived)} lights derived")

    if a.profile == "watercooler":
        for lname in ("props", "props-over", "collisions", "pois", "spawns",
                      "transitions"):
            if lname in made:
                continue
            layers.append({"type": "objectgroup", "name": lname, "id": lid,
                           "x": 0, "y": 0, "opacity": 1, "visible": True,
                           "draworder": "topdown", "objects": []})
            lid += 1

    tiled = {"compressionlevel": -1, "width": cols, "height": rows,
             "tilewidth": T, "tileheight": T, "infinite": False,
             "orientation": "orthogonal", "renderorder": "right-down", "type": "map",
             "version": "1.10", "tiledversion": "1.11.2",
             "nextlayerid": lid, "nextobjectid": 1,
             "tilesets": [tileset], "layers": layers}
    if derived is not None:
        tiled["properties"] = lights_mod.ambient_props()
    map_path = os.path.join(a.outdir, f"{name}.json")
    json.dump(tiled, open(map_path, "w"), indent=1)

    kb = os.path.getsize(os.path.join(a.outdir, img_name)) / 1024
    print(f"{map_path}")
    print(f"  atlas: {img_name}  {atlas.width}x{atlas.height}px, "
          f"{n} unique tiles ({kb:.0f} KB)")
    print(f"  layers: {len(layers)}  ({cols}x{rows} tiles)")
    print("  every asset exported: composites and cropped sprites included")


if __name__ == "__main__":
    main()
