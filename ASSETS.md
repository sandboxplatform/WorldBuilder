# Asset system — how the packs work and how to reference them

Working notes + the addressing scheme the world builder will use.

## 1. What's in the box

Four LimeZu packs, unzipped to `images/extracted/` (93,001 PNGs, ~670 MB):

| Pack | Folder | What it gives you |
|---|---|---|
| Modern Interiors | `moderninteriors-win/` | Room shells + interior furniture, 26 themes, plus the character generator |
| Modern Exteriors | `modernexteriors-win/` | Terrain, buildings, streets, vehicles, 24 themes |
| Modern Office | `Modern_Office_Revamped_v1.2/` | Office furniture, one theme |
| Modern UI | `modernuserinterface-win/` | HUD/menu frames + a portrait generator |

**Licence: these packs may not be resold or redistributed.** Keep them local — never
bundle them into a published artifact, CDN, or public repo. Ship *maps* (which are
just lists of asset ids), not pixels.

## 2. The four shapes an asset comes in

Everything in every pack is one of these. This is the whole mental model.

**a) Theme sheets** — one big PNG per theme, strictly aligned to the tile grid.
`12_Kitchen_32x32.png` is 512×1568 = 16 × 49 tiles. Objects are laid out with
empty tiles between them. These are the *canonical* source: grid-true, and the
thing to slice into an atlas at build time.

**b) Singles** — the same objects pre-cut into standalone PNGs, ~12,500 of them.
This is what a world builder actually places. Two important caveats:
- *Exterior* singles are grid-aligned (a 2×2 object is exactly 64×64 px).
- *Interior* singles are **tightly cropped to the object's pixel bounds**, so a
  single can be 32×48 or 16×96. About 36% are not 32-multiples. They therefore
  carry no intrinsic grid anchor — see §5.

**c) Animated spritesheets** — horizontal frame strips. 473 exterior + 327 interior.
Frame count = `width / (tile_size × footprint_cols)`. Doors, lamps, TVs, shutters.
Vehicles are separate and much bigger (a helicopter sheet is 25536×3456).

**d) Layered character/portrait sheets** — a paperdoll system, not sprites.
Every layer PNG is the same 1792×1312 (at 32px) so layers composite directly.
The pack's stated order is **body → eyes → outfit → hairstyle → accessory**.
Available: 9 bodies, 7 eyes, 133 outfits, 201 hairstyles, 85 accessories, plus
kid variants — and 21 ready-made characters if you don't want to composite.

Everything ships at **16, 32 and 48 px** tile sizes in parallel folders. 32 is the
sensible default; the catalog keeps all three so the renderer can pick.

## 3. Also present, deliberately not indexed

- **Shadowless / Black_Shadow** variants of every interior + office asset (31,914
  files). Same objects, different drop shadow. Reachable by swapping the path
  segment, so indexing them would triple the catalog for no gain.
- **`Modern_Exteriors_Complete_Singles_*`** (18,581) — a flat copy of the same
  exterior singles that live in the per-theme folders. Deduped into one entry.
- **Legacy** (`Old_Stuff`, `2_Characters/Old`, `Previous_Version`) and the RPG Maker
  MV exports.

## 4. The addressing scheme

One string identifies any asset, at any tile size:

```
<pack>.<kind>.<category>.<name>
```

```
ext.single.city_props.bench_1          a bench you can place
int.single.kitchen.n123                interior object #123 in the kitchen theme
int.sheet.kitchen.sheet                the whole kitchen theme sheet
ext.animated.object.street_lamp        an animated prop
char.layer.hairstyles.hairstyle_01_01   one paperdoll layer
office.single.office.n42               an office object
```

- `pack` — `int` | `ext` | `office` | `char` | `ui`
- `kind` — `single` | `sheet` | `animated` | `layer` | `premade` | `design` |
  `roombuilder` | `autotile` | `vehicle` | `portrait` | `palette`
- `category` — the theme (`kitchen`, `city_props`, `graveyard`, …)
- `name` — the pack's own object name where it has one, else `n<number>`

Ids are **size-independent on purpose**. `catalog/catalog.json` holds one record per
logical asset with all three size variants:

```json
{
  "id": "ext.single.city_props.bench_1",
  "pack": "ext", "kind": "single",
  "category": "city_props", "name": "bench_1",
  "paths": { "16": "...", "32": "...", "48": "..." },
  "px":    { "16": [32,32], "32": [64,64], "48": [96,96] },
  "tiles": [2, 2],
  "grid_aligned": true,
  "sizes": ["16","32","48"]
}
```

`tiles` is the footprint in tile units — what a placement/collision system needs.
`grid_aligned` is false for the tightly-cropped interior singles.

Build and query it:

```bash
python tools/build_catalog.py          # rebuild catalog/catalog.json
python tools/validate.py               # check ids unique, paths resolve
python tools/query.py bench            # free-text
python tools/query.py --pack ext --tiles 2x3 tree
python tools/query.py --id ext.single.city_props.bench_1
python tools/query.py --categories
python tools/contact_sheet.py out.png --pack int --category kitchen
python tools/find_fill.py ext.single.terrains_and_fences.grass_1_
python tools/render.py maps/demo_street.json out.png --scale 2
```

A map file is then just ids plus positions — small, diffable, and legal to share:

```json
{ "tile": 32, "size": [40, 30],
  "layers": [
    { "name": "ground", "tiles": [["ext.single.city_terrains.asphalt_1_variation_1", 0, 0], ...] },
    { "name": "props",  "tiles": [["ext.single.city_props.bench_1", 12, 8], ...] }
  ] }
```

## 5. Terrain is autotiled — don't repeat tile #1

The single biggest gotcha found while building the demo. A terrain family like
`ext.single.terrains_and_fences.grass_1_*` is an **autotile set**, not 22
interchangeable grass tiles. Variants 1–20 are edges, corners and transitions;
only **21 (dirt) and 22 (grass) tile seamlessly**. Carpeting a map with
`grass_1_1` produces a grid of borders, not a lawn — which is exactly what the
first demo render did.

`tools/find_fill.py` scores every 1×1 variant in a family by how well it matches
itself when repeated, and reports the seamless ones:

```
$ python tools/find_fill.py ext.single.terrains_and_fences.grass_1_
     0.00  ext.single.terrains_and_fences.grass_1_21
     0.00  ext.single.terrains_and_fences.grass_1_22
    17.00  ext.single.terrains_and_fences.grass_1_9
```

Proper terrain painting needs a wang/blob mapping from neighbour-mask to variant
per family. Until that exists, ground layers should use only the fill tiles.

## 6. The two real problems to solve next

**Half the singles have no name.** 6,264 exterior singles are semantically named
(`Bench_1`, `ATM_1`, `Fire_Hydrant_2`) — you can prompt against those today. But all
6,200 interior + office singles are numbered only (`Kitchen_Singles_32x32_1.png`).
You cannot ask for "a fridge" until they're labelled. Fix: render contact sheets per
theme and label them with a vision pass, writing tags back into the catalog. The
theme folder already narrows it (a kitchen object is one of ~408), so this is
tractable and only has to be done once. `tools/contact_sheet.py` renders the
labelled, paged grids for that pass.

**Interior singles have no grid anchor.** Because they're pixel-cropped, placing one
on a 32px grid is guesswork. The parent theme sheet *is* grid-true, so the anchor can
be recovered by matching each single back into its sheet. Tested on the kitchen theme:
RGB-only comparison (ignoring alpha, since shadows bleed across object bounds in the
sheet) locates them exactly. Flat single-colour objects match in several places and
need a tie-break. Once recovered, store `sheet_xy` per asset and the ambiguity is gone
permanently.

## Building maps

Two routes, and they meet in the middle:

- **By hand** — `editor/` is a full tile editor: any tile from any sheet, multi-tile
  stamps, per-tile collision, layers, a character to walk the result, and export.
  Run `python3 tools/serve.py 8823` and open http://127.0.0.1:8823/editor/
- **Generated** — `scenes/*.py` compose rooms from the labelled catalog.

Generated maps load into the editor unchanged, so generation is a first draft you can
take over at any point.
