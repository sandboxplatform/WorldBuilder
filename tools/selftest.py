#!/usr/bin/env python3
"""
End-to-end self test. Exercises every tool and data file and reports what breaks.

    python tools/selftest.py
"""
import json, os, subprocess, sys, tempfile, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable
TOOLS = os.path.join(ROOT, "tools")
RESULTS = []


def check(name):
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


def run(script, *args, expect_zero=True):
    r = subprocess.run([PY, os.path.join(TOOLS, script), *args],
                       capture_output=True, text=True, cwd=ROOT)
    if expect_zero and r.returncode != 0:
        raise AssertionError(f"{script} exited {r.returncode}\n{r.stderr[-600:]}")
    return r.stdout


def load(*parts):
    return json.load(open(os.path.join(ROOT, *parts)))


# ---------------------------------------------------------------- data files
@check("catalog.json loads and every path resolves")
def _():
    cat = load("catalog", "catalog.json")
    base = os.path.join(ROOT, cat["root"])
    assert len(cat["assets"]) > 10000, len(cat["assets"])
    missing = [p for e in cat["assets"][:400] for p in e["paths"].values()
               if not os.path.exists(os.path.join(base, p))]
    assert not missing, missing[:3]
    ids = [e["id"] for e in cat["assets"]]
    assert len(ids) == len(set(ids)), "duplicate asset ids"


@check("editor indexes are consistent with the catalog")
def _():
    cat = {e["id"] for e in load("catalog", "catalog.json")["assets"]}
    sheets = load("editor", "sheets.json")["sizes"]["32"]
    singles = load("editor", "singles.json")
    chars = load("editor", "characters.json")
    for s in sheets:
        assert s["id"] in cat, f"sheet not in catalog: {s['id']}"
        assert os.path.exists(os.path.join(ROOT, s["image"])), s["image"]
    labels = [s["label"] for s in sheets]
    assert len(labels) == len(set(labels)), "duplicate sheet labels"
    for cid, recs in list(singles["cats"].items())[:6]:
        for r in recs[:20]:
            assert r["id"] in cat, r["id"]
            assert r["id"] in singles["byId"], f"{r['id']} missing from byId"
    for c in chars:
        assert os.path.exists(os.path.join(ROOT, c["image"])), c["image"]
        assert set(c["dirBlocks"]) == {"right", "up", "left", "down"}


@check("every single referenced by a category exists in byId")
def _():
    s = load("editor", "singles.json")
    ids = set(s["byId"])
    missing = [r["id"] for recs in s["cats"].values() for r in recs if r["id"] not in ids]
    assert not missing, missing[:3]


@check("animation frame layouts divide their sheets exactly")
def _():
    anims = load("editor", "animations.json")
    cat = {e["id"]: e for e in load("catalog", "catalog.json")["assets"]}
    bad = []
    for aid, a in anims.items():
        px = cat[aid]["px"]["32"]
        if a["frame"][0] * a["frames"] != px[0] or a["frame"][1] != px[1]:
            bad.append(aid)
    assert not bad, f"{len(bad)} bad: {bad[:3]}"


@check("collision defaults follow the labelled placement")
def _():
    s = load("editor", "singles.json")["byId"]
    NON = {"floor_overlay", "on_surface", "wall", "mounted"}
    wrong = [k for k, v in s.items()
             if v.get("placement") and (v["placement"] in NON) == bool(v.get("blocks"))]
    assert not wrong, f"{len(wrong)} disagree: {wrong[:3]}"


# ------------------------------------------------------------------ tooling
@check("catalog validator passes")
def _():
    out = run("validate.py")
    assert "duplicate ids: 0" in out and "missing files: 0" in out, out[-300:]


@check("every saved map validates")
def _():
    maps = [f for f in os.listdir(os.path.join(ROOT, "maps")) if f.endswith(".json")]
    assert maps, "no maps to check"
    for m in maps:
        out = run("mapfmt.py", os.path.join("maps", m))
        assert "valid:" in out, f"{m}: {out}"


@check("generated scene is fully reachable")
def _():
    out = run("validate_scene.py", os.path.join("maps", "office_floor.json"))
    assert "every walkable tile is reachable" in out, out[-300:]


@check("scene generator runs and produces a valid map")
def _():
    run("../scenes/office_floor.py")
    out = run("mapfmt.py", os.path.join("maps", "office_floor.json"))
    assert "valid:" in out, out


@check("render produces a non-trivial image")
def _():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "r.png")
        run("render.py", os.path.join("maps", "office_floor.json"), p, "--scale", "1")
        assert os.path.getsize(p) > 20000, os.path.getsize(p)


@check("atlas export round-trips through its own renderer")
def _():
    with tempfile.TemporaryDirectory() as d:
        run("export_atlas.py", os.path.join("maps", "office_floor.json"), d,
            "--name", "t", "--profile", "watercooler")
        out = run("render_tiled.py", os.path.join(d, "t.json"), os.path.join(d, "r.png"))
        assert "tiles drawn from the atlas" in out, out
        n = int(out.split(",")[1].split("tiles")[0])
        assert n > 500, f"only {n} tiles drawn"


@check("WaterCooler maps still round-trip")
def _():
    wc = "/Users/robertchambers/Documents/KeysOff/WaterCooler/public/maps"
    if not os.path.isdir(wc):
        return "skipped (WaterCooler not present)"
    files = [os.path.join(wc, f) for f in sorted(os.listdir(wc)) if f.endswith(".json")]
    out = run("roundtrip_test.py", *files)
    assert "0 failed" in out, out[-400:]


@check("viewer bundle builds and is self-contained")
def _():
    run("build_viewer.py", os.path.join("maps", "office_floor.json"))
    d = os.path.join(ROOT, "viewer", "assets")
    for f in ("scene.json", "scene_atlas.png", "scene_meta.json", "character.png"):
        assert os.path.exists(os.path.join(d, f)), f
    meta = json.load(open(os.path.join(d, "scene_meta.json")))
    assert meta["collisions"] and meta["spawns"]


@check("index builders are idempotent")
def _():
    before = {f: open(os.path.join(ROOT, "editor", f)).read()
              for f in ("sheets.json", "characters.json")}
    run("build_editor_index.py")
    run("build_characters.py")
    for f, b in before.items():
        assert open(os.path.join(ROOT, "editor", f)).read() == b, f"{f} changed"


@check("editor js and html parse")
def _():
    r = subprocess.run(["node", "-e",
                        "new Function(require('fs').readFileSync("
                        "'editor/editor.js','utf8'))"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-400:]
    html = open(os.path.join(ROOT, "editor", "index.html")).read()
    for el in ("newDlg", "sheetSel", "charSel", "selBadge", "snapSel", "btnAuto"):
        assert f'id="{el}"' in html, f"missing #{el}"
    js = open(os.path.join(ROOT, "editor", "editor.js")).read()
    import re
    refs = set(re.findall(r'\$\("#([A-Za-z0-9_]+)"\)', js))
    ids = set(re.findall(r'id="([A-Za-z0-9_]+)"', html))
    missing = sorted(refs - ids)
    assert not missing, f"js references ids not in html: {missing}"


def main():
    print(f"running {len(RESULTS)} checks\n")
    failed = 0
    for name, fn in RESULTS:
        try:
            note = fn()
            print(f"  pass  {name}" + (f"  [{note}]" if note else ""))
        except Exception as e:
            failed += 1
            first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            print(f"  FAIL  {name}\n          {first}")
    print(f"\n{len(RESULTS)-failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
