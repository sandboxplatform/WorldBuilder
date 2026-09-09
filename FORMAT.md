# WorldBuilder map format v1

The neutral format. Engine-specific encoding (GIDs, tileset images, layer naming)
belongs in exporters, never here.

## Design rule

Store **meaning**, not indices. A placement says *what* is where:

```json
{ "id": "ext.single.city_props.bench_1", "at": [12, 8] }
```

Tiled would store that as a GID — an integer index into one sheet image at one tile
size. That breaks when a sheet is re-exported, carries no meaning, and cannot be
searched or diffed. The semantic id survives re-indexing, reads as English in a
diff, is what a prompt produces, and downgrades to a GID on export.

## Two kinds of reference

Maps address art at two granularities, because tile layers and object layers work
differently.

```
ext.single.city_props.bench_1     object ref -- a whole catalogued object
tile:int.sheet.kitchen#3,10       tile ref   -- one cell of a sheet image
```

Tile layers are painted cell by cell, so most cells are *part* of an object rather
than a whole one and have no object id at all. Tile refs address those exactly,
which is what makes importing a hand-built map lossless. Object refs carry meaning
and are what prompts produce.

Both forms are valid anywhere a ref is expected. In practice generated maps lean on
object refs and hand-painted detail lands as tile refs.

## Two kinds of layer

Terrain and objects have genuinely different shapes, so they get different
representations rather than one compromise.

**Terrain** covers every cell, so a per-cell list would be mostly repetition. It
uses a palette plus a grid of indices; `-1` is empty:

```json
{
  "name": "ground",
  "role": "terrain",
  "palette": ["ext.single.terrains_and_fences.grass_1_22",
              "ext.single.city_terrains.asphalt_1_variation_23"],
  "grid": [[0,0,0,1,1], [0,0,0,1,1]]
}
```

**Objects** are sparse and individually meaningful, so they are a placement list:

```json
{
  "name": "props",
  "role": "objects",
  "placements": [
    { "id": "ext.single.city_props.bench_1", "at": [12, 8] },
    { "id": "ext.single.camping.tree_1", "at": [15, 2], "flip": "h" }
  ]
}
```

`at` is the tile coordinate of the placement's **top-left tile**. Assets taller than
their footprint are bottom-aligned within it, so they sit on the floor.

Objects may also carry a **sub-tile pixel offset**:

```json
{ "id": "int.single.living_room.n11", "at": [4, 1], "off": [30, 10] }
```

Objects still land **on the grid** -- an object snaps by its own footprint, so a 1x3
lamp and a 3x2 desk both sit square in their cells even though they cover different
areas. `off` exists for half-tile placement where the art is drawn for it, and is
optional: absent means tile-aligned, so older maps are unaffected.

(An earlier note here claimed the pack's designs place furniture freely, based on
content bounding boxes in the artist's layer PNGs landing at 2, 4 and 6 px offsets.
That was wrong: those offsets are transparent padding *inside* on-grid sprites, not
free placement. Content bounds are not placement positions.)

## Whole file

```json
{
  "format": "worldbuilder-map/1",
  "tile": 32,
  "size": [28, 18],
  "background": "#20202c",
  "layers": [ ... ],
  "regions":   [ { "name": "kitchen", "rect": [0, 0, 10, 8] } ],
  "collisions":[ [12, 8, 2, 1] ],
  "spawns":    [ { "name": "entrance", "at": [4, 17] } ],
  "pois":      [ { "name": "coffee", "at": [9, 5] } ]
}
```

- `tile` is a property, not an assumption — the same map exports at 16, 32 or 48.
- `regions` are what region-scoped prompt edits address ("restyle the kitchen").
- `collisions`, `spawns`, `pois` are engine-neutral; exporters map them onto whatever
  the target expects (for Tiled/WaterCooler, object layers of the same names).

## Validation

`tools/mapfmt.py` validates a map and fails loudly: unknown asset ids, out-of-bounds
placements, palette indices with no entry, ragged grids. A map that does not validate
is not exported.

```bash
python tools/mapfmt.py maps/demo_street.json
```
