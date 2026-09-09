#!/usr/bin/env python3
"""
Build the standalone viewer bundle: atlas, map and character sheet.

Everything the viewer needs is generated into viewer/assets/ so the viewer runs
against this project alone -- no other repo, and no dependency on the original
packs at run time.

    python tools/build_viewer.py maps/office_floor.json
"""
import argparse, json, os, subprocess, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "viewer", "assets")

# From catalog/char_animations.json: 32x64 frames, 56 columns, 20 rows.
# Row 1 is idle, row 2 is walk; each is four direction blocks of six frames.
#
# Block order is right, up, left, down -- verified, not assumed: block 2 is an exact
# horizontal mirror of block 0 (0.0% pixel difference), and block 0's face points
# right. Getting this backwards makes the character moonwalk sideways.
DIR_BLOCKS = {"right": 0, "up": 1, "left": 2, "down": 3}
CHAR_ROWS = {"idle": 1, "walk": 2}
FRAMES_PER_DIR = 6
FW, FH = 32, 64


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mapfile")
    ap.add_argument("--character",
                    default="char.premade.0_premade_characters.premade_character_01")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    # 1. atlas + tiled map
    subprocess.run([sys.executable, os.path.join(HERE, "export_atlas.py"),
                    a.mapfile, OUT, "--name", "scene"], check=True)

    # 2. collision and spawn travel with the neutral map, not the Tiled export
    m = json.load(open(a.mapfile))
    json.dump({"size": m["size"], "tile": m["tile"],
               "collisions": m["collisions"], "spawns": m["spawns"]},
              open(os.path.join(OUT, "scene_meta.json"), "w"))

    # 3. character: just the idle and walk rows, cropped to the frames in use
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    index = {e["id"]: e for e in cat["assets"]}
    sheet = Image.open(os.path.join(base, index[a.character]["paths"]["32"])).convert("RGBA")
    ncols = FRAMES_PER_DIR * 4
    out = Image.new("RGBA", (ncols * FW, len(CHAR_ROWS) * FH), (0, 0, 0, 0))
    for i, (_name, row) in enumerate(sorted(CHAR_ROWS.items())):
        out.alpha_composite(sheet.crop((0, row * FH, ncols * FW, row * FH + FH)),
                            (0, i * FH))
    out.save(os.path.join(OUT, "character.png"))
    json.dump({"frame": [FW, FH], "framesPerDir": FRAMES_PER_DIR,
               "rows": {n: i for i, (n, _r) in enumerate(sorted(CHAR_ROWS.items()))},
               "dirBlocks": DIR_BLOCKS},
              open(os.path.join(OUT, "character.json"), "w"))

    print(f"  character.png  {out.width}x{out.height}")
    print(f"  scene_meta.json  {len(m['collisions'])} collision runs")
    print(f"\nviewer bundle ready in {OUT}")


if __name__ == "__main__":
    main()
