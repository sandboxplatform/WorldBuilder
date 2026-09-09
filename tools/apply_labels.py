#!/usr/bin/env python3
"""
Apply a vision-pass label set to a theme, writing catalog/labels.json.

Labels live in their own sidecar, never inside catalog.json: the catalog is
regenerated from disk, while labels are hand-verified and must survive a rebuild.

The label file is written as page/cell ranges against a labelling manifest, so it
stays short enough to read and diff. `shape` rules pick a concept from the sprite's
aspect ratio, which is how the modular kitchen units are separated into tall
cupboards, square cabinets and wide worktops.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "catalog", "labels.json")


def expand(spec, manifest, catalog_index, size):
    """Turn {"1:1-19": {...}} into {asset_id: {...}}."""
    out = {}
    for key, label in spec.items():
        page, cells = key.split(":")
        lo, _, hi = cells.partition("-")
        for n in range(int(lo), int(hi or lo) + 1):
            aid = manifest.get(f"{page}:{n}")
            if aid is None:
                continue
            rec = dict(label)
            shape = rec.pop("shape", None)
            if shape:
                w, h = catalog_index[aid]["px"][size]
                rec["concept"] = shape["tall"] if h > w else (
                    shape["wide"] if w > h else shape["square"])
            out[aid] = rec
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: apply_labels.py <labelspec.json> <manifest.json>")
    spec = json.load(open(sys.argv[1]))
    man = json.load(open(sys.argv[2]))
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    index = {e["id"]: e for e in cat["assets"]}
    size = man["size"]

    new = expand(spec["labels"], man["cells"], index, size)

    existing = {}
    if os.path.exists(OUT):
        existing = json.load(open(OUT)).get("labels", {})
    existing.update(new)
    json.dump({"note": "Vision-pass labels. Sidecar to catalog.json so they survive "
                       "a catalog rebuild.",
               "labels": existing}, open(OUT, "w"), indent=1, sort_keys=True)

    import collections
    conc = collections.Counter(v.get("concept") for v in new.values())
    place = collections.Counter(v.get("placement") for v in new.values())
    conf = collections.Counter(v.get("confidence", "high") for v in new.values())
    print(f"labelled {len(new)} assets in this pass; {len(existing)} total -> {OUT}")
    print(f"  placements: {dict(place)}")
    print(f"  confidence: {dict(conf)}")
    print(f"  {len(conc)} distinct concepts; top: "
          f"{', '.join(f'{c}({n})' for c, n in conc.most_common(10))}")


if __name__ == "__main__":
    main()
