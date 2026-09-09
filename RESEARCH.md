# How LimeZu built these packs, and what that means for us

Notes from reading the packs' own bundled documentation, measuring the art, and
checking the author's public posts. Written against the specific builds we hold.

## Versions we actually have

Everything below was verified against **these** builds, not against whatever the
itch.io pages currently describe.

| Pack | Build (from archive timestamps) |
|---|---|
| Modern Office — Revamped **v1.2** | Sept 2021, a handful of files touched 2024 |
| Modern UI | May 2023 |
| Modern Interiors | Dec 2024 |
| Modern Exteriors | Dec 2025 |

Four separate builds spanning four years. Two consequences:

1. **Prefer the docs bundled inside each pack.** They ship with the version, so they
   cannot drift from it. The web devlogs and community guides can and do describe
   other versions.
2. **Where a public post and the pixels disagree, the pixels win.** The author's
   "How to Walls" devlog refers to a tutorial image that is *not present* in our
   Interiors download, so we cannot confirm it describes this build. The Room Builder
   structure recorded below was measured from our own files instead.

There is also drift *within* a pack. Every Interiors file carries the same export
timestamp, so metadata suggests one consistent build — but the pixels disagree: the
`classroom_and_library` singles match nothing in their own theme sheet, and do match
the complete Interiors sheet. Timestamps record when files were exported, not when
the art was revised.

## What ships as documentation inside the packs

- `2_Characters/Character_Generator/CHARACTER_GENERATOR.txt` — the paperdoll layer
  order, stated by the author
- `2_Characters/Character_Generator/Spritesheet_animations_GUIDE.png` — a labelled
  map of every animation row
- `2_Characters/Character_Generator/HOW_TO_CHARACTER_GENERATOR.png`
- `5_Modern_Office_RPG_MAKER_MV/IMPORT MANUAL.txt` — RPG Maker MV/MZ tileset slots
- `LICENSE.txt` per pack, and `THIRD-PARTY TOOLS.txt` pointing at 0a3r's generator

## Characters are a paperdoll, in a fixed order

The author states the compositing order explicitly:

> body → eyes → outfit → hairstyle → accessory

with the noted exception that `Outfit_kid_6_pajama_frog` and `_7_pajama_tiger` need
no hairstyle. Every layer sheet is the same size at a given tile size, so layers
composite with no offset maths.

One trap: **body sheets are 1854px wide where every other layer is 1792px** (at 32px).
The extra 62px strip is not part of the 56-column frame grid, and naive column
counting over a body sheet produces wrong frame counts.

## The character animation grid (measured, not guessed)

Frames are **32×64** at the 32px size, laid out **56 columns × 20 rows**, row pitch
64px. Row order and names come from the pack's own guide; frame extents were measured
off the sheets and agree with it. Written to `catalog/char_animations.json`.

| Row | Animation | Frames | | Row | Animation | Frames |
|---:|---|---|---|---:|---|---|
| 0 | base_4dir | 4 × 1 | | 10 | gift | 46 * |
| 1 | idle | 4 × 6 | | 11 | lift | 4 × 14 |
| 2 | walk | 4 × 6 | | 12 | throw | 4 × 14 |
| 3 | sleep | 13 * | | 13 | hit | 4 × 6 |
| 4 | sit_a | 4 × 3 | | 14 | punch | 4 × 6 |
| 5 | sit_b | 4 × 3 | | 15 | stab | 4 × 12 |
| 6 | phone | 14 * | | 16 | grab_gun | 4 × 4 |
| 7 | read | 26 * | | 17 | gun_idle | 4 × 6 |
| 8 | push_cart | 4 × 12 | | 18 | shoot | 13 * |
| 9 | pick_up | 4 × 12 | | 19 | hurt | 13 * |

Each direction block is six frames, and the block order is **right, up, left, down**.
That was verified rather than assumed: block 2 is an exact horizontal mirror of block 0
(0.0% pixel difference across the walk frames), and block 0's face points right. I had
left and right swapped on the first pass and the character moonwalked sideways.

Rows marked `*` are not four equal direction blocks. These are exactly the rows the
author annotates specially in the guide: `sleep` carries bed and sleeping-bag props,
`gift` appends two box frames, `shoot` appends a bullet, and `phone` and `read` are
labelled as frame-range loops rather than directional sets. Treat those six as
special cases rather than forcing a 4-direction split.

## Rooms are built from parts, not painted freehand

The Interiors pack decomposes its Room Builder into named sub-files, which is the
author's own structural documentation:

| Part | Size (32px) | Role |
|---|---|---|
| `walls` | 32×40 tiles | wall styles, each a wang block |
| `3d_walls` | 24×59 | walls seen with depth |
| `floors` | 15×40 tiles | floor materials in vertical strips |
| `baseboards` | 6×6 | skirting joining wall to floor |
| `floor_shadows` | 16×5 | shadow walls cast onto the floor |
| `floor_connectors` | 7×36 | transitions between floor materials |
| `floor_paths` | 42×12 | paths laid over a floor |
| `borders` | 45×10 | edging |
| `arched_entryways` | 10×32.5 † | door openings |

† `arched_entryways` is 320×1040px — not a whole number of 32px tiles. Every other
Room Builder part is tile-exact, so this one needs a half-tile offset when sliced.

So a room is assembled as: **floor material → floor shadow under the walls → wall
style → baseboard → entryway**, with connectors and paths for floor transitions.
That ordering is the shape our room generator should take, and it explains why
`walls` and `floors` are laid out as repeating blocks rather than as objects.

Wall heights vary between 2 and 4 tiles by design. The author's stated reasoning is
partly practical (room for tall furniture) and partly tonal — taller walls read as
less domestic.

## The sheets are banded by family, and objects are multi-tile assemblies

Two things I got wrong by working from isolated single sprites, both fixed by reading
the sheet itself.

**Sheet row is a strong identity signal.** The Modern Office sheet is laid out in
horizontal bands: rows 0-7 are cubicle partitions, 8-11 chairs, 12-16 wall art and
desk kit, 17-24 sofas, cabinets, printers and vending, 28-51 desk surfaces. I had
labelled all the big tan panels "desk", which lumped 69 partition panels in with the
desks. Cross-checking labels against recovered sheet positions separated them in one
pass.

**Multi-tile objects have to be stamped, not assembled from singles.** A cubicle
partition is a panel over a footed base rail (3x3 at sheet 1,0). A desk is a surface
over a base rail (3x2 at 7,28). An L-return is 3x3 at 0,34. The pre-cut singles chop
these into 1x1 fragments that cannot be reassembled by guesswork -- stacking them
arbitrarily produces nonsense. `Scene.stamp()` places a block of sheet tiles keeping
their relative positions, which preserves the composition the artist drew.

**And a desk is never bare.** In the pack's own `6_Office_Designs` GIFs every desk
carries two to four items -- monitor, keyboard, papers, mug, lamp -- with a chair
tucked in front and a partition behind. A workstation is that whole assembly. Placing
a desk sprite alone and calling the room furnished is what made the first generated
office look empty.

## Why the shadow variants exist, and what we get from them

Interiors and Office ship every asset three times: normal, `Shadowless`, and
`Black_Shadow`. That is offered as an art choice, but it is also a free, objective
signal we exploit: **diffing an asset against its shadowless twin isolates the drop
shadow**, which tells us the object stands on the floor, and the shadow's bounding
box is roughly where it meets the ground — a better collision footprint than the
sprite bounds. Exteriors ship no shadowless variants, but exterior assets *are*
semantically named, so the two halves of the library are covered by different signals.

## Sources

- Bundled pack documentation (authoritative for these builds)
- [Modern Interiors](https://limezu.itch.io/moderninteriors) ·
  [Modern Exteriors](https://limezu.itch.io/modernexteriors) ·
  [Modern Office](https://limezu.itch.io/modernoffice)
- ["How to Walls" devlog](https://limezu.itch.io/moderninteriors/devlog/209960/tutorial-how-to-walls)
  — version unconfirmed against our build; its tutorial image is not in our download
