#!/usr/bin/env python3
"""
Check that a generated scene is actually usable.

A layout can look right and still be broken: a room sealed off by furniture, a
doorway blocked by a filing cabinet, a chair you can never reach. This flood-fills
from the spawn and reports what a player could never get to.

    python tools/validate_scene.py maps/office_floor.json
"""
import collections, json, sys


def main():
    m = json.load(open(sys.argv[1]))
    W, H = m["size"]
    solid = [[False] * W for _ in range(H)]
    for x, y, w, h in m["collisions"]:
        for j in range(h):
            for i in range(w):
                if 0 <= x + i < W and 0 <= y + j < H:
                    solid[y + j][x + i] = True

    floor = set()
    for L in m["layers"]:
        if L["role"] == "terrain" and L["name"] == "floor":
            for y, row in enumerate(L["grid"]):
                for x, v in enumerate(row):
                    if v != -1:
                        floor.add((x, y))

    walkable = {p for p in floor if not solid[p[1]][p[0]]}
    start = tuple(m["spawns"][0]["at"])
    if start not in walkable:
        print(f"FAIL: spawn {start} is not walkable")
        return 1

    seen = {start}
    q = collections.deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
            if (nx, ny) in walkable and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))

    stranded = walkable - seen
    print(f"floor tiles      : {len(floor)}")
    print(f"walkable         : {len(walkable)}  ({100*len(walkable)/max(1,len(floor)):.0f}% of floor)")
    print(f"reachable from spawn: {len(seen)}  ({100*len(seen)/max(1,len(walkable)):.0f}% of walkable)")

    if stranded:
        # group the unreachable pockets so the report is readable
        pockets, left = [], set(stranded)
        while left:
            s = left.pop()
            grp, q2 = {s}, collections.deque([s])
            while q2:
                x, y = q2.popleft()
                for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
                    if (nx, ny) in left:
                        left.discard((nx, ny)); grp.add((nx, ny)); q2.append((nx, ny))
            pockets.append(grp)
        pockets.sort(key=len, reverse=True)
        print(f"\nUNREACHABLE: {len(stranded)} tiles in {len(pockets)} pocket(s)")
        for g in pockets[:6]:
            xs = [p[0] for p in g]; ys = [p[1] for p in g]
            print(f"   {len(g):4d} tiles around ({min(xs)}-{max(xs)}, {min(ys)}-{max(ys)})")
        return 1

    print("\nevery walkable tile is reachable from the spawn")
    return 0


if __name__ == "__main__":
    sys.exit(main())
