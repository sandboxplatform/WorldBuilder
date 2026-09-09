#!/usr/bin/env python3
"""
Generate a scene from labelled assets.

This is the payoff for the catalog work: rooms are described by *what they are*
("an open-plan office 16x10"), and the generator resolves that to concrete assets
through the concept vocabulary, the placement facets and the measured finishes.

Placement comes from the four-way facet split established during labelling:
  wall           -> hung on the wall band at the top of a room
  floor          -> stands on the floor
  on_surface     -> goes ON a floor item that is a surface (desk, table, counter)
  floor_overlay  -> rugs and mats, drawn under everything

Style coherence uses the measured `finish` facet, so all the desks in one room
share a surface rather than being a random mix.
"""
import json, os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RB = "office.roombuilder.office.room_builder_office"

# Read off the Room_Builder_Office sheet: walls occupy cols 0-9 rows 5-12 in
# four styles of two rows each; floors occupy cols 10-15 rows 5-12.
WALL_STYLES = {
    "lavender": 5, "stone": 7, "brick": 9, "white": 11,
}
FLOORS = {
    "grey": (11, 6), "pale": (10, 5), "dark": (11, 8),
    "olive": (14, 8), "maroon": (11, 12), "wood": (14, 10),
}

# Concepts that other things can be placed on top of.
SURFACES = {"desk", "table", "counter", "sideboard", "console_table", "side_table",
            "shelf", "cabinet", "dresser", "vanity"}


def tile(col, row, sheet=RB):
    return f"tile:{sheet}#{col},{row}"


class Library:
    """Query the catalog through labels, facets and vocabulary."""

    def __init__(self):
        cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
        self.index = {e["id"]: e for e in cat["assets"]}
        self.labels = json.load(open(os.path.join(ROOT, "catalog", "labels.json")))["labels"]
        self.facets = json.load(open(os.path.join(ROOT, "catalog", "facets.json")))["assets"]

    def find(self, concept, theme=None, placement=None, finish=None,
             max_tiles=None, exclude_composite=False):
        out = []
        for aid, lab in self.labels.items():
            if lab.get("concept") != concept:
                continue
            if theme and f".{theme}." not in aid:
                continue
            if placement and lab.get("placement") != placement:
                continue
            if exclude_composite and lab.get("composite"):
                continue
            e = self.index[aid]
            if max_tiles and (e["tiles"][0] > max_tiles[0] or e["tiles"][1] > max_tiles[1]):
                continue
            if finish:
                pf = self.facets.get(aid, {}).get("pixel_facets", {})
                if pf.get("finish") != finish:
                    continue
            out.append(aid)
        return sorted(out)

    def size(self, aid):
        """Footprint in tiles, measured from the *content*, not the canvas.

        Office singles are all exported on a 2x3 canvas regardless of how big the
        object is, so spacing by canvas size leaves huge gaps. The pixel facets
        carry the real content bounds.
        """
        pf = self.facets.get(aid, {}).get("pixel_facets", {})
        bbox = pf.get("bbox")
        if bbox:
            _x, _y, bw, bh = bbox
            return max(1, -(-bw // 32)), max(1, -(-bh // 32))
        w, h = self.index[aid]["tiles"]
        return max(1, int(w + 0.999)), max(1, int(h + 0.999))

    def collision_box(self, aid, placement):
        """
        Pixel box (x, y, w, h) inside the sprite that actually blocks movement,
        relative to the content bounds. None means the asset blocks nothing.

        The rules come straight out of the facet work:
          floor_overlay  rugs and mats -- you walk over them
          on_surface     a monitor does not block; the desk under it does
          wall           hung above floor level, you walk beneath it
          floor          blocks only where it MEETS THE FLOOR, which is what the
                         shadow-diff measured. Using the whole sprite makes every
                         object about twice its real width (median shadow area is
                         44% of sprite area) and the room feels clogged.
        """
        if placement in ("floor_overlay", "on_surface", "wall", "mounted"):
            return None
        pf = self.facets.get(aid, {}).get("pixel_facets", {})
        bb = pf.get("bbox")
        if not bb:
            return None
        bx, by, bw, bh = bb
        sb = pf.get("shadow_bbox")
        if sb:
            # shadow bounds are absolute in the sprite; make them content-relative
            return (sb[0] - bx, sb[1] - by, sb[2], sb[3])
        # no shadow twin (exteriors): fall back to the lower third, which is where
        # a top-down sprite's base sits
        base = max(8, bh // 3)
        return (0, bh - base, bw, base)

    def offset(self, aid):
        """Where the content sits inside its canvas, in tiles (left, top)."""
        pf = self.facets.get(aid, {}).get("pixel_facets", {})
        bbox = pf.get("bbox")
        return (bbox[0] // 32, bbox[1] // 32) if bbox else (0, 0)


class Scene:
    def __init__(self, cols, rows, rng):
        self.cols, self.rows = cols, rows
        self.rng = rng
        self.floor = {}                    # (x,y) -> ref
        self.walls = {}
        self.overlay = []                  # (ref, x, y)
        self.furniture = []
        self.props = []
        self.occupied = set()              # tiles taken by furniture footprints
        self.surfaces = []                 # (x, y, w, concept) tops available
        self.used_tops = set()             # surfaces already carrying something
        self.blockers = []                 # pixel-space collision boxes
        self.reserved = set()              # circulation: no furniture, still walkable
        self.solid_tiles = set()           # structural collision (walls)
        self.open_tiles = set()            # doorways: never solid

    # ---- structure -------------------------------------------------------
    def room(self, x, y, w, h, wall="white", floor="grey"):
        """Floor plus a two-tile wall band along the top and single side walls."""
        fc, fr = FLOORS[floor]
        for yy in range(y + 2, y + h):
            for xx in range(x, x + w):
                self.floor[(xx, yy)] = tile(fc, fr)
        top = WALL_STYLES[wall]
        for i, xx in enumerate(range(x, x + w)):
            col = 0 if i == 0 else (2 if i == w - 1 else 1)
            self.walls[(xx, y)] = tile(col, top)
            self.walls[(xx, y + 1)] = tile(col, top + 1)
        for yy in range(y + 2, y + h):
            self.walls[(x, yy)] = tile(0, top + 1)
            self.walls[(x + w - 1, yy)] = tile(2, top + 1)
        # the wall band and the side walls are solid, for both layout and the player
        for xx in range(x, x + w):
            for yy in (y, y + 1):
                self.occupied.add((xx, yy)); self.solid_tiles.add((xx, yy))
        for yy in range(y, y + h):
            for xx in (x, x + w - 1):
                self.occupied.add((xx, yy)); self.solid_tiles.add((xx, yy))

    def door(self, x, y, w=1, h=1, floor="grey"):
        """Cut an opening through a wall and lay floor through it."""
        fc, fr = FLOORS[floor]
        for xx in range(x, x + w):
            for yy in range(y, y + h):
                self.walls.pop((xx, yy), None)
                self.floor[(xx, yy)] = tile(fc, fr)
                self.occupied.discard((xx, yy))
                self.solid_tiles.discard((xx, yy))
                self.open_tiles.add((xx, yy))

    def corridor(self, x, y, w, h, floor="grey"):
        fc, fr = FLOORS[floor]
        for xx in range(x, x + w):
            for yy in range(y, y + h):
                self.floor[(xx, yy)] = tile(fc, fr)

    def aisle(self, x, y, w, h):
        """Reserve circulation. Furniture may not go here; the player still can.

        Real rooms are laid out around how people move through them, so the walkways
        are carved first and the furniture fills what is left -- rather than
        scattering furniture and hoping a path survives.
        """
        for xx in range(x, x + w):
            for yy in range(y, y + h):
                if 0 <= xx < self.cols and 0 <= yy < self.rows:
                    self.reserved.add((xx, yy))

    def free(self, x, y, w, h):
        if x < 0 or y < 0 or x + w > self.cols or y + h > self.rows:
            return False
        return all((xx, yy) not in self.occupied and (xx, yy) not in self.reserved
                   for xx in range(x, x + w) for yy in range(y, y + h))

    def take(self, x, y, w, h):
        for xx in range(x, x + w):
            for yy in range(y, y + h):
                self.occupied.add((xx, yy))

    # ---- placement -------------------------------------------------------
    def place(self, lib, aid, x, y, layer="furniture", surface=False,
              placement=None):
        w, h = lib.size(aid)
        if not self.free(x, y, w, h):
            return False
        self.take(x, y, w, h)
        (self.furniture if layer == "furniture" else self.props).append((aid, x, y))
        if surface:
            self.surfaces.append((x, y, w, aid))
        pl = placement or lib.labels.get(aid, {}).get("placement", "floor")
        box = lib.collision_box(aid, pl)
        if box:
            bx, by, bw, bh = box
            self.blockers.append((x * 32 + bx, y * 32 + by, bw, bh))
        return True

    def place_on_wall(self, lib, aid, room, tries=30):
        """Hang against the inside face of the top wall band."""
        rx, ry, rw, _rh = room
        w, h = lib.size(aid)
        for _ in range(tries):
            x = self.rng.randrange(rx + 1, max(rx + 2, rx + rw - w))
            y = ry + 2 - h
            if y >= 0 and self.free(x, max(0, y), w, h):
                self.take(x, max(0, y), w, h)
                self.props.append((aid, x, max(0, y)))
                return True   # wall-hung: no collision box
        return False

    def place_in_room(self, lib, aid, room, tries=60, surface=False, layer="furniture"):
        rx, ry, rw, rh = room
        w, h = lib.size(aid)
        for _ in range(tries):
            x = self.rng.randrange(rx + 1, max(rx + 2, rx + rw - w))
            y = self.rng.randrange(ry + 2, max(ry + 3, ry + rh - h))
            if self.place(lib, aid, x, y, layer=layer, surface=surface):
                return True
        return False

    def place_on_surface(self, lib, aid):
        """Sit an item on top of an existing surface, centred on its front edge."""
        order = list(self.surfaces)
        self.rng.shuffle(order)
        w, h = lib.size(aid)
        for (sx, sy, sw, _c) in order:
            if sw < w or (sx, sy) in self.used_tops:
                continue
            x = sx + (sw - w) // 2
            self.props.append((aid, x, sy))
            self.used_tops.add((sx, sy))
            return True
        return False

    # ---- arrangement -----------------------------------------------------
    def along_wall(self, lib, ids, room, side="top", gap=1, layer="furniture",
                   surface=False):
        """Line items up against one wall of a room, in order."""
        rx, ry, rw, rh = room
        placed, cursor = 0, 0
        for aid in ids:
            w, h = lib.size(aid)
            if side == "top":
                x, y = rx + 1 + cursor, ry + 2
                step = w + gap
                if x + w > rx + rw - 1:
                    break
            elif side == "bottom":
                x, y = rx + 1 + cursor, ry + rh - h
                step = w + gap
                if x + w > rx + rw - 1:
                    break
            elif side == "left":
                x, y = rx + 1, ry + 2 + cursor
                step = h + gap
                if y + h > ry + rh:
                    break
            else:  # right
                x, y = rx + rw - 1 - w, ry + 2 + cursor
                step = h + gap
                if y + h > ry + rh:
                    break
            if self.place(lib, aid, x, y, layer=layer, surface=surface):
                placed += 1
            cursor += step
        return placed

    def desk_bank(self, lib, desk_ids, chair_ids, room, banks=2, per_bank=5,
                  aisle_w=2):
        """
        Back-to-back desk banks with a shared chair aisle, then a walking aisle.

        This is how an open-plan floor is actually laid out: desks face each other
        across a bank, people sit between them, and a clear aisle runs between banks.
        """
        rx, ry, rw, rh = room
        dw, dh = lib.size(desk_ids[0])
        ch0 = chair_ids[0]
        cw, chh = lib.size(ch0)
        bank_h = dh + chh + dh          # desks, chairs, desks
        n = 0
        y = ry + 3
        for b in range(banks):
            if y + bank_h > ry + rh - 1:
                break
            x = rx + 2
            for i in range(per_bank):
                if x + dw > rx + rw - 2:
                    break
                top = desk_ids[n % len(desk_ids)]
                bot = desk_ids[(n + 1) % len(desk_ids)]
                self.place(lib, top, x, y, surface=True)
                self.place(lib, bot, x, y + dh + chh, surface=True)
                ch = chair_ids[n % len(chair_ids)]
                self.place(lib, ch, x, y + dh)
                n += 2
                x += dw + 1
            y += bank_h + aisle_w
            self.aisle(rx + 1, y - aisle_w, rw - 2, aisle_w)
        return n

    def stamp(self, sheet_id, col, row, w, h, x, y, layer="furniture",
              solid_from=None):
        """
        Place a w x h block of tiles straight from a sheet, keeping their
        arrangement intact.

        Many objects in these packs are multi-tile assemblies -- a cubicle panel is
        a top, a body and a footed base; a desk is a slab with a base rail. The
        pre-cut singles chop those into pieces that cannot be reassembled by
        guesswork. Addressing the sheet by tile keeps the author's own composition.

        solid_from: first local row that blocks the player (the base of the object).
                    None means the whole block is decorative.
        """
        for dy in range(h):
            for dx in range(w):
                tx, ty = x + dx, y + dy
                if not (0 <= tx < self.cols and 0 <= ty < self.rows):
                    continue
                ref = f"tile:{sheet_id}#{col + dx},{row + dy}"
                (self.furniture if layer == "furniture" else self.props).append(
                    (ref, tx, ty))
                self.occupied.add((tx, ty))
                if solid_from is not None and dy >= solid_from:
                    self.solid_tiles.add((tx, ty))
        return True

    # Multi-tile assemblies read straight off the office sheet, as blocks that keep
    # the author's own composition. (col, row, w, h) in sheet tiles.
    OFFICE_SHEET = "office.sheet.office.sheet"
    PARTITION = (1, 1, 3, 2)      # fabric panel plus its footed base rail
    DESK_TAN = (7, 28, 3, 2)      # surface plus base rail
    DESK_LILAC = (0, 30, 3, 2)
    DESK_L = (0, 34, 3, 3)        # corner return

    def office_bay(self, lib, x, y, items, chair=None, desk=None, partition=True):
        """
        One cubicle: partition panel, desk assembly, kit on the surface, chair.

        Each part is stamped as a block so its pieces stay in the right relative
        positions -- a partition is a panel over a footed rail, a desk is a surface
        over a base rail, and neither survives being placed as loose 1x1 singles.
        """
        d = desk or self.DESK_TAN
        top = y
        if partition:
            pc, pr, pw, ph = self.PARTITION
            self.stamp(self.OFFICE_SHEET, pc, pr, pw, ph, x, top, solid_from=ph - 1)
            top += ph
        dc, dr, dw, dh = d
        self.stamp(self.OFFICE_SHEET, dc, dr, dw, dh, x, top, solid_from=dh - 1)
        # Rest each item ON the desk: the slab spans both stamped rows, so an item's
        # base has to land at the bottom of the slab, not the top of the first row.
        # Anchoring one row higher leaves everything hovering in the partition.
        for i, it in enumerate(items[:dw]):
            _iw, ih = lib.size(it)
            self.props.append((it, x + i, top + dh - ih))
        if chair:
            cw, _ch = lib.size(chair)
            self.place(lib, chair, x + max(0, (dw - cw) // 2), top + dh)
        return dw

    def workstation(self, lib, desk, partition, chair, items, x, y):
        """
        Compose one workstation the way the pack's own office designs do:

            partition          cubicle panel forming the back of the bay
            desk               a multi-tile surface slab
            items on the desk  monitor, keyboard, papers, mug -- spread across it
            chair              tucked in front

        Placing a bare desk sprite and calling it furnished is what made the first
        pass look empty: in the source art a desk is never on its own.
        """
        dw, dh = lib.size(desk)
        if partition:
            pw, ph = lib.size(partition)
            for px in range(x, x + dw, max(1, pw)):
                self.place(lib, partition, px, y - ph, layer="furniture")
        if not self.place(lib, desk, x, y, surface=True):
            return 0
        # spread items across the desk's own width, on its top row
        n = 0
        for i, it in enumerate(items):
            if i >= dw:
                break
            iw, ih = lib.size(it)
            self.props.append((it, x + i, y))       # on_surface: never blocks
            n += 1
        if chair:
            cw, chh = lib.size(chair)
            self.place(lib, chair, x + max(0, (dw - cw) // 2), y + dh)
        return n

    def workstation_row(self, lib, desks, partitions, chairs, item_pool, room,
                        x, y, count, gap=0):
        """A run of workstations sharing a partition wall, as in a real bay."""
        made = 0
        rx, ry, rw, rh = room
        for i in range(count):
            d = desks[i % len(desks)]
            dw, _dh = lib.size(d)
            if x + dw > rx + rw - 1:
                break
            items = [item_pool[(i * 3 + k) % len(item_pool)] for k in range(dw)]
            if self.workstation(lib, d, partitions[i % len(partitions)] if partitions else None,
                                chairs[i % len(chairs)] if chairs else None,
                                items, x, y):
                made += 1
            x += dw + gap
        return made

    def cubicles(self, lib, ids, room, side="top", pitch=3):
        """Fixtures spaced on a pitch, with the gap between them kept clear."""
        rx, ry, rw, rh = room
        placed = 0
        for i, aid in enumerate(ids):
            w, h = lib.size(aid)
            x = rx + 1 + i * pitch
            if x + w > rx + rw - 1:
                break
            y = ry + 2 if side == "top" else ry + rh - h
            if self.place(lib, aid, x, y):
                placed += 1
                self.aisle(x + w, y, max(0, pitch - w), h)
        return placed

    def table_run(self, lib, table_ids, chair_ids, room, length, cy_off=0,
                  chairs_both_sides=True):
        """A long table down the middle of a room with chairs along both sides."""
        rx, ry, rw, rh = room
        tw, th = lib.size(table_ids[0])
        total = length * tw
        x0 = rx + (rw - total) // 2
        y0 = ry + (rh - th) // 2 + cy_off
        placed = 0
        for i in range(length):
            aid = table_ids[i % len(table_ids)]
            if self.place(lib, aid, x0 + i * tw, y0, surface=True):
                placed += 1
        if chair_ids:
            for i in range(length):
                ch = chair_ids[i % len(chair_ids)]
                cw, chh = lib.size(ch)
                self.place(lib, ch, x0 + i * tw, y0 + th)
                if chairs_both_sides:
                    self.place(lib, ch, x0 + i * tw, y0 - chh)
        return placed

    def seating_cluster(self, lib, table_ids, sofa_ids, chair_ids, room,
                        cx=None, cy=None):
        """
        A low table with seating addressed at it: sofas above and below, chairs at
        the ends. People sit facing each other across a table, so the arrangement
        is built around the table rather than scattered near it.
        """
        rx, ry, rw, rh = room
        cx = cx if cx is not None else rx + rw // 2
        cy = cy if cy is not None else ry + rh // 2
        t = table_ids[0]
        tw, th = lib.size(t)
        self.place(lib, t, cx, cy, surface=True)
        if sofa_ids:
            sw, sh = lib.size(sofa_ids[0])
            self.place(lib, sofa_ids[0], cx + (tw - sw) // 2, cy - sh - 1)
            if len(sofa_ids) > 1:
                self.place(lib, sofa_ids[1], cx + (tw - sw) // 2, cy + th + 1)
        for i, dx in enumerate((-3, tw + 1)):
            if i < len(chair_ids):
                self.place(lib, chair_ids[i], cx + dx, cy)
        # keep a lane to the cluster so it is always approachable
        self.aisle(cx - 1, cy - 1, tw + 2, 1)

    def scatter(self, lib, ids, room, tries=40, layer="furniture"):
        rx, ry, rw, rh = room
        n = 0
        for aid in ids:
            w, h = lib.size(aid)
            for _ in range(tries):
                x = self.rng.randrange(rx + 1, max(rx + 2, rx + rw - w))
                y = self.rng.randrange(ry + 2, max(ry + 3, ry + rh - h))
                if self.place(lib, aid, x, y, layer=layer):
                    n += 1
                    break
        return n

    # ---- output ----------------------------------------------------------
    def to_map(self, tile_px=32, background="#12131a"):
        def grid_layer(name, cells):
            pal, pi = [], {}
            grid = [[-1] * self.cols for _ in range(self.rows)]
            for (x, y), ref in cells.items():
                if not (0 <= x < self.cols and 0 <= y < self.rows):
                    continue
                if ref not in pi:
                    pi[ref] = len(pal); pal.append(ref)
                grid[y][x] = pi[ref]
            return {"name": name, "role": "terrain", "palette": pal, "grid": grid}

        layers = [grid_layer("floor", self.floor), grid_layer("walls", self.walls)]
        if self.overlay:
            layers.append({"name": "ground", "role": "objects",
                           "placements": [{"id": a, "at": [x, y]} for a, x, y in self.overlay]})
        layers.append({"name": "furniture", "role": "objects",
                       "placements": [{"id": a, "at": [x, y]} for a, x, y in self.furniture]})
        layers.append({"name": "props", "role": "objects",
                       "placements": [{"id": a, "at": [x, y]} for a, x, y in self.props]})
        # Collision is NOT the layout footprint. Layout reserves whole sprite
        # rectangles so furniture does not overlap; what blocks the player is the
        # part that meets the floor. Pixel boxes are rasterised to tiles, and a tile
        # only counts as solid when the box really covers it.
        COVER = 0.35
        cover = {}
        for (px, py, pw, ph) in self.blockers:
            for ty in range(max(0, py // 32), min(self.rows, (py + ph - 1) // 32 + 1)):
                for tx in range(max(0, px // 32), min(self.cols, (px + pw - 1) // 32 + 1)):
                    ox = max(0, min(px + pw, tx * 32 + 32) - max(px, tx * 32))
                    oy = max(0, min(py + ph, ty * 32 + 32) - max(py, ty * 32))
                    cover[(tx, ty)] = cover.get((tx, ty), 0) + ox * oy

        solid = {c for c, area in cover.items() if area >= COVER * 32 * 32}
        solid |= self.solid_tiles
        solid -= self.open_tiles          # doorways always stay walkable

        rects, run = [], None
        for (x, y) in sorted(solid, key=lambda p: (p[1], p[0])):
            if not (0 <= x < self.cols and 0 <= y < self.rows):
                continue
            if run and run[1] == y and run[0] + run[2] == x:
                run[2] += 1
            else:
                if run:
                    rects.append(run)
                run = [x, y, 1, 1]
        if run:
            rects.append(run)

        # spawn somewhere genuinely standable
        spawn = None
        for y in range(self.rows):
            for x in range(self.cols):
                if (x, y) not in solid and (x, y) in self.floor:
                    spawn = [x, y]
                    break
            if spawn:
                break

        return {"format": "worldbuilder-map/1", "tile": tile_px,
                "size": [self.cols, self.rows], "background": background,
                "layers": layers, "regions": [], "collisions": rects,
                "spawns": [{"name": "start", "at": spawn or [1, 1]}], "pois": []}
