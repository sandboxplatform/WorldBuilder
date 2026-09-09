# WorldBuilder — build plan

**Goal:** build tile worlds from prompts plus UI tools.

**Decisions taken (2026-09-08):** neutral internal map format with per-engine
exporters · standalone web app · prompts produce a whole-map draft, then region edits.

---

## What the neutral format has to earn

A neutral format is only worth the extra layer if it stores something Tiled cannot.
It does: **semantic placements** rather than flattened tile indices.

```json
{ "id": "ext.single.city_props.bench_1", "at": [12, 8], "layer": "props" }
```

Tiled would store that as a GID — an integer index into a specific sheet image at a
specific tile size. That number breaks if the sheet is re-exported, carries no
meaning, and cannot be searched, diffed or reasoned about by a model. The semantic
id survives re-indexing, reads as English in a diff, is what a prompt actually
produces, and **downgrades to a GID on export**.

That is the design rule for the whole format: keep meaning in the core, push
engine-specific encoding into exporters. If a field only exists to satisfy Tiled,
it belongs in the exporter, not the format.

The demo map format already written is the rough shape of this. It needs
formalising, not inventing.

---

## Decisions (2026-09-08)

Neutral map format with per-engine exporters · standalone web app · whole-map draft
then region edits · **project-specific atlas** · groupings are the priority, taken
slowly · vision labelling fills the **full facet schema** · concepts come from a
**controlled list seeded from the pack names** · **one shared atlas per project** ·
sheet positions pushed to **maximum coverage**, decomposing composites.

The controlled-vocabulary choice creates an ordering constraint: the vocabulary has
to exist before the vision pass, because the vision pass selects from it. So
vocabulary comes before labelling, and the composite work runs alongside.

## Status

**The editor is built** — `editor/`, served by `tools/serve.py`. Paint from any of
245,279 tiles across 67 sheets, drag the palette to grab multi-tile blocks, control
collision by hand or derive it from layers, drop in any of 29 characters, walk the map
to test it, and export a self-contained bundle. Generated maps load straight into it,
so the generator is a starting point rather than the only route. See `editor/README.md`.

## Status (earlier)

Phases 1 and 2 are **done and passing**. `tools/roundtrip_test.py` round-trips all
18 hand-built WaterCooler maps through the neutral format with zero differences.

The design changed once along the way: tile layers are painted cell by cell, so most
cells are *part* of an object and have no object id. Adding a second reference form
(`tile:<sheet>#col,row` alongside `ext.single.city_props.bench_1`) made import
lossless and took `sheet_xy` off the critical path for round-tripping — though it is
still needed to export *generated* maps, which speak in object refs.

## Phase 1 — Core format and grid addressing

1. **Formalise the map format.** Layers, semantic placements, anchors, tile size as
   a property rather than an assumption, collision and spawn metadata. Write it as a
   schema with a validator, so bad maps fail loudly and early.
2. **Recover `sheet_xy` for every asset.** Any tilemap exporter needs to know an
   asset's `(sheet, column, row)` to compute a GID. Match each single back into its
   grid-true parent sheet by RGB comparison, ignoring alpha — shadows bleed across
   object bounds in the sheets. Already prototyped and working on the kitchen theme.
3. **Break the ties.** Flat single-colour objects match in several places. Prefer
   in-order positions, then flag whatever stays ambiguous for a visual check rather
   than guessing.

**Acceptance test:** every catalog asset resolves to a sheet position, or is
explicitly listed as unresolved. No silent guesses.

**Result:** ~87% located on the kitchen theme, 3 seconds per theme. The misses are
not matcher failures — they are **pre-composed variants** ("table + coffee machine",
"counter + open drawer") that the pack author assembled and exported as one file.
They exist nowhere as a contiguous block in any sheet, so they cannot be expressed
as a GID against the original sheets at all. See "Open question: atlases" below.

---

## Phase 2 — Exporter framework, and the first exporter

*Do this early, despite the neutral core.* The cost of a neutral format is that
nothing renders until an exporter exists, so the fix is to write one immediately
rather than building the core in the dark.

1. **Exporter interface**, so Phaser and Godot can follow later without reworking
   the core.
2. **Tiled exporter**, emitting standard Tiled JSON with GIDs computed from Phase 1.
3. **WaterCooler profile** on top of it: 48px, and its layer contract
   (`floor`, `walls`, `ground`, `furniture`, `objects`, `overhead`, `props`,
   `props-over` + object layers `collisions`, `pois`, `spawns`, `transitions`).

**Acceptance test — the one that proves the whole chain:** import an existing
hand-built map (`WaterCooler/public/maps/lobby.json`) into the neutral format, export
it back out, and get a visually identical map. Its two sheets already match the
catalog exactly — `Room_Builder_Office_48x48.png` (768×672, 224 tiles) →
`office.roombuilder.office`, and `Modern_Office_48x48.png` (768×2544, 848 tiles) →
`office.sheet.office`. A real map surviving that round trip proves the format is
expressive enough and the addressing is correct.

**Result: 18/18 maps pass.** Importing also turned out to be worth having for its
own sake — it makes 18 hand-built maps into reference data and regression fixtures,
and it is the closest thing available to ground truth for what a good room looks like.

### Open question: atlases

Composite singles cannot be referenced by GID against LimeZu's own sheets. The clean
fix is for the exporter to **pack a project-specific atlas** containing exactly the
assets a map uses, and emit it beside the Tiled JSON. Then GIDs index an image we
control, every asset is representable, and sub-tile alignment stops mattering.

The trade is a generated image per project instead of referencing the stock sheets.
Existing WaterCooler maps still import either way. Worth deciding before Phase 5,
since generation will produce composites constantly.

---

## Phase 3 — Groupings (current focus)

The pack's own folders group by theme, which is a shelf layout, not a way to find
things. Three signals feed one facet schema:

| Signal | Covers | Status |
|---|---|---|
| pack filenames | ~6,900 exterior/office singles | done |
| measured pixels | all 12,799 | done |
| vision labelling | ~6,200 unnamed interior/office singles | not started |

Built so far: `tools/facets.py` (name + pixel facets, shadow-diff placement),
`tools/vocab.py` (445 canonical concepts, 81% into 25 classes), and facet filters in
`tools/query.py`.

Still to do here: classify the remaining concept tail, split the `mounted` bucket
(it conflates wall-mounted / on-surface / floor-overlay), and group variant families
so generated rooms use matching furniture rather than a random mix.

## Phase 3b — Make it promptable

Half the library is unaddressable by name. 6,264 exterior singles are named
(`Bench_1`, `ATM_1`); all 6,200 interior and office singles are numbered only. You
cannot ask for "a fridge" today.

1. **Label the unnamed singles** with a vision pass over paged contact sheets
   (`tools/contact_sheet.py` already renders them). ~6,200 items at 48–64 per sheet
   is roughly 100–130 sheets — a one-time cost, done in batches.
2. **Prioritise by theme.** Start with `office`, `kitchen`, `conference_hall`,
   `living_room`. Prove the loop on one theme before committing to all 26.
3. **Labels live in a sidecar file**, never in `catalog.json` — the catalog is
   regenerated from disk, labels are hand-verified and must survive a rebuild.
4. **Aliases and functional tags**, so "fridge", "refrigerator" and "icebox" all
   resolve, alongside `seating`, `storage`, `wall-mounted`, `blocks-movement`.

**Acceptance test:** `query.py fridge` returns actual fridges from the interior packs.

---

## Phase 4 — Placement rules

Raw asset ids do not make a coherent room. This is the layer that stops generated
maps looking like a junk drawer.

1. **Autotiling.** Terrain families are wang sets — variants 1–20 are edges and
   corners, only the last one or two tile seamlessly. Build a neighbour-mask →
   variant map per family. (`tools/find_fill.py` already finds the fills.)
2. **Rooms as a system.** Walls, floors, doors and baseboards from the Room_Builder
   sheets, composed as rooms rather than placed tile by tile.
3. **Placement grammar.** Default layer per asset, what can sit on what, clearance
   in front (a fridge cannot open into a wall), wall-mounted vs floor-standing, and
   collision footprints.

**Acceptance test:** a generated room is walkable end to end, with no overlapping
furniture and no blocked doors.

---

## Phase 5 — Generation

1. **Layout pass:** prompt → zones and rooms (walls, floors, doors, circulation).
2. **Furnish pass:** each zone → furniture and props, under Phase 4 rules.
3. **Region edits:** "put a kitchen in the top-left corner" rewrites only the
   selected rectangle and leaves the rest untouched.
4. **Retrieval, not recall.** The model picks from catalog search results rather
   than inventing ids. Keep the renderer's loud failure on unresolved ids — it
   caught a bad id within minutes on the first demo.

---

## Phase 6 — The web app

Standalone Next.js/React app, reusing WaterCooler's stack and patterns.

- Asset browser: search, filter by pack/theme/footprint, visual grid
- Canvas editor: paint terrain, stamp objects, per-layer visibility, undo
- Prompt box for whole-map drafts and region edits
- Live preview rendering the neutral format directly
- Export via the Phase 2 exporters

---

## Phase 7 — More exporters

Phaser and Godot as needed. The point of Phase 2's interface is that these are
additive and touch nothing in the core.

---

## Order of work

Phases 1 and 2 are one push — the format is unproven until a real map round-trips
through it, so treat the exporter as part of building the format, not as a follow-up.
Phase 3 can run in parallel once the contact-sheet loop is proven on one theme, since
labelling is batch work that blocks nothing.

## Standing constraint

The packs are licensed and **must not be redistributed**. Everything ships as maps
(id lists), never pixels. `images/` stays gitignored. Sheets copied into a private
deployment are fine; publishing them anywhere is not.
