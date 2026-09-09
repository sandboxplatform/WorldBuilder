#!/usr/bin/env python3
"""
Derive light sources from the sprites a map already contains.

Nobody wants to place a light under every lamp they placed a lamp for. The catalog
already knows what each sprite is -- vocab.json classes 30 concepts as "lighting" --
so the exporter can read the lights straight off the placements, the same way
collision is derived from object type and then overridden by hand.

This runs at export time, not in the game: the runtime consumes Tiled JSON and has
no catalog. Lights ride out as a "lights" object layer, which is a shape Phaser
already parses (see MapHelpers.parseSpawns in the WaterCooler project).

    python3 tools/lights.py maps/chester_harbour.json      # what would be emitted
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Per-concept defaults: radius in pixels, colour, intensity 0..1, flicker 0..1, and
# whether it burns all the time or only after dark. Anything classed "lighting" in
# the vocab but not named here falls back to LIT_DEFAULT.
LIGHT_KINDS = {
    # streets and structures -- big, steady, cool-white
    "street_lamp":     dict(r=132, color="#ffe3ad", intensity=0.95, flicker=0.0,  when="night"),
    # a bare "lamp" is the interior kind -- the vocab calls the outdoor ones
    # street_lamp, so this must not inherit a 132px night-only streetlight
    "lamp":            dict(r=100, color="#ffdca8", intensity=0.8,  flicker=0.0,  when="always"),
    "stadium_light":   dict(r=220, color="#eaf1ff", intensity=1.0,  flicker=0.0,  when="night"),
    "spotlight":       dict(r=180, color="#eaf1ff", intensity=1.0,  flicker=0.0,  when="night"),
    "structure_light": dict(r=110, color="#dbe7ff", intensity=0.8,  flicker=0.0,  when="night"),
    "led_light":       dict(r=64,  color="#bcd8ff", intensity=0.7,  flicker=0.0,  when="always"),
    "lighthouse":      dict(r=260, color="#fff2cc", intensity=1.0,  flicker=0.0,  when="night"),
    "traffic_light":   dict(r=48,  color="#ffd0a0", intensity=0.5,  flicker=0.0,  when="always"),

    # small warm flames -- close in, and they move
    "candle":          dict(r=56,  color="#ffb46b", intensity=0.75, flicker=0.35, when="always"),
    "lantern":         dict(r=88,  color="#ffc985", intensity=0.85, flicker=0.18, when="always"),
    "campfire":        dict(r=150, color="#ff9a4d", intensity=1.0,  flicker=0.30, when="always"),
    "fire":            dict(r=150, color="#ff8a3d", intensity=1.0,  flicker=0.30, when="always"),
    "torch":           dict(r=110, color="#ffab5c", intensity=0.9,  flicker=0.28, when="always"),

    # screens and signage -- weak, cold, and restless
    "tv":              dict(r=72,  color="#9fd4ff", intensity=0.55, flicker=0.22, when="always"),
    "screen":          dict(r=64,  color="#9fd4ff", intensity=0.5,  flicker=0.22, when="always"),
    "monitor":         dict(r=56,  color="#9fd4ff", intensity=0.45, flicker=0.20, when="always"),
    "neon":            dict(r=96,  color="#ff7ae0", intensity=0.8,  flicker=0.08, when="night"),
    "billboard":       dict(r=96,  color="#ffe9b0", intensity=0.6,  flicker=0.0,  when="night"),
    "sign":            dict(r=64,  color="#ffe0a8", intensity=0.5,  flicker=0.0,  when="night"),

    # interiors, mostly from the vision labels rather than from names
    "desk_lamp":            dict(r=76,  color="#ffdca8", intensity=0.7,  flicker=0.0,  when="always"),
    "dome_light":           dict(r=118, color="#fff0cf", intensity=0.85, flicker=0.0,  when="always"),
    "light_strip":          dict(r=90,  color="#e6f0ff", intensity=0.6,  flicker=0.0,  when="always"),
    "string_lights":        dict(r=84,  color="#ffd08a", intensity=0.6,  flicker=0.10, when="night"),
    "fireplace":            dict(r=140, color="#ff9440", intensity=0.95, flicker=0.30, when="always"),
    "firewood":             dict(r=110, color="#ff8a3d", intensity=0.8,  flicker=0.28, when="always"),
    "projector_screen":     dict(r=88,  color="#bcd8ff", intensity=0.5,  flicker=0.14, when="always"),
    "presentation_screen":  dict(r=88,  color="#bcd8ff", intensity=0.5,  flicker=0.14, when="always"),

    # water
    "buoy":            dict(r=52,  color="#ff6b5c", intensity=0.7,  flicker=0.12, when="night"),
}
# Names that read like lights and are not. Matching is exact, so "fire_extinguisher"
# never collides with "fire" -- this list is a guard against the table growing sloppy.
NOT_LIGHTS = {"fire_extinguisher", "fire_hydrant", "fire_truck", "lighthouse_door",
              "light_flower", "traffic_lights_frontal"}
LIT_DEFAULT = dict(r=96, color="#ffd9a0", intensity=0.8, flicker=0.0, when="night")

# Ambient tint the runtime lerps between. Not a light -- the colour of the dark.
AMBIENT = {"day": "#ffffff", "dusk": "#e0a86a", "night": "#1b2a4a", "darkness": 0.72}


def _sheet_cells():
    """(sheet, col, row) -> single id. A map can stamp a lamp straight off a sheet,
    and that ref carries no name to parse; sheet_xy.json says which sprite occupies
    each cell, which is how a stamped lamp gets its concept back."""
    loc = json.load(open(os.path.join(ROOT, "catalog", "sheet_xy.json")))["located"]
    out = {}
    for sid, l in loc.items():
        c0, r0 = l["tile"]
        sw, sh = l["span"]
        for dy in range(sh):
            for dx in range(sw):
                out.setdefault((l["sheet"], c0 + dx, r0 + dy), sid)
    return out


def _labels():
    """Vision-pass concepts. The office pack numbers its sprites -- n3, n56 -- so
    there is no name to parse and this is the only thing that knows what they are."""
    p = os.path.join(ROOT, "catalog", "labels.json")
    return json.load(open(p))["labels"] if os.path.exists(p) else {}


def _vocab_classes():
    """concept or alias -> class, so a sprite can be asked what kind of thing it is."""
    v = json.load(open(os.path.join(ROOT, "catalog", "vocab.json")))
    rows = v if isinstance(v, list) else v.get("concepts", v)
    out = {}
    for r in rows:
        if not isinstance(r, dict) or "concept" not in r:
            continue
        out[r["concept"]] = r.get("class")
        for al in r.get("aliases", []):
            out.setdefault(al, r.get("class"))
    return out


def _kind_for(names, classes):
    """The light table entry for a sprite, or None if it does not glow. `names` is
    tried in order of trust: a vision label beats a parsed name."""
    names = [n for n in names if n and n not in NOT_LIGHTS]
    for key in names:
        if key in LIGHT_KINDS:
            return key, LIGHT_KINDS[key]
    # a name the table does not list but the vocab calls lighting still lights up
    for key in names:
        if classes.get(key) == "lighting":
            return key, LIT_DEFAULT
    return None, None


def lights_for(m, facets=None, classes=None, labels=None, cells=None):
    """Every light a map's placements imply, in map pixels."""
    facets = facets if facets is not None else json.load(
        open(os.path.join(ROOT, "catalog", "facets.json")))["assets"]
    classes = classes if classes is not None else _vocab_classes()
    labels = labels if labels is not None else _labels()
    cells = cells if cells is not None else _sheet_cells()
    T = m["tile"]
    ref = re.compile(r"^tile:(.+)#(\d+),(\d+)$")
    out = []
    for L in m.get("layers", []):
        for p in L.get("placements", []):
            aid = p["id"]
            mt = ref.match(aid)
            if mt:
                # a tile stamped off a sheet: ask sheet_xy which sprite lives there
                aid = cells.get((mt.group(1), int(mt.group(2)), int(mt.group(3))))
                if not aid:
                    continue
            fa = facets.get(aid) or {}
            nf = fa.get("name_facets", {})
            lab = labels.get(aid) or {}
            # trust order: what the vision pass called it, then what its name says
            kind, spec = _kind_for([lab.get("concept"), nf.get("concept"),
                                    nf.get("head")], classes)
            if not spec:
                continue
            bbox = fa.get("pixel_facets", {}).get("bbox") or [0, 0, T, T]
            _bx, _by, bw, bh = bbox
            off = p.get("off", (0, 0))
            x0 = p["at"][0] * T + off[0]
            y0 = p["at"][1] * T + off[1]
            # A lamp glows at its head, not its feet: on anything taller than two
            # tiles put the source near the top, otherwise at the middle.
            cx = x0 + bw / 2
            cy = y0 + (min(bh / 4, T) if bh > 2 * T else bh / 2)
            out.append({"x": round(cx, 1), "y": round(cy, 1), "kind": kind,
                        "id": aid, **spec})
    return out


def tiled_layer(lights, lid):
    """The lights as a Tiled object layer -- point objects with typed properties."""
    def prop(n, v):
        t = "float" if isinstance(v, (int, float)) and not isinstance(v, bool) else "string"
        return {"name": n, "type": t, "value": v}

    objects = []
    for i, l in enumerate(lights, 1):
        objects.append({
            "id": i, "name": l["kind"], "type": "light", "point": True,
            "x": l["x"], "y": l["y"], "width": 0, "height": 0,
            "rotation": 0, "visible": True,
            "properties": [prop("r", l["r"]), prop("color", l["color"]),
                           prop("intensity", l["intensity"]),
                           prop("flicker", l["flicker"]), prop("when", l["when"])],
        })
    return {"type": "objectgroup", "name": "lights", "id": lid,
            "x": 0, "y": 0, "opacity": 1, "visible": True,
            "draworder": "topdown", "objects": objects}


def ambient_props():
    return [{"name": f"ambient_{k}", "type": "float" if isinstance(v, float) else "string",
             "value": v} for k, v in AMBIENT.items()]


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 1
    m = json.load(open(sys.argv[1]))
    lights = lights_for(m)
    from collections import Counter
    by = Counter(l["kind"] for l in lights)
    print(f"  {len(lights)} lights from {sum(len(L.get('placements', [])) for L in m.get('layers', []))} placements")
    for k, n in by.most_common():
        s = LIGHT_KINDS.get(k, LIT_DEFAULT)
        print(f"    {n:4}  {k:<16} r={s['r']:<4} {s['color']}  {s['when']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
