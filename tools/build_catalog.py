#!/usr/bin/env python3
"""
Build a queryable catalog of every asset in the LimeZu packs under images/extracted.

Produces catalog/catalog.json:  one entry per *logical asset*, with the 16/32/48
pixel-size variants collapsed into a single record, plus a stable id, a semantic
name where the pack provides one, tile footprint, and tags.

Addressing scheme (see ASSETS.md):
    <pack>.<kind>.<category>.<name>
e.g.  ext.single.city_props.barrel_1
      int.single.kitchen.n123
      int.sheet.kitchen
      char.hairstyle.hair_01
"""
import json, os, re, struct, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACTED = os.path.join(ROOT, "images", "extracted")
OUT = os.path.join(ROOT, "catalog", "catalog.json")

SIZES = ("16", "32", "48")

# Exteriors theme numbers, as used by the ME_Theme_Sorter folders. Filenames in
# Modern_Exteriors_Complete_Singles carry only this number, not the theme name.
EXT_THEMES = {
    "1": "terrains_and_fences", "2": "city_terrains", "3": "city_props",
    "4": "generic_building", "5": "floor_modular_building", "6": "garage_sales",
    "7": "villas", "8": "worksite", "9": "shopping_center_and_markets",
    "10": "vehicles", "11": "camping", "12": "hotel_and_hospital", "13": "school",
    "14": "swimming_pool", "15": "police_station", "16": "office", "17": "garden",
    "18": "fire_station", "19": "graveyard", "20": "subway_and_train_station",
    "21": "beach", "22": "post_office", "23": "military_base",
    "24": "additional_houses",
}


def png_size(path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def slug(s):
    s = re.sub(r"\.(png|gif|ase|aseprite)$", "", s, flags=re.I)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return re.sub(r"_+", "_", s)


# --- size-variant normalisation -------------------------------------------------
# Collapse .../32x32/... and _32x32 into a {S} placeholder so the three exports of
# one logical asset fold into a single catalog entry.
# the packs contain a typo ("17_Garden_48xx48.png"), so allow the doubled x too
SIZE_RE = re.compile(r"(?<![0-9])(16xx?16|32xx?32|48xx?48)(?![0-9])")


def normalize(rel):
    """Return (template, size) where template has the size token replaced by {S}."""
    found = SIZE_RE.findall(rel)
    if not found:
        return rel, None
    size = re.match(r"\d+", found[0]).group(0)
    return SIZE_RE.sub("{S}", rel), size


# --- classification -------------------------------------------------------------
def classify(rel):
    """Map a relative path to (pack, kind, category, name) or None to skip."""
    parts = rel.split("/")
    top = parts[0]
    p = rel  # shorthand

    # ---------- Modern Exteriors ----------
    if top == "modernexteriors-win":
        if "/OLD" in p or "Old_Sorting" in p:
            return None
        if "Character_Generator_Addons" in p:
            return ("ext", "character", "addon", slug(parts[-1]))
        if "Animated" in p and "Vehicles" in p:
            sub = parts[-2] if len(parts) > 2 else "vehicles"
            return ("ext", "vehicle", slug(sub), slug(parts[-1]))
        if "Animated_sheets" in p or "Animated_Terrains" in p:
            cat = "terrain" if "Terrains" in p else "object"
            return ("ext", "animated", cat, slug(parts[-1]))
        if "Autotiles" in p:
            kind = "autotile_single" if "Singles" in p else "autotile"
            return ("ext", kind, "gms", slug(parts[-1]))
        if "Complete_Tileset" in p:
            return ("ext", "sheet", "complete", "complete")
        if "Singles" in p:
            # ME_Singles_<Category>_32x32_<Name>.png  -> semantic name
            m = re.match(r"ME_Singles_(.+?)_(?:16x16|32x32|48x48)_(.+)\.png$", parts[-1])
            if m:
                return ("ext", "single", slug(m.group(1)), slug(m.group(2)))
            # alternate convention in Modern_Exteriors_Complete_Singles
            m = re.match(r"(\d+)_(.+?)_(?:16x16|32x32|48x48)_(.+)\.png$", parts[-1])
            if m:
                return ("ext", "single", EXT_THEMES.get(m.group(1), slug(m.group(2))),
                        slug(m.group(3)))
            # ...and some with no size token at all, so the theme number decides
            m = re.match(r"(\d+)_(.+)\.png$", parts[-1])
            if m and m.group(1) in EXT_THEMES:
                theme = EXT_THEMES[m.group(1)]
                rest = slug(m.group(2))
                if rest.startswith(theme + "_"):
                    rest = rest[len(theme) + 1:]
                return ("ext", "single", theme, rest)
            m = re.match(r"ME_Singles_(.+)\.png$", parts[-1])
            if m:
                rest = slug(m.group(1))
                for theme in sorted(set(EXT_THEMES.values()), key=len, reverse=True):
                    head = theme.split("_")[0]
                    if rest.startswith(head + "_"):
                        return ("ext", "single", theme, rest[len(head) + 1:])
                return ("ext", "single", "misc", rest)
            folder = re.sub(r"^\d+_", "", parts[-2])
            return ("ext", "single", slug(re.sub(r"_Singles.*$", "", folder)), slug(parts[-1]))
        if "ME_Theme_Sorter" in p and parts[-1].endswith(".png"):
            return ("ext", "sheet", slug(SIZE_RE.sub("", re.sub(r"^\d+_", "", parts[-1])).replace("_.png", "").replace(".png", "")), "sheet")
        return None

    # ---------- Modern Interiors ----------
    if top == "moderninteriors-win":
        if "Old_Stuff" in p or "/Old/" in p:
            return None
        if "Character_Generator" in p:
            layer = None
            for lay in ("Bodies_kids", "Bodies", "Eyes_kids", "Eyes", "Hairstyles_kids",
                        "Hairstyles", "Outfits_kids", "Outfits", "Accessories",
                        "Books", "Smartphones", "0_Premade_Characters"):
                if f"/{lay}/" in p:
                    layer = lay
                    break
            if layer is None:
                return None
            return ("char", "premade" if layer.startswith("0_") else "layer", slug(layer), slug(parts[-1]))
        if "3_Animated_objects" in p:
            return ("int", "animated", "object", slug(parts[-1]))
        if "4_User_Interface_Elements" in p:
            return ("int", "ui", "emote", slug(parts[-1]))
        if "6_Home_Designs" in p:
            return ("int", "design", slug(parts[1].replace("_Designs", "")), slug(parts[-1]))
        if "Room_Bulder_subfiles" in p:
            return ("int", "roombuilder", slug(re.sub(r"^Room_Builder_|_(16x16|32x32|48x48)\.png$", "", parts[-1])), "part")
        if re.search(r"Room_Builder_(16x16|32x32|48x48)\.png$", parts[-1]):
            return ("int", "roombuilder", "complete", "complete")
        if "Theme_Sorter" in p and "Singles" in p:
            shade = ("shadowless" if "Shadowless" in p else
                     "black_shadow" if "Black_Shadow" in p else "shadow")
            if shade != "shadow":
                return None  # index the default shaded variant only
            folder = re.sub(r"^\d+_|_S[Ii]ngles.*$", "", parts[-2])
            m = re.search(r"_(\d+)\.png$", parts[-1])
            name = f"n{m.group(1)}" if m else slug(parts[-1])
            return ("int", "single", slug(folder), name)
        if "Theme_Sorter" in p:
            if "Shadowless" in p or "Black_Shadow" in p:
                return None
            return ("int", "sheet",
                    slug(SIZE_RE.sub("", re.sub(r"^\d+_", "", parts[-1])).replace("_.png", "").replace(".png", "")), "sheet")
        if re.search(r"Interiors_(16x16|32x32|48x48)\.png$", parts[-1]):
            return ("int", "sheet", "complete", "complete")
        if "Palettes" in p:
            return ("int", "palette", "palette", slug(parts[-1]))
        return None

    # ---------- Modern Office ----------
    if top == "Modern_Office_Revamped_v1.2":
        if "Previous_Version" in p or "RPG_MAKER" in p:
            return None
        if "Room_Builder_Office" in p:
            return ("office", "roombuilder", "office", slug(parts[-1]))
        if "singles" in p.lower():
            m = re.search(r"_(\d+)\.png$", parts[-1])
            return ("office", "single", "office", f"n{m.group(1)}" if m else slug(parts[-1]))
        if "Office_Designs" in p:
            return ("office", "design", "office", slug(parts[-1]))
        if "Shadowless" in p or "Black_Shadow" in p:
            return None
        if re.match(r"Modern_Office_(16x16|32x32|48x48)\.png$", parts[-1]):
            return ("office", "sheet", "office", "sheet")
        return None

    # ---------- Modern UI ----------
    if top == "modernuserinterface-win":
        if "Portrait_Generator" in p:
            layer = None
            for lay in ("Accessories", "Eyes", "Hairstyles", "Skins"):
                if f"/{lay}" in p:
                    layer = lay
                    break
            return ("ui", "portrait", slug(layer or "misc"), slug(parts[-1]))
        return ("ui", "sheet", "ui", slug(parts[-1]))

    return None


def main():
    if not os.path.isdir(EXTRACTED):
        sys.exit(f"missing {EXTRACTED} — run the unzip step first")

    entries = {}
    skipped = 0
    for dirpath, _dirs, files in os.walk(EXTRACTED):
        for fn in files:
            if not fn.lower().endswith(".png"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, EXTRACTED)
            c = classify(rel)
            if c is None:
                skipped += 1
                continue
            pack, kind, category, name = c
            category = SIZE_RE.sub("", category).strip("_").replace("__", "_")
            name = SIZE_RE.sub("", name).strip("_").replace("__", "_")
            template, size = normalize(rel)
            aid = f"{pack}.{kind}.{category}.{name}"
            # strip the size token out of the name so variants collapse
            aid = SIZE_RE.sub("", aid).replace("__", "_").replace("._", ".").rstrip("._")

            wh = png_size(path)
            e = entries.setdefault(aid, {
                "id": aid, "pack": pack, "kind": kind, "category": category,
                "name": name, "paths": {}, "px": {}, "tiles": None,
            })
            key = size or "na"
            prev = e["paths"].get(key)
            # the same object ships in both the per-theme and the "Complete_Singles"
            # folders; keep the per-theme copy as canonical
            if prev is None or ("Theme_Sorter" in rel and "Theme_Sorter" not in prev):
                e["paths"][key] = rel
            if wh:
                e["px"][key] = [wh[0], wh[1]]

    # tile footprint from the 32px variant where available
    for e in entries.values():
        for s in ("32", "48", "16", "na"):
            if s in e["px"]:
                t = int(s) if s != "na" else 32
                w, h = e["px"][s]
                e["tiles"] = [round(w / t, 2), round(h / t, 2)]
                e["grid_aligned"] = (w % t == 0 and h % t == 0)
                break
        e["sizes"] = sorted(k for k in e["paths"] if k != "na")

    cat = {
        "version": 1,
        "root": os.path.relpath(EXTRACTED, ROOT),
        "note": "LimeZu asset packs - licensed, NOT redistributable. Keep local.",
        "assets": sorted(entries.values(), key=lambda e: e["id"]),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(cat, f, separators=(",", ":"))

    # ---- summary ----
    by = collections.Counter((e["pack"], e["kind"]) for e in entries.values())
    print(f"indexed {len(entries)} logical assets  (skipped {skipped} files: legacy/duplicate-shade/rpgmaker)")
    print(f"wrote {OUT}  ({os.path.getsize(OUT)/1e6:.1f} MB)\n")
    for (pack, kind), n in sorted(by.items()):
        print(f"  {pack:7s} {kind:16s} {n:6d}")
    named = sum(1 for e in entries.values()
                if e["kind"] == "single" and not re.fullmatch(r"n\d+", e["name"]))
    singles = sum(1 for e in entries.values() if e["kind"] == "single")
    print(f"\n  singles: {singles} total, {named} semantically named "
          f"({100*named/max(singles,1):.0f}%), {singles-named} number-only")


if __name__ == "__main__":
    main()
