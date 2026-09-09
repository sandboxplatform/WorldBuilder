#!/usr/bin/env python3
"""
Generate a multi-room office floor from the labelled catalog.

Rooms are described by what they are; every asset is resolved through the concept
vocabulary and the placement facets produced by the labelling pass.
"""
import json, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
from generate import Library, Scene   # noqa: E402

rng = random.Random(23)
lib = Library()
W, H = 48, 33
S = Scene(W, H, rng)

# Rooms abut so their walls are shared and the floor plan reads as one building.
OPEN   = (0, 0, 29, 18)
MEET   = (28, 0, 20, 11)
BREAK  = (28, 10, 20, 12)
WASH   = (0, 17, 14, 16)
LOUNGE = (13, 17, 16, 16)
RECEP  = (28, 21, 20, 12)

S.room(*OPEN,   wall="white",    floor="grey")
S.room(*MEET,   wall="stone",    floor="pale")
S.room(*BREAK,  wall="brick",    floor="wood")
S.room(*WASH,   wall="white",    floor="pale")
S.room(*LOUNGE, wall="lavender", floor="maroon")
S.room(*RECEP,  wall="stone",    floor="olive")

# Circulation first: aisles from every doorway, so the layout is built around how
# people move rather than furniture being scattered and a path hoped for.
def link(x, y, w, h):
    S.aisle(x, y, w, h)

# doorways between neighbours
S.door(28, 6, 1, 3, floor="pale")      # open office -> meeting
S.door(28, 15, 1, 3, floor="wood")     # open office -> break room
S.door(6, 17, 3, 2, floor="pale")      # open office -> washroom
S.door(20, 17, 3, 2, floor="maroon")   # open office -> lounge
S.door(13, 24, 1, 4, floor="maroon")   # washroom -> lounge
S.door(28, 25, 1, 4, floor="olive")    # lounge -> reception
S.door(29, 21, 4, 1, floor="olive")    # break room -> reception


def some(concept, n, **kw):
    opts = lib.find(concept, **kw)
    if not opts:
        print(f"  ! nothing for {concept} {kw}")
        return []
    rng.shuffle(opts)
    return (opts * (n // max(1, len(opts)) + 1))[:n]


def on_surfaces(spec):
    for concept, n, kw in spec:
        for aid in some(concept, n, **kw):
            S.place_on_surface(lib, aid)


def on_walls(room, spec):
    for concept, n, kw in spec:
        for aid in some(concept, n, **kw):
            S.place_on_wall(lib, aid, room)


# ------------------------------------------------- open-plan office
# A workstation is a multi-tile assembly, stamped from the sheet so its parts keep
# the composition the artist drew: partition panel over a footed rail, desk surface
# over a base rail, kit on the surface, chair tucked in front.
chairs = lib.find("office_chair")
deskware = (lib.find("monitor", theme="office", exclude_composite=True)
            + lib.find("laptop", theme="office")
            + lib.find("paperwork", theme="office")
            + lib.find("desk_lamp", theme="office")
            + lib.find("desk_accessory", theme="office"))
rng.shuffle(deskware)

pods, k = 0, 0
DESKS = [S.DESK_TAN, S.DESK_LILAC, S.DESK_TAN]
# cubicles sit shoulder to shoulder so the partitions read as one continuous wall
# a bay is 6 rows deep (partition 2, desk 2, chair 2); the open office interior is
# rows 2-17, so two bays fit and the last two rows stay clear for the cross aisle
# and the doors into the washroom and lounge
for by in (3, 10):
    x = 2
    while x + 3 <= OPEN[0] + OPEN[2] - 2:
        items = [deskware[(k * 3 + i) % len(deskware)] for i in range(3)]
        S.office_bay(lib, x, by, items, chair=chairs[k % len(chairs)],
                     desk=DESKS[k % len(DESKS)])
        pods += 1; k += 1
        x += 3
    S.aisle(1, by + 6, OPEN[2] - 2, 1)

S.along_wall(lib, some("filing_cabinet", 4), OPEN, side="bottom", gap=3)
S.along_wall(lib, some("plant", 4), OPEN, side="left", gap=4)
S.along_wall(lib, some("printer", 3, theme="office"), OPEN, side="right", gap=3)
on_walls(OPEN, [("painting", 5, {}), ("whiteboard", 3, {})])

# ----------------------------------------------------- meeting room
mdesks = [d for d in lib.find("desk", theme="conference_hall") if lib.size(d)[0] >= 2]
mchairs = some("chair", 8, theme="conference_hall")
S.table_run(lib, mdesks, mchairs, MEET, length=7)
S.along_wall(lib, some("plant", 3), MEET, side="right", gap=3)
S.along_wall(lib, some("filing_cabinet", 3), MEET, side="left", gap=2)
on_surfaces([("laptop", 5, {}), ("paperwork", 5, {})])
on_walls(MEET, [("projector_screen", 3, {}), ("banner", 4, {})])

# -------------------------------------------------------- break room
S.along_wall(lib, some("counter", 8, theme="kitchen"), BREAK, side="top", gap=0,
             surface=True)
S.along_wall(lib, some("fridge", 3, theme="kitchen"), BREAK, side="right", gap=1)
ktables = some("table", 8, theme="kitchen")
kchairs = some("chair", 8, theme="kitchen")
S.table_run(lib, ktables, kchairs, BREAK, length=6, cy_off=1)
S.along_wall(lib, some("plant", 3), BREAK, side="left", gap=3)
on_surfaces([("kettle", 3, {}), ("coffee_machine", 3, {}), ("cup", 6, {}),
             ("plate", 6, {}), ("sink", 2, {})])
on_walls(BREAK, [("cupboard", 5, {})])

# ------------------------------------------------------------ washroom
# toilets on a cubicle pitch, basins in a row opposite
S.cubicles(lib, some("toilet", 4), WASH, side="top", pitch=3)
S.along_wall(lib, some("washbasin", 4), WASH, side="bottom", gap=1)
S.along_wall(lib, some("laundry_basket", 3), WASH, side="right", gap=2)
S.along_wall(lib, some("shower", 4), WASH, side="left", gap=1)
S.cubicles(lib, some("washbasin", 3), WASH, side="bottom", pitch=3)
S.scatter(lib, some("plant", 2), WASH)
S.scatter(lib, some("cleaning_trolley", 1), WASH)
on_walls(WASH, [("mirror", 4, {}), ("towel_rail", 4, {})])

# -------------------------------------------------------------- lounge
S.along_wall(lib, some("sofa", 4, theme="living_room"), LOUNGE, side="top", gap=1)
S.along_wall(lib, some("armchair", 4, theme="living_room"), LOUNGE, side="bottom", gap=2)
S.along_wall(lib, some("plant", 4), LOUNGE, side="right", gap=3)
S.along_wall(lib, some("console_table", 2, theme="living_room"), LOUNGE, side="left",
             gap=4, surface=True)
S.seating_cluster(lib, some("console_table", 1, theme="living_room"),
                  some("sofa", 2, theme="living_room"),
                  some("armchair", 2, theme="living_room"), LOUNGE, cx=17, cy=26)
S.along_wall(lib, some("cabinet", 3, theme="living_room"), LOUNGE, side="bottom", gap=2)
S.along_wall(lib, some("lamp", 2, theme="living_room"), LOUNGE, side="right", gap=5)
on_surfaces([("lamp", 3, {"theme": "living_room"})])
on_walls(LOUNGE, [("painting", 5, {})])

# ----------------------------------------------------------- reception
S.along_wall(lib, some("desk", 4, theme="office"), RECEP, side="top", gap=1, surface=True)
S.along_wall(lib, some("sofa", 3, theme="living_room"), RECEP, side="bottom", gap=2)
S.along_wall(lib, some("plant", 4), RECEP, side="right", gap=3)
S.along_wall(lib, some("vending_machine", 2), RECEP, side="left", gap=2)
S.seating_cluster(lib, some("console_table", 1, theme="living_room"),
                  some("sofa", 2, theme="living_room"),
                  some("armchair", 2, theme="living_room"), RECEP, cx=38, cy=28)
S.scatter(lib, some("backpack", 3), RECEP)
S.along_wall(lib, some("filing_cabinet", 3), RECEP, side="bottom", gap=3)
on_surfaces([("monitor", 3, {"exclude_composite": True}), ("cup", 3, {})])
on_walls(RECEP, [("painting", 4, {}), ("banner", 3, {})])

out = os.path.join(os.path.dirname(HERE), "maps", "office_floor.json")
json.dump(S.to_map(), open(out, "w"), indent=1)
print(f"wrote {out}")
print(f"  {W}x{H} tiles | desk pods {pods} | furniture {len(S.furniture)} "
      f"| props {len(S.props)} | surfaces {len(S.surfaces)}")
