#!/usr/bin/env python3
"""
Index every paintable sheet for the editor.

The editor paints tile refs (`tile:<sheet-id>#col,row`), so it needs to know which
sheets exist, where their images are, and how many tiles each holds. Images are
served straight from images/extracted -- nothing is copied, so the 670 MB of source
art stays in one place and stays local.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "editor", "sheets.json")

# sheet-like kinds the editor can paint from
# Sheets are the big multi-object images you paint tiles from. Animated strips are
# single objects, not sheets -- they belong in the singles browser, which handles
# their frames properly. Listing all 769 of them here buried the ~69 real sheets and
# gave them all the same name, since they share one category.
KINDS = {"sheet", "roombuilder", "palette", "autotile"}

# Friendly grouping for the editor's dropdown -- a flat list of 69 sheets is a lot
# to scan, and the pack a sheet comes from is the way people actually look for one.
PACK_NAME = {"ext": "Exteriors", "int": "Interiors",
             "office": "Modern Office", "ui": "User Interface", "char": "Characters"}
KIND_NAME = {"roombuilder": "room builder", "autotile": "autotiles",
             "palette": "palettes"}


def main():
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    root = cat["root"]
    groups = {}
    for e in cat["assets"]:
        if e["kind"] not in KINDS:
            continue
        for size, path in e["paths"].items():
            if size not in e["px"] or not size.isdigit():
                continue
            w, h = e["px"][size]
            t = int(size)
            if w < t or h < t:
                continue
            # Label from whatever actually distinguishes this sheet. Category alone
            # is not enough: several packs reuse one category across sheets.
            parts = [e["pack"], e["category"].replace("_", " ")]
            if e["name"] not in ("sheet", "complete", e["category"]):
                parts.append(e["name"].replace("_", " "))
            label = " · ".join(parts)
            if e["kind"] != "sheet":
                label += f" ({e['kind']})"
            group = PACK_NAME.get(e["pack"], e["pack"])
            if e["kind"] in KIND_NAME:
                group += " · " + KIND_NAME[e["kind"]]
            groups.setdefault(size, []).append({
                "id": e["id"],
                "group": group,
                "label": label,
                "pack": e["pack"], "kind": e["kind"],
                "image": f"{root}/{path}",
                "cols": w // t, "rows": h // t, "px": [w, h],
            })
    for size in groups:
        groups[size].sort(key=lambda s: (s["group"], s["label"]))
        # last resort: never show two entries with the same name
        seen = {}
        for sh in groups[size]:
            if sh["label"] in seen:
                seen[sh["label"]] += 1
                sh["label"] += f" #{seen[sh['label']]}"
            else:
                seen[sh["label"]] = 1

    json.dump({"root": root, "sizes": {k: v for k, v in sorted(groups.items())}},
              open(OUT, "w"), indent=1)
    for size, v in sorted(groups.items()):
        tot = sum(s["cols"] * s["rows"] for s in v)
        uniq = len({s["label"] for s in v})
        print(f"  {size}px: {len(v)} sheets ({uniq} distinct names), "
              f"{tot:,} paintable tiles")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
