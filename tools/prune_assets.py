#!/usr/bin/env python3
"""
Collect just the artwork the editor actually fetches into web_assets/.

images/ is 677 MB across 93,001 files -- the whole extracted tree, most of which no
index ever references. The editor only ever loads the sheets, singles and character
sheets named in editor/*.json: 13,044 files, 95 MB. That subset is what ships in the
deployed image, so a deploy carries a seventh of the tree.

Paths are kept relative to images/, so the image can copy web_assets/ straight to
images/ and every reference in the JSON indexes still resolves.

    python3 tools/prune_assets.py                 # everything the editor references
    python3 tools/prune_assets.py --sizes 32      # only the 32px sheets
"""
import argparse, json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "images")
DST = os.path.join(ROOT, "web_assets")


def referenced(sizes=None):
    """Every image path named by an editor index, as paths under images/."""
    def load(name):
        return json.load(open(os.path.join(ROOT, "editor", name)))

    want = set()
    sheets = load("sheets.json")
    for size, lst in sheets["sizes"].items():
        if sizes and size not in sizes:
            continue
        for s in lst:
            want.add(s["image"])

    singles = load("singles.json")
    for recs in singles["cats"].values():
        for r in recs:
            want.add(r["image"])

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "image" and isinstance(v, str):
                    want.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(load("characters.json"))

    out = set()
    for p in want:
        if not p.startswith("images/"):
            print(f"  ! not under images/: {p}", file=sys.stderr)
            continue
        out.add(p[len("images/"):])
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", help="tile sizes to keep (default: all)")
    ap.add_argument("--clean", action="store_true", help="remove web_assets/ first")
    a = ap.parse_args()

    if a.clean and os.path.isdir(DST):
        shutil.rmtree(DST)

    files = referenced(set(a.sizes) if a.sizes else None)
    copied = skipped = missing = 0
    total = 0
    for rel in files:
        src, dst = os.path.join(SRC, rel), os.path.join(DST, rel)
        if not os.path.exists(src):
            print(f"  ! missing: {rel}", file=sys.stderr)
            missing += 1
            continue
        total += os.path.getsize(src)
        # skip files already copied and unchanged, so a rebuild is quick
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
            skipped += 1
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    print(f"  {len(files)} referenced, {total/1e6:.1f} MB "
          f"({copied} copied, {skipped} already current, {missing} missing)")
    if missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
