#!/usr/bin/env python3
"""
Asset references.

Three forms, because maps address art at two different granularities:

  object ref   ext.single.city_props.bench_1     a whole catalogued object
  sprite ref   sprite:ext.single.city_props.bench_1   the same object, painted
                                                 into a tile grid rather than
                                                 placed on the object layer
  tile ref     tile:int.sheet.kitchen#3,10       one 1x1 cell of a sheet image

Tile layers are painted cell by cell, so most cells are *part* of an object rather
than a whole one and have no object id. Tile refs address those directly, which
makes import from Tiled lossless. Object refs carry meaning and are what prompts
produce; tile refs are exact and are what hand-painted detail needs.

resolve() turns either into a PIL image plus its tile footprint.
"""
import functools, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILE_RE = re.compile(r"^tile:([A-Za-z0-9_.]+)#(\d+),(\d+)$")
SPRITE = "sprite:"


@functools.lru_cache(maxsize=1)
def catalog():
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    return cat, {e["id"]: e for e in cat["assets"]}


def object_id(ref):
    """Strip the sprite: prefix the editor writes when a single is painted into a
    tile grid. It names the same catalogued asset as the bare id, so everything
    downstream -- validation, render, export -- treats the two alike."""
    if isinstance(ref, str) and ref.startswith(SPRITE):
        return ref[len(SPRITE):]
    return ref


def is_tile_ref(ref):
    return isinstance(ref, str) and ref.startswith("tile:")


def parse_tile_ref(ref):
    m = TILE_RE.match(ref)
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3))


def make_tile_ref(sheet_id, col, row):
    return f"tile:{sheet_id}#{col},{row}"


def check(ref, size):
    """Return None if the ref is usable at this tile size, else why not."""
    _cat, index = catalog()
    if is_tile_ref(ref):
        parsed = parse_tile_ref(ref)
        if parsed is None:
            return f"malformed tile ref {ref!r}"
        sheet_id, col, row = parsed
        e = index.get(sheet_id)
        if e is None:
            return f"unknown sheet {sheet_id!r}"
        if size not in e["px"]:
            return f"sheet {sheet_id!r} has no {size}px variant"
        w, h = e["px"][size]
        t = int(size)
        if not (0 <= col < w // t and 0 <= row < h // t):
            return f"{ref} is outside the sheet ({w // t}x{h // t} tiles)"
        return None
    ref = object_id(ref)
    e = index.get(ref)
    if e is None:
        return f"unknown asset id {ref!r}"
    if size not in e["paths"]:
        return f"{ref!r} has no {size}px variant"
    return None


@functools.lru_cache(maxsize=64)
def _sheet_image(path):
    from PIL import Image
    return Image.open(path).convert("RGBA")


def resolve(ref, size):
    """(image, (footprint_cols, footprint_rows)) for a ref at this tile size."""
    from PIL import Image
    cat, index = catalog()
    base = os.path.join(ROOT, cat["root"])
    t = int(size)
    if is_tile_ref(ref):
        sheet_id, col, row = parse_tile_ref(ref)
        sheet = _sheet_image(os.path.join(base, index[sheet_id]["paths"][size]))
        return sheet.crop((col * t, row * t, col * t + t, row * t + t)), (1, 1)
    e = index[object_id(ref)]
    im = Image.open(os.path.join(base, e["paths"][size])).convert("RGBA")
    fw, fh = e["tiles"]
    # footprint is in tile units; round up so cropped sprites still get whole cells
    return im, (max(1, -(-im.width // t)), max(1, -(-im.height // t)))
