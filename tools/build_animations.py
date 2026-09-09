#!/usr/bin/env python3
"""
Work out the frame layout of every animated sheet.

The animated files are horizontal frame strips -- a door opening, a lamp flickering,
a shutter rolling -- meant to be played by stepping through the frames. Nothing in the
pack states the frame size, so it is recovered from the art: the alpha column profile
of a strip is periodic with the frame width, so autocorrelation finds it.

    python tools/build_animations.py
"""
import json, os
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "editor", "animations.json")
SIZE = "32"
T = 32


def frame_width(a):
    """Best frame width in pixels, or None if the strip does not look periodic."""
    alpha = (a[:, :, 3] > 0).sum(axis=0).astype(float)   # column profile
    W = len(alpha)
    if alpha.sum() == 0:
        return None, 0.0
    prof = (alpha - alpha.mean()).astype(np.float64)
    cands = []
    for fw in range(T, W // 2 + 1, T):
        if W % fw:
            continue
        n = W // fw
        blocks = prof[: n * fw].reshape(n, fw)
        ref = blocks.mean(axis=0)
        rn = float(np.linalg.norm(ref))
        bn = np.linalg.norm(blocks, axis=1)
        if rn < 1e-6 or (bn < 1e-6).any():
            continue
        score = float(((blocks @ ref) / (rn * bn)).mean())
        cands.append((fw, score))
    if not cands:
        return None, 0.0
    # Prefer the SMALLEST period that still explains the strip. Scoring alone favours
    # the largest window, because one big block is trivially similar to itself, which
    # made almost every strip look like a 2-frame animation.
    top = max(s for _fw, s in cands)
    for fw, score in cands:
        if score >= top - 0.02:
            return fw, score
    return cands[0]


def main():
    cat = json.load(open(os.path.join(ROOT, "catalog", "catalog.json")))
    base = os.path.join(ROOT, cat["root"])
    out = {}
    skipped = 0
    for e in cat["assets"]:
        if e["kind"] != "animated" or SIZE not in e["paths"]:
            continue
        w, h = e["px"][SIZE]
        if w % T or h % T or w < 2 * T:
            skipped += 1
            continue
        a = np.asarray(Image.open(os.path.join(base, e["paths"][SIZE])).convert("RGBA"))
        fw, score = frame_width(a)
        if not fw or score < 0.55:
            skipped += 1
            continue
        out[e["id"]] = {
            "image": f"{cat['root']}/{e['paths'][SIZE]}",
            "frame": [fw, h], "frames": w // fw,
            "tiles": [fw // T, h // T],
            "confidence": round(score, 3),
            "name": e["name"],
        }
    json.dump(out, open(OUT, "w"), indent=1)
    import collections
    c = collections.Counter(v["frames"] for v in out.values())
    print(f"{len(out)} animated sheets with a detected frame layout "
          f"({skipped} skipped as non-periodic or odd-sized)")
    print("  frame counts:", dict(sorted(c.items())[:12]))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
