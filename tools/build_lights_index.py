#!/usr/bin/env python3
"""
Write editor/lights.json: what the editor needs to light a map the same way the
exporter does.

The derivation in tools/lights.py reads facets, labels, vocab and sheet_xy -- 15 MB
the editor has no business loading to draw a glow. Only the sprites that actually
emit light matter, and there are few of them, so this bakes just those: the kind
table, an asset -> kind map, and the sheet cells that resolve to a light.

Keeping one source of truth matters more than the file size. If the editor guessed
at lighting separately, what you author and what you export would drift.

    python3 tools/build_lights_index.py
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import lights as L  # noqa: E402


def main():
    facets = json.load(open(os.path.join(ROOT, "catalog", "facets.json")))["assets"]
    classes, labels, cells = L._vocab_classes(), L._labels(), L._sheet_cells()

    by_id = {}
    for aid, fa in facets.items():
        nf = fa.get("name_facets", {})
        lab = labels.get(aid) or {}
        kind, spec = L._kind_for([lab.get("concept"), nf.get("concept"), nf.get("head")],
                                 classes)
        if spec:
            by_id[aid] = kind
    # a label can exist for an asset facets never measured
    for aid, lab in labels.items():
        if aid in by_id:
            continue
        kind, spec = L._kind_for([lab.get("concept")], classes)
        if spec:
            by_id[aid] = kind

    # only the sheet cells that land on something that glows
    sheet_cells = {}
    for (sheet, col, row), sid in cells.items():
        k = by_id.get(sid)
        if k:
            sheet_cells[f"{sheet}#{col},{row}"] = k

    kinds = dict(L.LIGHT_KINDS)
    kinds["_default"] = L.LIT_DEFAULT

    out = {"kinds": kinds, "byId": by_id, "sheetCells": sheet_cells,
           "ambient": L.AMBIENT}
    path = os.path.join(ROOT, "editor", "lights.json")
    json.dump(out, open(path, "w"))
    kb = os.path.getsize(path) / 1024
    print(f"  {len(by_id)} lit assets, {len(sheet_cells)} lit sheet cells, "
          f"{len(kinds) - 1} kinds -> editor/lights.json ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
