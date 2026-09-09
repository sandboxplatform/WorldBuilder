#!/usr/bin/env python3
"""
Index every standalone sprite the editor can paint.

Sheets do not cover everything: ~2,141 pre-cut singles are pre-composed variants that
appear nowhere as a contiguous block in any sheet, and the animated frame strips are
separate files too. Those can only be placed as whole sprites, so the editor browses
them from here.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "editor", "singles.json")
SIZE = "32"
KINDS = {"single", "animated", "vehicle", "design", "autotile_single"}

PACK_NAME = {"ext": "Exteriors", "int": "Interiors",
             "office": "Modern Office", "ui": "User Interface"}
KIND_NAME = {"animated": "animated", "vehicle": "vehicles",
             "design": "room designs", "autotile_single": "autotile pieces"}


def main():
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    labels = {}
    lp = os.path.join(ROOT, "catalog", "labels.json")
    if os.path.exists(lp):
        labels = json.load(open(lp))["labels"]
    # Collision defaults come from the labelling pass: a thing that stands on the
    # floor blocks over the patch where it MEETS the floor (measured from the
    # shadow), while rugs, wall art and anything sitting on a desk do not block at
    # all. The editor applies these as defaults and lets you override any tile.
    NON_BLOCKING = {"floor_overlay", "on_surface", "wall", "mounted"}
    shadows = {}
    bboxes = {}
    fp = os.path.join(ROOT, "catalog", "facets.json")
    if os.path.exists(fp):
        for aid, rec in json.load(open(fp))["assets"].items():
            pf = rec.get("pixel_facets", {})
            if pf.get("bbox"):
                bboxes[aid] = pf["bbox"]
            if pf.get("shadow_bbox"):
                shadows[aid] = pf["shadow_bbox"]

    # animated strips are many frames wide; the placeable object is ONE frame
    anims = {}
    ap = os.path.join(ROOT, "editor", "animations.json")
    if os.path.exists(ap):
        anims = json.load(open(ap))

    cats, by_id, cat_group = {}, {}, {}
    T = int(SIZE)
    for e in cat["assets"]:
        if e["kind"] not in KINDS or SIZE not in e["paths"]:
            continue
        w, h = e["px"][SIZE]
        an = anims.get(e["id"])
        if an:
            w, h = an["frame"]            # one frame, not the whole strip
        elif w > T * 24 or h > T * 24:
            continue                      # skip oversized strips we cannot split
        concept = labels.get(e["id"], {}).get("concept")
        bb = bboxes.get(e["id"])
        rec = {
            "id": e["id"],
            "image": f"{cat['root']}/{e['paths'][SIZE]}",
            "tiles": ([max(1, -(-bb[2] // T)), max(1, -(-bb[3] // T))] if bb
                      else [max(1, -(-w // T)), max(1, -(-h // T))]),
            "px": [w, h],
            "bbox": bboxes.get(e["id"], [0, 0, w, h]),
            "name": concept or e["name"],
        }
        placement = labels.get(e["id"], {}).get("placement")
        rec["blocks"] = placement not in NON_BLOCKING
        if rec["blocks"]:
            bb = bboxes.get(e["id"])
            sb = shadows.get(e["id"])
            if sb and bb:
                # shadow bounds are absolute in the sprite; make them relative to
                # the content, which is what the editor positions by
                rec["cbox"] = [sb[0] - bb[0], sb[1] - bb[1], sb[2], sb[3]]
            elif bb:
                base = max(8, bb[3] // 3)      # no shadow twin: use the lower third
                rec["cbox"] = [0, bb[3] - base, bb[2], base]
        if placement:
            rec["placement"] = placement
        if an:
            rec["anim"] = {"frames": an["frames"], "frame": an["frame"]}
            rec["bbox"] = [0, 0, w, h]
            rec["tiles"] = [max(1, -(-w // T)), max(1, -(-h // T))]
        key = f"{e['pack']}.{e['kind']}.{e['category']}"
        cats.setdefault(key, []).append(rec)
        group = PACK_NAME.get(e["pack"], e["pack"])
        if e["kind"] in KIND_NAME:
            group += " · " + KIND_NAME[e["kind"]]
        cat_group[key] = group
        by_id[e["id"]] = rec

    for k in cats:
        cats[k].sort(key=lambda r: r["name"])
    json.dump({"cats": cats, "groups": cat_group, "byId": by_id},
              open(OUT, "w"), separators=(",", ":"))
    print(f"{len(by_id):,} sprites in {len(cats)} categories -> {OUT} "
          f"({os.path.getsize(OUT)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
