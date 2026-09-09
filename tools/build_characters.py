#!/usr/bin/env python3
"""
Index the character sheets the editor can drop into a world.

Frame geometry and direction order come from catalog/char_animations.json, which was
measured off the sheets rather than assumed -- blocks run right, up, left, down.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "editor", "characters.json")
SIZE = "32"


def main():
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    anim = json.load(open(os.path.join(ROOT, "catalog", "char_animations.json")))
    order = anim.get("direction_order", ["right", "up", "left", "down"])
    dir_blocks = {name: i for i, name in enumerate(order)}
    rows = {r["name"]: r["row"] for r in anim["rows"]}

    out = []
    for e in cat["assets"]:
        if e["pack"] != "char" or e["kind"] not in ("premade", "layer"):
            continue
        if e["kind"] == "layer" and e["category"] not in ("bodies",):
            continue                       # bodies stand alone; other layers overlay
        if SIZE not in e["paths"]:
            continue
        out.append({
            "id": e["id"],
            "label": ("premade · " if e["kind"] == "premade" else "body · ") + e["name"],
            "image": f"{cat['root']}/{e['paths'][SIZE]}",
            "frame": anim["frame_px"],
            "framesPerDir": 6,
            "rows": {"idle": rows.get("idle", 1), "walk": rows.get("walk", 2)},
            "dirBlocks": dir_blocks,
        })
    # premade characters are fully dressed; bodies are a bare base layer, so the
    # dressed ones come first and become the default
    out.sort(key=lambda c: (c["label"].startswith("body"), c["label"]))
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{len(out)} characters -> {OUT}")


if __name__ == "__main__":
    main()
