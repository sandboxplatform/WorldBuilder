# WorldBuilder

A pixel-art map builder for the LimeZu asset packs: catalogue 14,024 assets, paint a
map with full control over layers and collision, walk it as a character, and export it
to another project.

Everything runs locally against your own copy of the packs. Nothing is uploaded.

## What's here

    catalog/     the asset index -- facets, labels, a controlled concept vocabulary,
                 and sheet_xy.json, which locates individual sprites inside sheets
    editor/      the map editor (plain HTML/JS, no build step)
    viewer/      a standalone walk-around viewer
    tools/       ~30 Python tools: catalogue builders, exporters, renderers, tests
    maps/        saved maps in the neutral format
    scenes/      programmatic scene generators
    labelling/   contact sheets and the labels derived from them

Design notes live in [ASSETS.md](ASSETS.md) (how the packs are built and addressed),
[FORMAT.md](FORMAT.md) (the neutral map format) and [RESEARCH.md](RESEARCH.md).

## Setup

Put your unzipped copies of the packs in `images/`, then:

```bash
python3 -m venv .venv && ./.venv/bin/pip install pillow numpy
./.venv/bin/python tools/build_catalog.py
./.venv/bin/python tools/build_editor_index.py
./.venv/bin/python tools/build_singles_index.py
./.venv/bin/python tools/build_thumbnails.py
```

## Run

```bash
python3 tools/serve.py 8823
```

Then open <http://127.0.0.1:8823/editor/>. The editor's own guide is in
[editor/README.md](editor/README.md).

## Tests

```bash
python3 tools/selftest.py
```

15 checks over the tools and data. The editor has its own 26 checks — load it, then in
the console:

```js
await import('./selftest.js').then(m => m.run())
```

## The packs

`images/` is excluded from the repo: it is 1 GB across 95k files, and two of the zips
exceed GitHub's 100 MB per-file limit. Buy the packs from
[LimeZu on itch.io](https://limezu.itch.io/), unzip them into `images/`, and the build
steps above regenerate every index from them.
