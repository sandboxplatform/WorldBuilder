# WorldBuilder map editor

Paint your own maps from any tile in the packs, control collision by hand, drop in a
character, walk the room to test it, and export a bundle other projects can use.

## Run

```bash
python3 tools/serve.py 8823
```

- editor — http://127.0.0.1:8823/editor/
- viewer — http://127.0.0.1:8823/viewer/

The server also serves `images/extracted`, so sheet images stream from where they
already live. Nothing is copied and nothing leaves the machine.

## New map

**New** opens a dialog rather than browser prompts. Size it however suits you:

- **tiles** or **pixels** -- the two fields are linked, edit either and the other follows
- **tile size** 16 / 32 / 48; changing it reflows the pixel figures
- **presets** for a room, a floor, or something large
- **drag on canvas…** dismisses the dialog and lets you **drag out the size directly**,
  with a live `W × H tiles · W × H px` readout as you go. `esc` cancels.

## Painting

The palette has two modes.

Both modes are chosen through one **thumbnail picker**: click the sheet button under
the mode buttons to open a searchable grid, grouped by pack (Exteriors, Interiors,
Modern Office, User Interface) with sub-groups for room builders, autotiles, animated
objects, vehicles and room designs. Type to filter, Enter takes the first match, Esc
closes.

Every entry carries a preview of one **real asset from that sheet or category** —
`catalog/sheet_xy.json` records which named sprites live inside which sheet, so the
fire station shows its fire truck. The 22 sheets with no located members (room-builder
parts, UI, autotiles) show their fullest 2×2 tile block instead, which is the honest
preview for a sheet of walls or floors. Previews are baked into two small atlases:

    python3 tools/build_thumbnails.py     # editor/thumbs_{sheets,cats}.{png,json}

Re-run it if `sheets.json` or `singles.json` is rebuilt. Missing atlases are not fatal
— the picker just shows blank tiles.

**sheets** — 69 sheets at 32px, 247,775 paintable tiles. Pick a sheet, then **drag
across the palette to grab a block** — that block is your stamp, so multi-tile objects
stay assembled instead of being placed a tile at a time. Includes the two enormous
"complete" sheets (the interiors one is 512×34048).

**singles** — 12,826 whole sprites in 58 categories, including **652 animated
objects** (doors, shutters, lamps, TVs). Animated entries show a small blue dot and
their frame count; they are stored as one placement and **play in the canvas**, and
their frame layout travels in the export manifest so the importing project can play
them too. Frame size is not stated anywhere in the packs — it is recovered from the
art by autocorrelating each strip's alpha profile. Not everything lives in a sheet:
about 2,141 of the pre-cut singles are pre-composed variants (a table with a coffee
machine on it) that appear nowhere as a contiguous block, so they can only be placed
whole. Picking one gives a sprite stamp; it exports as an object placement.

| | |
|---|---|
| `wasd` / `arrows` | pan the canvas · `shift` for 4 tiles at a time |
| `b` paint · `e` erase · `r` rect · `f` fill · `i` pick | `h` or `space` pan tool |
| `v` select · `m` move | `esc` clear selection |
| `alt`+click on the map | eyedropper (also selects that layer and sheet) |
| `[` `]` | change layer · `g` grid · `c` collision view |
| `-` `=` or wheel | zoom · `ctrl+z` undo · `ctrl+s` save |

## Layout

The three columns resize: drag either gutter, double click one to restore its default.
There is no fixed pixel cap — a panel can take as much of the window as it likes, so
long as the map keeps 280px; on a wide screen that means genuinely wide panels, and
the limit re-clamps if you shrink the window.
Either side panel folds away to give the map the space: **◧** and **◨** in the header,
or the chevron tab at the top of each gutter. The chevron stays put when the panel
goes, so the way out is where the way in was, and the header button lights up while
its panel is hidden. The
palette resizes on its own bottom edge. Every size and collapsed state persists per
browser.

## Saving and deleting

**Save** writes the map into `maps/`; **load…** lists what is there. **Delete** removes
the saved copy of the world named in `load…` (or the name box), along with any export
bundle built from it — leaving that behind would keep a stale zip downloadable for a
world that no longer exists. It asks first, naming the world, because it is the one
action here with no undo. Whatever is on the canvas is left alone: losing the file you
saved should not also lose what is on screen.

## Tools

Each tool button carries an icon and, on hover, a one-line explanation with its
keyboard shortcut — the words alone ("rect", "pick", "pan") only make sense once you
already know them. The same tooltip appears on the header buttons and the collision
overrides.

| tool | what it does | key |
|---|---|---|
| paint | paint the stamp onto the current layer | `b` |
| erase | erase, removing the whole multi-tile group | `e` |
| rect | drag a rectangle, fill it with the stamp | `r` |
| fill | flood fill connected matching tiles | `f` |
| pick | eyedropper (`alt`+click works from any tool) | `i` |
| pan | drag to scroll the view | `h` / `space` |
| move | drag a placed sprite; arrows nudge it | `m` |
| select | drag a box — it deletes, and masks editing | `v` |

## Light and dark

The header button cycles three states: **◐ system** (the default — follows your OS
setting live, so the editor matches everything else on screen), **☀ light** and
**☾ dark**, which stay pinned until you cycle back round to system. The choice is
remembered per browser. All chrome reads CSS variables, so the switch is one attribute
on `<html>`; canvases ask for the current value when they repaint.

A map that has never been given a background of its own follows the theme, as does
the area outside the map bounds. A map carrying a deliberate background keeps it in
either theme — that is map data, not chrome, and it is what gets exported.

## Layers

Seven by default, matching Tiled's contract so exports drop into other projects
unchanged. Draw order is top to bottom in the list.

| Layer | Kind | Purpose | Blocks? |
|---|---|---|---|
| `floor` | tiles | the surface you stand on -- boards, carpet, paving, grass | no |
| `walls` | tiles | wall segments and their bases | **yes** |
| `ground` | tiles | things lying *on* the floor -- rugs, mats, paths, decals | no |
| `furniture` | tiles | the big stuff on the floor -- desks, counters, beds | **yes** |
| `objects` | tiles | smaller items, and things sitting on furniture | **yes** |
| `overhead` | tiles | drawn **above** the character -- treetops, ceiling fittings, upper walls | no |
| `props` | objects | whole sprites placed as single objects | **yes** |

"Blocks?" is what **from layers** marks solid. `ground` and `overhead` are
deliberately excluded: you walk over a rug and under a branch.

Add your own with **+ layer**; you choose tiles or objects.

## Lighting

The **night** slider previews the map after dark. Most lights are not placed at all:
they are read off the sprites you already put down — a street lamp lights because the
catalog knows it is a street lamp — using the same table and the same arithmetic
`tools/lights.py` uses at export, so the preview and the game agree. The panel says
how many came from sprites and how many you placed.

The **light** tool (`l`) places one by hand for where the art implies nothing: click to
drop, drag to move, and set radius, colour, flicker and whether it burns all the time
or only after dark. Hand-placed lights are saved in the map and travel with the export
alongside the derived ones.

The index the editor reads is built from the catalog:

```bash
python3 tools/build_lights_index.py
```

## Shadows

Characters carry no shadow of their own — measured: zero semi-transparent pixels along
the bottom of a frame — so in walk mode one is drawn for them. The pack's objects
already have theirs baked in, drawn for a sun off the upper left, and in daylight the
character's matches it.

After dark the sun is not what casts it. Every light in reach pulls the shadow away
from itself, weighted by how strongly it falls where the character stands, so walking
past a lamp swings the shadow around and stretches it as you leave the pool. Stand
where nothing lights you and there is nothing to cast one, and it fades away.

Objects deliberately get no second shadow. Interiors and Office ship separable
`Black_Shadow` and `Shadowless` sheets, but Exteriors do not — 144 incidental files
against ~31,700 — so their baked shadows cannot be removed, and a system that worked
indoors only would look inconsistent with the outdoor maps.

## Choosing what you draw on

Click a layer's **name** in the Layers list — that is the one every stroke lands on,
tiles and sprites alike. It gets an accent bar and its name in bold, and the status
line at the bottom of the canvas reads `12,7 → furniture` so you can see the target
without looking away from the map. `[` and `]` step through the layers.

The checkbox beside each name is visibility only. Ticking it hides or shows that
layer and never changes what you are drawing on.

## Putting a sprite on a chosen layer

Select a layer and place a sprite, and it lands on **that** layer — not on `props`.
Any layer can hold both tiles and sprites; a layer's sprites draw above its own tiles
and below the next layer, which is what makes "put this lamp on overhead" mean
something. They block from where they sit, save with their layer, and the sprite count
shows beside the layer name.

## Stacking tiles in one cell

Every tile layer has its own grid, so one cell holds **one tile per layer** — six of
them (floor, walls, ground, furniture, objects, overhead), drawn in that order. Sand
with see-through edges laid on `ground` over grass on `floor` shows the grass through
the gaps; that is the whole point of the layer order.

What does *not* work is painting both on the same layer. One cell holds one tile per
layer, so the sand replaces the grass and its see-through parts show bare canvas. When
that happens the editor now says so and names the layer to use instead.

## Stamps and transparency

A stamp block is a rectangle, but the art inside it rarely is. The camping dock has
transparent corners, and writing those cells anyway used to replace whatever they were
laid over — water became blank canvas. Cells that are fully transparent in the sheet
are now skipped, so a stamp only ever adds pixels and you can lay a dock straight over
water. Emptiness is measured from the sheet itself, one tile at a time and cached, so
it holds for any sheet without another build step.

## Two kinds of layer

**Tile layers** (`floor, walls, ground, furniture, objects, overhead`) snap to the
grid and hold tile refs.

**Object layers** (`props`, plus any you add) hold whole sprites. These still land
**on the grid**: an object snaps by its own footprint, so a 1x3 lamp and a 3x2 desk
both sit square in their cells even though they cover different areas.

| | |
|---|---|
| **snap** | tile (default) or half tile |
| `m` or **move** | select an object, drag it -- it stays snapped |
| `arrows` | nudge the selected object; otherwise they pan |
| `del` | remove the selected object |

## Erasing and selecting

**Erase takes the whole object.** A multi-tile stamp is remembered as one piece, so
clicking erase on any cell of a 3x2 desk removes all six -- you cannot punch a hole
in the middle of something. On an object layer, erase removes the whole sprite under
the cursor. (The grouping is saved with the map, so it still works after reopening.)

**`v` select** does two things:

- **click an object** to grab it and drag it, still snapped to the grid
- **drag on empty space** to pull a marquee, then `del` to delete everything inside

While a selection is up it **masks editing** -- painting, filling and object placement
are confined to it, which is how you fill one room without spilling over the edge. A
`masked N×N ✕` badge appears in the header; click it or press `esc` to clear. Clicking
outside the selection tells you why nothing happened rather than silently ignoring you.

Marquee delete clears tiles and objects across every *visible* layer -- hide a layer
to protect it. Collision is left alone; it has its own paint/erase tools. `esc`
clears the selection.

Offsets survive save, the renderer, and the atlas export -- the exporter slices an
off-grid sprite on its own offset grid, so nothing is clipped.

Toggle layer visibility with the checkbox, select by clicking the name. Object layers
are tagged `obj`.

## Collision

**Sensible by default, yours to override.**

With **auto** on (the default), collision follows what each thing actually is. The
defaults come from the labelling pass and the shadow measurements:

| | |
|---|---|
| stands on the floor | blocks, over the patch where it **meets the floor** -- not its whole sprite |
| rug or mat (`floor_overlay`) | never blocks |
| sitting on a desk (`on_surface`) | never blocks; the desk under it does |
| wall-hung (`wall`) | never blocks; you walk beneath it |
| tile layers | `walls`, `furniture`, `objects` block; `floor`, `ground`, `overhead` do not |

**paint** and **erase** record an override for that tile which **wins over the
default and survives further editing** -- so you can carve a doorway through a wall
run, or make one shelf walk-through, and it stays that way as you keep building.
Overrides are saved with the map.

**rebuild** throws the overrides away and re-derives from scratch. **clear** empties
collision and turns auto off, leaving it entirely manual. `c` shows the overlay.

Unlabelled themes fall back to "blocks", since most objects do. The five labelled
themes (kitchen, office, bathroom, living room, conference hall) get the finer
per-object defaults.

## Character and playtest

Choose any of the 29 character sheets (premade characters first, then bare bodies),
place a spawn with **set spawn**, then **▶ walk** to walk the map with the collision
you painted. `esc` or the button stops. Frame layout and the direction order come from
`catalog/char_animations.json`, measured off the sheets.

A map remembers which character it was built for.

## Export

**export bundle** writes `out/<name>/`:

| File | |
|---|---|
| `<name>.json` | Tiled map, tile layers, Tiled's layer contract |
| `<name>_atlas.png` | every tile the map uses, deduplicated |
| `character.png` | the chosen sheet |
| `manifest.json` | size, tile size, collisions, spawns, character frame layout |

The atlas means the bundle is **self-contained** — no dependency on the source packs
at run time, and composites and pixel-cropped sprites all survive, which they cannot
when referencing the stock sheets by GID.

## Tests

Two suites, both meant to be run after any change.

**Tools and data** — `python3 tools/selftest.py`. 15 checks: catalog paths resolve and
ids are unique, the editor indexes agree with the catalog, sheet labels are distinct,
animation frame layouts divide their sheets exactly, collision defaults match the
labelled placements, every saved map validates, the generated scene is fully
reachable, render and atlas export round-trip, the 18 WaterCooler maps still
round-trip, index builders are idempotent, and every element id the editor JS
references actually exists in the HTML.

**Editor** — open the editor, then in the console:

```js
await import('./selftest.js').then(m => m.run())
```

42 checks driving the real UI through synthetic events: multi-tile stamps, rect fill
and single-click, whole-group erase (including after a save/load cycle), flood fill,
eyedropper, object snapping, select-and-drag, the marquee mask and its warning,
marquee delete, undo/redo, save/reload fidelity, export, walk mode honouring
collision, animation playback, tile-size switching, painting outside the map, the
thumbnail picker (cell count matches the option list, every cell has a preview,
choosing one moves the palette), picker search and its empty state, the theme toggle
cycling system/light/dark and repainting both chrome and canvas, column resizing with its clamps and reset, and
every tool having an icon, a tip and a shortcut that shows on hover, and
deleting a saved world including the cancel path, collapsing
each side panel and restoring it, a stamp leaving what is under its transparent
cells alone, a sprite landing on the chosen layer and surviving a save, and the
active layer being marked, named in the status line and unaffected by the
visibility box, a cell stacking a tile on every layer with the lower one
showing through the upper one's gaps, and the warning naming where to put a
see-through tile.

## Licensing

The packs are licensed and must not be redistributed. `out/` and `viewer/assets/` are
gitignored. Ship maps and atlases inside your own projects; do not publish the source
art.
