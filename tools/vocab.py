#!/usr/bin/env python3
"""
Build the controlled concept vocabulary.

Prompting only works if one word resolves to one set of assets. The packs' own
names give us ~1,100 raw concept strings, but they are inconsistent: compounds
(ground_floor_shop), adjectival tails (wall_flowered, greenhouse_structure_see_through),
plurals, and synonyms all describe the same things differently.

This derives a canonical list of concepts, each with the raw strings that map to it,
so both halves of the library -- names now, vision labels later -- land in one
vocabulary. The vision pass picks from this list rather than inventing terms.

    python tools/vocab.py                  # build catalog/vocab.json
    python tools/vocab.py --report         # coverage and what needs review
"""
import argparse, collections, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "catalog", "vocab.json")

# Tokens that are never the head noun: participles and adjectives that the packs
# tack onto the end of a name ("wall_flowered", "..._see_through").
ADJ_TAIL = {"through", "see", "flowered", "fenced", "benched", "covered", "broken",
            "painted", "damaged", "ruined", "stacked", "folded", "hanging", "floating",
            "closed", "opened", "lit", "modular", "single", "double", "triple",
            "inner", "outer", "upper", "lower", "front", "back", "side", "corner",
            "left", "right", "top", "bottom", "middle", "diagonal", "vertical",
            "horizontal", "small", "medium", "big", "large", "tall", "short", "long",
            "new", "old", "empty", "full", "dead", "cut", "dirty", "clean", "used",
            # animation-state suffixes on animated sheets, not nouns
            "idle", "loop", "turn", "animated", "frontal", "deep", "shallow"}

# Plural -> singular, only where the packs actually use both forms.
IRREGULAR = {"leaves": "leaf", "shelves": "shelf", "bushes": "bush",
             "benches": "bench", "boxes": "box", "crosses": "cross",
             "flowers": "flower", "candies": "candy", "berries": "berry"}
# words whose trailing "s" is part of the word, not a plural
NEVER_SINGULAR = {"stairs", "clothes", "grass", "glass", "moss", "props", "trees"}

# Broad classes, so the generator can reason about kinds of thing rather than
# 400 individual nouns. Keyed by canonical concept.
CLASSES = {
    "vegetation": {"tree", "grass", "bush", "flower", "sprout", "plant", "leaf",
                   "hedge", "palm", "cactus", "mushroom", "vine", "log", "trunk"},
    "terrain": {"sidewalk", "asphalt", "dirt", "sand", "water", "floor", "path",
                "road", "pavement", "tile", "ground", "snow", "mud", "gravel"},
    "structure": {"wall", "roof", "building", "house", "condo", "villa", "pillar",
                  "ceiling", "awning", "railing", "opening", "tower", "shed",
                  "fence", "door", "window", "stairs", "railing", "gate", "balcony",
                  "structure", "greenhouse", "shed", "pier", "bridge", "barrier"},
    "furniture": {"table", "chair", "bench", "seat", "sofa", "bed", "desk", "shelf",
                  "cabinet", "counter", "stool", "wardrobe", "drawer", "bookcase"},
    "vehicle": {"car", "truck", "bus", "train", "boat", "bike", "motorbike",
                "helicopter", "cart", "trailer", "van", "ambulance"},
    "lighting": {"light", "lamp", "candle", "lantern", "torch", "streetlight"},
    "container": {"box", "can", "bucket", "barrel", "crate", "bin", "dumpster",
                  "basket", "bag", "pot", "vase", "tank"},
    "signage": {"sign", "billboard", "poster", "graffiti", "banner", "flag", "arrow"},
    "decor": {"painting", "picture", "rug", "carpet", "curtain", "mirror", "clock",
              "statue", "trophy", "toy", "book", "shell", "rock", "stone"},
    "appliance": {"fridge", "oven", "stove", "sink", "microwave", "washer", "tv",
                  "computer", "monitor", "printer", "phone", "radio"},
    "premises": {"shop", "store", "market", "bakery", "gym", "butchery", "office",
                 "restaurant", "cafe", "bar", "pharmacy", "library", "school"},
    "water": {"pool", "fountain", "water", "sea", "lake", "pond", "wave"},
    "transport": {"rail", "binary", "track", "platform", "station", "stop"},
    "waste": {"trash", "trashbin", "dumpster", "bin", "pile", "garbage"},
    "memorial": {"grave", "tombstone", "coffin", "cross", "urn", "mausoleum"},
    "amenity": {"yard", "stage", "picnic", "entrance", "tube", "playground",
                "slide", "swing", "court", "pitch", "camp"},
    "tool": {"shovel", "hammer", "saw", "wrench", "axe", "rake", "broom", "ladder"},
    "equipment": {"stretcher", "wheelchair", "tank", "generator", "pump", "antenna"},
    "weapon": {"gun", "rifle", "pistol", "knife", "sword", "bomb"},
    "nature": {"rock", "stone", "mountain", "moss", "shell", "sand", "worm",
               "mushroom", "cliff", "hill"},
    "marine": {"buoy", "anchor", "net", "pier", "dock", "boat"},
    "effect": {"shadow", "bubble", "smoke", "steam", "spark", "splash"},
    "prop": {"mailbox", "umbrella", "tent", "ball", "balloon", "kite", "bag",
             "crate", "pot", "bucket", "barrel", "stick", "pole", "post"},
    "surface": {"panel", "shutter", "tile", "border", "edge", "trim"},
}
CONCEPT_CLASS = {c: k for k, v in CLASSES.items() for c in v}


def singular(word):
    if word in NEVER_SINGULAR:
        return word
    if word in IRREGULAR:
        return IRREGULAR[word]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


# Nouns that merely look like participles. Without these, "building" and "ceiling"
# get stripped as adjectival tails and the concept is lost.
ING_NOUNS = {"building", "ceiling", "awning", "railing", "painting", "fencing",
             "lighting", "clothing", "bedding", "siding", "roofing", "swing",
             "ring", "string", "spring", "sting", "wing", "king", "opening",
             "crossing", "parking", "seating", "shed", "bed", "weed", "seed",
             "shield", "field", "bird", "board"}


def head_of(concept):
    """The head noun of a concept string, skipping adjectival tails."""
    toks = [t for t in concept.split("_") if t]
    while toks and toks[-1] not in ING_NOUNS and (
            toks[-1] in ADJ_TAIL or toks[-1].endswith(("ed", "ing"))):
        toks.pop()
    if not toks:
        return None
    return singular(toks[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    fp = os.path.join(ROOT, "catalog", "facets.json")
    if not os.path.exists(fp):
        sys.exit("run tools/facets.py first")
    facets = json.load(open(fp))["assets"]

    entries = collections.defaultdict(lambda: {"aliases": collections.Counter(),
                                               "assets": 0})
    unresolved = collections.Counter()
    for aid, rec in facets.items():
        raw = rec["name_facets"].get("concept")
        if not raw:
            continue
        h = head_of(raw)
        if h is None:
            unresolved[raw] += 1
            continue
        e = entries[h]
        e["aliases"][raw] += 1
        e["assets"] += 1

    vocab = {}
    for concept, e in entries.items():
        vocab[concept] = {
            "concept": concept,
            "class": CONCEPT_CLASS.get(concept),
            "assets": e["assets"],
            "aliases": [k for k, _ in e["aliases"].most_common()],
        }

    ordered = sorted(vocab.values(), key=lambda v: -v["assets"])
    json.dump({"note": "Canonical concepts derived from pack filenames. The vision "
                       "pass selects from this list; add terms only when nothing fits.",
               "concepts": ordered,
               "unclassed": [v["concept"] for v in ordered if v["class"] is None]},
              open(a.out, "w"), indent=1)

    total = sum(v["assets"] for v in vocab.values())
    classed = sum(v["assets"] for v in vocab.values() if v["class"])
    print(f"{len(vocab)} canonical concepts covering {total} named assets")
    print(f"  -> {a.out}")
    print(f"  in a class: {classed} assets ({100*classed/max(total,1):.0f}%), "
          f"{sum(1 for v in vocab.values() if v['class'])} concepts")
    print(f"  no class yet: {sum(1 for v in vocab.values() if not v['class'])} concepts")
    if unresolved:
        print(f"  names with no head noun: {len(unresolved)} "
              f"(e.g. {list(unresolved)[:3]})")

    if a.report:
        cum, n = 0, 0
        for v in ordered:
            cum += v["assets"]
            n += 1
            if cum >= total * 0.8:
                break
        print(f"\ncoverage: the top {n} concepts cover 80% of named assets")
        print("\ntop concepts with no class assigned (need review):")
        for v in ordered:
            if not v["class"]:
                print(f"  {v['assets']:5d}  {v['concept']:<22s} e.g. {v['aliases'][0]}")
                n -= 1
                if n < -25:
                    break


if __name__ == "__main__":
    main()
