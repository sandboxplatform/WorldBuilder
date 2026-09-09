#!/usr/bin/env python3
"""
Query the asset catalog.

    python tools/query.py bench                  # free-text search
    python tools/query.py --pack ext --kind single bench
    python tools/query.py --category kitchen --limit 5
    python tools/query.py --id ext.single.city_props.bench_1
    python tools/query.py --categories            # list every category
    python tools/query.py --tiles 2x3 desk        # filter by tile footprint
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "catalog", "catalog.json")


def load():
    with open(CATALOG) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("terms", nargs="*", help="words that must all appear in the id")
    ap.add_argument("--pack", help="int | ext | office | char | ui")
    ap.add_argument("--kind", help="single | sheet | animated | layer | design | ...")
    ap.add_argument("--category")
    ap.add_argument("--id", help="exact id lookup, prints full record")
    ap.add_argument("--tiles", help="tile footprint, e.g. 2x3")
    ap.add_argument("--size", default="32", help="pixel size variant to report (16/32/48)")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--count", action="store_true", help="print only the match count")
    ap.add_argument("--categories", action="store_true", help="list categories and asset counts")
    ap.add_argument("--json", action="store_true", help="emit matches as JSON")
    # facet filters (need catalog/facets.json -- build with tools/facets.py)
    ap.add_argument("--concept", help="parsed concept, e.g. bench, trash_can")
    ap.add_argument("--head", help="head noun of the concept, e.g. can, sign")
    ap.add_argument("--placement",
                    choices=["terrain", "floor", "mounted", "wall", "on_surface",
                             "floor_overlay"])
    ap.add_argument("--labelled", action="store_true",
                    help="only assets that have been through the vision pass")
    ap.add_argument("--colour")
    ap.add_argument("--material")
    ap.add_argument("--finish", choices=["smooth", "grained", "woven"],
                    help="measured surface finish, for style-matching furniture")
    ap.add_argument("--state")
    ap.add_argument("--modular", action="store_true", help="only modular pieces")
    ap.add_argument("--tileable", action="store_true", help="only seamless terrain")
    ap.add_argument("--concepts", action="store_true",
                    help="list the concept vocabulary and counts")
    # argparse mis-binds a trailing nargs="*" positional when it follows an
    # option, so split bare search terms out of argv first.
    VALUED = {"--pack", "--kind", "--category", "--id", "--tiles", "--size", "--limit",
              "--concept", "--head", "--placement", "--colour", "--material",
              "--state", "--finish"}
    argv, terms, i = [], [], 1
    while i < len(sys.argv):
        tok = sys.argv[i]
        if tok.startswith("-"):
            argv.append(tok)
            if tok.split("=")[0] in VALUED and "=" not in tok and i + 1 < len(sys.argv):
                i += 1
                argv.append(sys.argv[i])
        else:
            terms.append(tok)
        i += 1
    a = ap.parse_args(argv)
    a.terms = terms

    cat = load()
    assets = cat["assets"]

    facet_path = os.path.join(ROOT, "catalog", "facets.json")
    facets = {}
    wants_facets = any([a.concept, a.head, a.placement, a.colour, a.material,
                        a.state, a.modular, a.tileable, a.concepts, a.labelled,
                        a.finish])
    if wants_facets:
        if not os.path.exists(facet_path):
            sys.exit("facet filters need catalog/facets.json -- run tools/facets.py")
        facets = json.load(open(facet_path))["assets"]
        # Vision labels override the pixel/name guesses they were made to correct.
        label_path = os.path.join(ROOT, "catalog", "labels.json")
        if os.path.exists(label_path):
            for aid, lab in json.load(open(label_path))["labels"].items():
                rec = facets.setdefault(aid, {"name_facets": {}, "pixel_facets": {}})
                nf = rec["name_facets"]
                for key in ("concept", "colour", "material", "state", "part"):
                    if key in lab:
                        nf[key] = lab[key]
                if "concept" in lab:
                    nf.setdefault("head", lab["concept"].split("_")[-1])
                if "placement" in lab:
                    rec["placement"] = lab["placement"]
                rec["labelled"] = True

    if a.concepts:
        import collections
        c = collections.Counter()
        for r in facets.values():
            con = r["name_facets"].get("concept")
            if con:
                c[con] += 1
        print(f"{len(c)} concepts across {sum(c.values())} named assets")
        for con, n in c.most_common(a.limit):
            print(f"  {n:5d}  {con}")
        return

    if a.id:
        hit = [e for e in assets if e["id"] == a.id]
        if not hit:
            sys.exit(f"no asset with id {a.id}")
        print(json.dumps(hit[0], indent=2))
        return

    if a.categories:
        import collections
        c = collections.Counter((e["pack"], e["kind"], e["category"]) for e in assets)
        for (p, k, cg), n in sorted(c.items()):
            print(f"{n:6d}  {p}.{k}.{cg}")
        return

    res = assets
    if a.pack:
        res = [e for e in res if e["pack"] == a.pack]
    if a.kind:
        res = [e for e in res if e["kind"] == a.kind]
    if a.category:
        res = [e for e in res if a.category in e["category"]]
    if a.tiles:
        w, h = (float(x) for x in a.tiles.lower().split("x"))
        res = [e for e in res if e["tiles"] == [w, h]]
    def facet_ok(e):
        r = facets.get(e["id"])
        if r is None:
            return False
        nf, pf = r["name_facets"], r["pixel_facets"]
        if a.concept and nf.get("concept") != a.concept:
            return False
        if a.head and nf.get("head") != a.head:
            return False
        if a.placement and r.get("placement") != a.placement:
            return False
        if a.colour and a.colour not in nf.get("colour", []):
            return False
        if a.material and a.material not in nf.get("material", []):
            return False
        if a.state and a.state not in nf.get("state", []):
            return False
        if a.modular and not nf.get("modular"):
            return False
        if a.finish and pf.get("finish") != a.finish:
            return False
        if a.tileable and not pf.get("tileable"):
            return False
        if a.labelled and not r.get("labelled"):
            return False
        return True

    if wants_facets:
        res = [e for e in res if facet_ok(e)]

    for t in a.terms:
        t = t.lower()
        res = [e for e in res if t in e["id"]]

    if a.count:
        print(len(res))
        return
    if a.json:
        print(json.dumps(res[: a.limit], indent=2))
        return

    print(f"{len(res)} match(es)" + (f", showing {a.limit}" if len(res) > a.limit else ""))
    for e in res[: a.limit]:
        px = e["px"].get(a.size) or next(iter(e["px"].values()), [0, 0])
        tiles = e["tiles"] or [0, 0]
        flag = "" if e.get("grid_aligned") else "  (off-grid)"
        print(f"  {e['id']:<58s} {px[0]:>4}x{px[1]:<4} px  {tiles[0]:g}x{tiles[1]:g} tiles"
              f"  sizes={','.join(e['sizes'])}{flag}")


if __name__ == "__main__":
    main()
