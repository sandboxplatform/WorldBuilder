# Standalone viewer

Walk around a generated scene. Runs entirely from this project — no other repo, and
no dependency on the original packs at run time (everything it needs is baked into
`viewer/assets/`).

## Run it

```bash
python3 tools/serve_viewer.py 8823
```

Then open http://127.0.0.1:8823/

`WASD` or arrows to move · `shift` to run · `g` to show the collision grid ·
`-` / `=` to zoom.

## Rebuild the bundle after changing a scene

```bash
python3 scenes/office_floor.py          # regenerate the map
python3 tools/build_viewer.py maps/office_floor.json
```

That writes four files into `viewer/assets/`:

| File | What it is |
|---|---|
| `scene.json` | Tiled map, tile layers only |
| `scene_atlas.png` | every tile the scene uses, deduplicated (~64 KB) |
| `scene_meta.json` | collision runs and the spawn point |
| `character.png` | idle and walk rows, four directions, six frames each |

The whole bundle is about 120 KB.

## Notes

- **Assets stay local.** The packs are licensed and must not be redistributed, so
  this is a local server, never a published page. `viewer/assets/` is gitignored.
- The character frame layout comes from `catalog/char_animations.json`, measured off
  the sheets rather than assumed. Direction blocks are **right, up, left, down** — verified by mirror test, and read
from `character.json` rather than hardcoded in the viewer.
- **Collision is not the sprite footprint.** Layout reserves whole sprite rectangles
  so furniture does not overlap, but what blocks *you* is where an object meets the
  floor — measured from the shadow-diff, a median 44% of the sprite area. Rugs,
  wall-hung art and anything sitting on a desk do not block at all.
- `tools/validate_scene.py` flood-fills from the spawn and reports any pocket a
  player could never reach.
- The character's collision box is its feet (14x10 px), not the whole sprite, so you
  can tuck into desk alcoves the way you'd expect.
- The loop is driven by `requestAnimationFrame` *and* a timer: some embedded browser
  views throttle rAF to roughly one frame a second, which made the viewer look frozen
  until the fallback was added.
