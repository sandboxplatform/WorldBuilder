/* WorldBuilder map editor — paint tiles, control collision, place spawns, export. */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
/*
 * Tile layers paint into the grid; object layers hold whole sprites, which still
 * land ON the grid -- an object snaps by its own footprint, so a 1x3 lamp and a 3x2
 * desk both sit square in their cells even though they cover different areas.
 * Half-tile is available for the cases the art is drawn for; arbitrary pixel
 * placement is not, because it just produces a mess that will not line up with
 * anything modular.
 */
const DEFAULT_BG = "#12131a";   // "unset" -- such a map follows the editor theme
const LAYERS = [
  { name: "floor", role: "tiles" }, { name: "walls", role: "tiles" },
  { name: "ground", role: "tiles" }, { name: "furniture", role: "tiles" },
  { name: "objects", role: "tiles" }, { name: "overhead", role: "tiles" },
  { name: "props", role: "objects" },
];

const state = {
  tile: 32, zoom: 2, cam: { x: 0, y: 0 },
  sheets: {}, sheetsBySize: {}, sheet: null, img: new Map(),
  stamp: null,                       // {sheet, col, row, w, h}
  tool: "paint", showGrid: true, showColl: false, snap: 32, sel: null, nextGroup: 1, marquee: null,
  palMode: "sheets", singles: null, singleCat: null, singlePage: 0,
  clock: 0, animTimer: null, autoColl: true,
  layerIdx: 0, undo: [], redo: [], playing: false,
  chars: [], charId: null,
};

const M = {
  name: "untitled", tile: 32, size: [40, 30], background: DEFAULT_BG,
  layers: LAYERS.map(L => ({ name: L.name, role: L.role, visible: true,
                             grid: null, items: [] })),
  collision: new Set(), spawns: [],
  // manual decisions that beat the derived defaults: "x,y" -> true (solid) | false (free)
  overrides: new Map(),
};

/* ---------------------------------------------------------------- helpers */
const key = (x, y) => x + "," + y;
const toast = (m, ok = true) => {
  const t = $("#toast"); t.textContent = m;
  t.style.borderLeftColor = ok ? "var(--ok)" : "var(--danger)";
  t.classList.add("show"); clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), 2200);
};
function blankGrid(w, h) { return Array.from({ length: h }, () => new Array(w).fill(null)); }
function blankGroups(w, h) { return Array.from({ length: h }, () => new Array(w).fill(0)); }
function ensureGrids() {
  const [w, h] = M.size;
  for (const L of M.layers) {
    if (!L.role) L.role = "tiles";
    if (!L.items) L.items = [];
    if (L.role === "objects") continue;
    if (!L.grid) L.grid = blankGrid(w, h);
    if (!L.groups || L.groups.length !== L.grid.length) L.groups = blankGroups(w, h);
    if (L.grid.length !== h || L.grid[0].length !== w) {
      const g = blankGrid(w, h), gr = blankGroups(w, h);
      for (let y = 0; y < Math.min(h, L.grid.length); y++)
        for (let x = 0; x < Math.min(w, L.grid[0].length); x++) {
          g[y][x] = L.grid[y][x];
          gr[y][x] = L.groups?.[y]?.[x] || 0;
        }
      L.grid = g; L.groups = gr;
    }
  }
}
function imgFor(src) {
  if (!state.img.has(src)) {
    const i = new Image(); i.src = "/" + src;
    i.onload = () => draw();
    state.img.set(src, i);
  }
  return state.img.get(src);
}
function sheetOf(id) { return state.sheets[id]; }
function parseRef(ref) {
  const m = /^tile:([A-Za-z0-9_.]+)#(\d+),(\d+)$/.exec(ref || "");
  return m ? { id: m[1], col: +m[2], row: +m[3] } : null;
}
const makeRef = (id, c, r) => `tile:${id}#${c},${r}`;
const isSprite = ref => typeof ref === "string" && ref.startsWith("sprite:");
function spriteDef(ref) {
  const id = ref.slice(7);
  return state.singles?.byId?.[id] || null;
}

/* ------------------------------------------------------------------ undo */
function snapshot() {
  state.undo.push(JSON.stringify({
    layers: M.layers.map(L => ({ name: L.name, grid: L.grid, groups: L.groups,
                                 items: L.items })),
    collision: [...M.collision], overrides: [...M.overrides],
    spawns: M.spawns, size: M.size,
  }));
  if (state.undo.length > 60) state.undo.shift();
  state.redo.length = 0;
}
function restore(js) {
  const s = JSON.parse(js);
  M.size = s.size;
  s.layers.forEach((L, i) => { if (M.layers[i]) {
    M.layers[i].grid = L.grid; M.layers[i].groups = L.groups;
    M.layers[i].items = L.items || []; } });
  state.sel = null;
  M.collision = new Set(s.collision);
  M.overrides = new Map(s.overrides || []); M.spawns = s.spawns;
  ensureGrids(); draw(); renderLayers();
}
function undo() { if (!state.undo.length) return; state.redo.push(JSON.stringify({
    layers: M.layers.map(L => ({ name: L.name, grid: L.grid, groups: L.groups,
                                 items: L.items })),
    collision: [...M.collision], overrides: [...M.overrides],
    spawns: M.spawns, size: M.size }));
  restore(state.undo.pop()); }
function redo() { if (!state.redo.length) return; restore(state.redo.pop()); }

/* --------------------------------------------------------------- palette */
async function loadSheets() {
  const data = await fetch("sheets.json").then(r => r.json());
  state.sheetsBySize = data.sizes;
  fillSheetSelect();
}
// Full path in the option text, not just inside the optgroup: a closed <select>
// shows only the option, so trimming the group meant "police station" with no clue
// it was an exterior. Slight repetition when the list is open is the better trade.
function fullLabel(label, group) {
  const head = group.split(" · ")[0].toLowerCase();
  const short = { exteriors: "ext", interiors: "int", "modern office": "office",
                  "user interface": "ui" }[head] || head;
  return `${group} · ${label.replace(new RegExp(`^${short} · `), "")}`;
}
function optgroups(items, value, text) {
  const by = new Map();
  for (const it of items) {
    const g = it.group || "Other";
    if (!by.has(g)) by.set(g, []);
    by.get(g).push(it);
  }
  return [...by].map(([g, list]) =>
    `<optgroup label="${g}">` +
    list.map(it => `<option value="${value(it)}">${text(it, g)}</option>`).join("") +
    `</optgroup>`).join("");
}
function fillSheetSelect() {
  const list = state.sheetsBySize[String(state.tile)] || [];
  state.sheets = Object.fromEntries(list.map(s => [s.id, s]));
  $("#sheetSel").innerHTML = optgroups(list, s => s.id,
    (s, g) => fullLabel(s.label, g));
  if (list.length) selectSheet(list[0].id);
  loadThumbs().then(syncPickBtn);
}
function selectSheet(id) {
  state.sheet = sheetOf(id);
  $("#sheetSel").value = id;
  syncPickBtn();
  // start at the top of the new sheet: keeping the old scroll can leave you looking
  // at blank rows past the end of a shorter sheet
  const wrap = $("#palWrap");
  if (wrap) { wrap.scrollTop = 0; wrap.scrollLeft = 0; }
  $("#sheetInfo").textContent =
    `${state.sheet.group} · ${state.sheet.cols}×${state.sheet.rows} tiles`;
  drawPalette();
}
/*
 * The palette is virtualised: it draws only the slice you are scrolled to.
 * Some sheets are enormous -- the complete interiors sheet is 512x34048, which at
 * any zoom blows past the browser's canvas size limit and silently renders nothing.
 * A spacer div carries the scroll height; the canvas stays viewport-sized.
 */
function palZoom(s) { return s.cols > 40 ? 1 : 2; }
function drawPalette() {
  const s = state.sheet; if (!s || state.palMode !== "sheets") return;
  const wrap = $("#palWrap"), c = $("#pal"), sp = $("#palSpacer");
  const z = palZoom(s), t = state.tile * z;
  c._z = z;
  sp.style.width = s.cols * t + "px";
  sp.style.height = s.rows * t + "px";
  // clientHeight can still be 0 the first time this runs after a mode or sheet
  // switch, before layout settles; a ResizeObserver redraws once it is real
  const vw = Math.min(wrap.clientWidth || 240, s.cols * t);
  const vh = Math.min(wrap.clientHeight || 320, s.rows * t);
  if (c.width !== vw || c.height !== vh) { c.width = vw; c.height = vh; }
  const ox = wrap.scrollLeft, oy = wrap.scrollTop;
  c.style.marginLeft = ox + "px";
  c.style.marginTop = "0px";
  c.style.left = "0px";

  const x = c.getContext("2d"); x.imageSmoothingEnabled = false;
  x.clearRect(0, 0, c.width, c.height);
  const im = imgFor(s.image);
  if (im.complete && im.naturalWidth) {
    x.drawImage(im, ox / z, oy / z, vw / z, vh / z, 0, 0, vw, vh);
  } else {
    im.addEventListener("load", drawPalette, { once: true });
  }
  x.strokeStyle = cssVar("--grid");
  const c0 = Math.floor(ox / t), r0 = Math.floor(oy / t);
  for (let i = c0; i <= c0 + vw / t + 1; i++) {
    const px = i * t - ox; x.beginPath(); x.moveTo(px, 0); x.lineTo(px, vh); x.stroke(); }
  for (let j = r0; j <= r0 + vh / t + 1; j++) {
    const py = j * t - oy; x.beginPath(); x.moveTo(0, py); x.lineTo(vw, py); x.stroke(); }
  const st = state.stamp;
  if (st && st.sheet === s.id) {
    x.strokeStyle = "#ffc65c"; x.lineWidth = 2;
    x.strokeRect(st.col*t - ox + 1, st.row*t - oy + 1, st.w*t - 2, st.h*t - 2);
  }
  $("#palPage").textContent = `row ${r0}/${s.rows}`;
}
function drawStampPreview() {
  const c = $("#stamp"), x = c.getContext("2d");
  x.imageSmoothingEnabled = false; x.clearRect(0, 0, c.width, c.height);
  const st = state.stamp;
  if (!st) { $("#stampInfo").textContent = "none"; return; }
  if (st.sprite) {
    const im = imgFor(st.image);
    const a = state.singles?.byId?.[st.sprite];
    if (im.complete) {
      const fw = a?.anim ? a.anim.frame[0] : im.naturalWidth;
      const fh = a?.anim ? a.anim.frame[1] : im.naturalHeight;
      const k = Math.max(1, Math.floor(Math.min(96/fw, 96/fh)));
      x.drawImage(im, 0, 0, fw, fh, 0, 0, fw*k, fh*k);
    } else im.addEventListener("load", drawStampPreview, { once: true });
    $("#stampInfo").textContent = a?.anim
      ? `${st.w}×${st.h} · ${a.anim.frames} frames` : `${st.w}×${st.h} sprite`;
    return;
  }
  const s = sheetOf(st.sheet), im = imgFor(s.image), T = state.tile;
  const z = Math.max(1, Math.floor(Math.min(96 / (st.w * T), 96 / (st.h * T))));
  if (im.complete)
    x.drawImage(im, st.col*T, st.row*T, st.w*T, st.h*T, 0, 0, st.w*T*z, st.h*T*z);
  $("#stampInfo").textContent = `${st.w}×${st.h} @ ${st.col},${st.row}`;
}

/* ------------------------------------------------- singles (sprite) browser */
/*
 * Not every asset lives in a sheet. 2,141 of the pre-cut singles are pre-composed
 * variants -- a table with a coffee machine on it, a counter with an open drawer --
 * that appear nowhere as a contiguous block in any sheet. They can only be painted
 * as whole sprites, so the palette has a second mode that browses them directly.
 */
const SINGLE_COLS = 6, SINGLE_CELL = 40, SINGLE_PAGE = 90;

async function loadSingles() {
  if (state.singles) return state.singles;
  state.singles = await fetch("singles.json").then(r => r.json());
  const sel = $("#sheetSel");
  state.singleCat = state.singleCat || Object.keys(state.singles.cats)[0];
  return state.singles;
}
function fillSingleSelect() {
  const groups = state.singles.groups || {};
  const items = Object.keys(state.singles.cats).map(c => ({
    key: c, group: groups[c] || "Other",
    // the group carries the pack and kind, so show just the theme
    name: c.split(".").slice(2).join(" ").replace(/_/g, " "),
    n: state.singles.cats[c].length,
  })).sort((a, b) => a.group.localeCompare(b.group) || a.name.localeCompare(b.name));
  $("#sheetSel").innerHTML = optgroups(items, i => i.key,
    i => `${i.group} · ${i.name} (${i.n})`);
  $("#sheetSel").value = state.singleCat;
  if (!$("#sheetSel").value && items.length) {
    state.singleCat = items[0].key; $("#sheetSel").value = state.singleCat;
  }
  loadThumbs().then(syncPickBtn);
}
function singleList() { return (state.singles?.cats[state.singleCat]) || []; }
function drawSingles() {
  const list = singleList();
  const wrap = $("#palWrap"), c = $("#pal"), sp = $("#palSpacer");
  const rows = Math.ceil(list.length / SINGLE_COLS);
  sp.style.width = SINGLE_COLS * SINGLE_CELL + "px";
  sp.style.height = rows * SINGLE_CELL + "px";
  const vw = Math.min(wrap.clientWidth || 240, SINGLE_COLS * SINGLE_CELL);
  const vh = wrap.clientHeight || 320;
  if (c.width !== vw || c.height !== vh) { c.width = vw; c.height = vh; }
  c.style.marginLeft = "0px";
  const oy = wrap.scrollTop;
  const x = c.getContext("2d"); x.imageSmoothingEnabled = false;
  x.clearRect(0, 0, vw, vh);
  const r0 = Math.floor(oy / SINGLE_CELL), r1 = r0 + Math.ceil(vh / SINGLE_CELL) + 1;
  for (let r = r0; r <= r1; r++) for (let cc = 0; cc < SINGLE_COLS; cc++) {
    const i = r * SINGLE_COLS + cc; if (i >= list.length) break;
    const a = list[i], im = imgFor(a.image);
    const px = cc * SINGLE_CELL, py = r * SINGLE_CELL - oy;
    x.strokeStyle = cssVar("--grid"); x.strokeRect(px + .5, py + .5, SINGLE_CELL - 1, SINGLE_CELL - 1);
    if (im.complete && im.naturalWidth) {
      const fw = a.anim ? a.anim.frame[0] : im.naturalWidth;
      const fh = a.anim ? a.anim.frame[1] : im.naturalHeight;
      const k = Math.min((SINGLE_CELL - 6) / fw, (SINGLE_CELL - 6) / fh, 2);
      x.drawImage(im, 0, 0, fw, fh,
                  px + (SINGLE_CELL - fw*k)/2, py + SINGLE_CELL - 3 - fh*k, fw*k, fh*k);
      if (a.anim) { x.fillStyle = "#6aa9ff"; x.fillRect(px+2, py+2, 4, 4); }
    } else im.addEventListener("load", drawSingles, { once: true });
    if (state.stamp?.sprite === a.id) {
      x.strokeStyle = "#ffc65c"; x.lineWidth = 2; x.strokeRect(px+1, py+1, SINGLE_CELL-2, SINGLE_CELL-2);
    }
  }
  $("#palPage").textContent = `${list.length} sprites`;
}
function pickSingle(ev) {
  const wrap = $("#palWrap"), b = $("#pal").getBoundingClientRect();
  const cc = Math.floor((ev.clientX - b.left) / SINGLE_CELL);
  const r = Math.floor((ev.clientY - b.top + wrap.scrollTop) / SINGLE_CELL);
  const a = singleList()[r * SINGLE_COLS + cc];
  if (!a) return;
  state.stamp = { sprite: a.id, w: a.tiles[0], h: a.tiles[1], image: a.image };
  drawSingles(); drawStampPreview();
}
async function setPalMode(mode) {
  state.palMode = mode;
  $("#modeSheets").classList.toggle("on", mode === "sheets");
  $("#modeSingles").classList.toggle("on", mode === "singles");
  $("#palWrap").scrollTop = 0;
  if (mode === "singles") {
    await loadSingles(); fillSingleSelect();
    const g = state.singles.groups?.[state.singleCat] || "";
    $("#sheetInfo").textContent = `${g} · whole sprites`;
    drawSingles();
  } else { fillSheetSelect(); drawPalette(); }
}

/* ------------------------------------------------------------------ draw */
function draw() {
  const cv = $("#map"), ctx = cv.getContext("2d");
  const stage = $("#stage");
  cv.width = stage.clientWidth; cv.height = stage.clientHeight;
  ctx.imageSmoothingEnabled = false;
  let anyAnim = false;
  const T = state.tile, Z = state.zoom, S = T * Z;
  const [W, H] = M.size;
  const ox = -state.cam.x, oy = -state.cam.y;
  // Outside the map is the editor's own backdrop, not the map's background: the
  // two were the same colour until light mode made the difference obvious.
  ctx.fillStyle = cssVar("--void"); ctx.fillRect(0, 0, cv.width, cv.height);
  // A map that has never been given its own background follows the theme; one that
  // carries a deliberate colour keeps it, in either theme.
  ctx.fillStyle = M.background === DEFAULT_BG ? cssVar("--canvas") : M.background;
  ctx.fillRect(ox, oy, W * S, H * S);

  // "overhead" means drawn above the character -- treetops, ceiling fixtures, the
  // upper courses of a wall. Held back until after the player, otherwise the layer
  // has no purpose that its position in the list does not already serve.
  const held = [];
  for (const L of M.layers) {
    if (!L.visible) continue;
    if (state.playing && L.name === "overhead") { held.push(L); continue; }
    if (L.role === "objects") {
      for (const it of L.items) {
        const a = spriteDef("sprite:" + it.id) || state.singles?.byId?.[it.id];
        if (!a) continue;
        const im = imgFor(a.image); if (!im.complete) continue;
        if (a.anim) {
          const [fw, fh] = a.anim.frame;
          const f = Math.floor(state.clock / 140) % a.anim.frames;
          ctx.drawImage(im, f*fw, 0, fw, fh, ox + it.x*Z, oy + it.y*Z, fw*Z, fh*Z);
          anyAnim = true;
        } else {
          ctx.drawImage(im, ox + it.x*Z - a.bbox[0]*Z, oy + it.y*Z - a.bbox[1]*Z,
                        im.naturalWidth*Z, im.naturalHeight*Z);
        }
        if (state.sel === it) {
          ctx.strokeStyle = "#ffc65c"; ctx.lineWidth = 2;
          ctx.strokeRect(ox + it.x*Z - 1, oy + it.y*Z - 1,
                         (a.bbox[2] || T)*Z + 2, (a.bbox[3] || T)*Z + 2);
        }
      }
      continue;
    }
    if (!L.grid) continue;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const ref = L.grid[y][x]; if (!ref) continue;
      if (isSprite(ref)) {
        const a = spriteDef(ref); if (!a) continue;
        const im = imgFor(a.image); if (!im.complete) continue;
        if (a.anim) {
          // frame strips play by stepping along the sheet; draw the current frame
          const [fw, fh] = a.anim.frame;
          const f = Math.floor(state.clock / 140) % a.anim.frames;
          ctx.drawImage(im, f*fw, 0, fw, fh, ox + x*S, oy + y*S, fw*Z, fh*Z);
          anyAnim = true;
          continue;
        }
        // content-aligned: the sprite's content lands on the cell it was placed on,
        // which is exactly how the exporter slices it
        ctx.drawImage(im, ox + x*S - a.bbox[0]*Z, oy + y*S - a.bbox[1]*Z,
                      im.naturalWidth*Z, im.naturalHeight*Z);
        continue;
      }
      const r = parseRef(ref); if (!r) continue;
      const sh = sheetOf(r.id); if (!sh) continue;
      const im = imgFor(sh.image); if (!im.complete) continue;
      ctx.drawImage(im, r.col*T, r.row*T, T, T, ox + x*S, oy + y*S, S, S);
    }
  }
  if (state.showGrid) {
    // crisp 1px lines: offset by .5 so they land on a pixel instead of straddling two
    ctx.lineWidth = 1;
    // read once, not per line: getComputedStyle inside the loop costs a reflow each
    const minor = cssVar("--gridMinor"), major = cssVar("--gridMajor");
    for (let x = 0; x <= W; x++) {
      const gx = Math.round(ox + x*S) + .5;
      ctx.strokeStyle = x % 8 ? minor : major;
      ctx.beginPath(); ctx.moveTo(gx, oy); ctx.lineTo(gx, oy + H*S); ctx.stroke();
    }
    for (let y = 0; y <= H; y++) {
      const gy = Math.round(oy + y*S) + .5;
      ctx.strokeStyle = y % 8 ? minor : major;
      ctx.beginPath(); ctx.moveTo(ox, gy); ctx.lineTo(ox + W*S, gy); ctx.stroke();
    }
  }
  if (state.showColl) {
    ctx.fillStyle = "rgba(255,70,120,.42)";
    for (const k of M.collision) { const [x,y] = k.split(",").map(Number);
      ctx.fillRect(ox + x*S, oy + y*S, S, S); }
  }
  ctx.strokeStyle = cssVar("--mapEdge"); ctx.lineWidth = 2;
  ctx.strokeRect(ox - 1, oy - 1, W*S + 2, H*S + 2);
  const r = selRect();
  if (r) {
    // dim everything outside the selection: while one is active it masks editing,
    // so it needs to look like a mask rather than a highlight
    const sx = ox + r.x0*S, sy = oy + r.y0*S;
    const sw = (r.x1 - r.x0 + 1) * S, sh = (r.y1 - r.y0 + 1) * S;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, cv.width, cv.height);
    ctx.rect(sx, sy, sw, sh);
    ctx.fillStyle = "rgba(8,9,13,.55)";
    ctx.fill("evenodd");
    ctx.restore();
    ctx.strokeStyle = "#ffc65c"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
    ctx.strokeRect(sx, sy, sw, sh);
    ctx.setLineDash([]);
  }
  for (const sp of M.spawns) {
    ctx.fillStyle = "#6ade9a";
    ctx.fillRect(ox + sp.at[0]*S + S*.25, oy + sp.at[1]*S + S*.25, S*.5, S*.5);
  }
  drawSizing(ctx, ox, oy, S);
  if (state.playing) {
    drawPlayer(ctx, ox, oy, S);
    for (const L of held) {
      if (!L.grid) continue;
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const r = parseRef(L.grid[y][x]); if (!r) continue;
        const sh = sheetOf(r.id); if (!sh) continue;
        const im = imgFor(sh.image); if (!im.complete) continue;
        ctx.drawImage(im, r.col*T, r.row*T, T, T, ox + x*S, oy + y*S, S, S);
      }
    }
  }
  // keep a slow repaint going only while something on the map is animating
  if (anyAnim && !state.animTimer) {
    state.animTimer = setInterval(() => { state.clock += 140; draw(); }, 140);
  } else if (!anyAnim && state.animTimer) {
    clearInterval(state.animTimer); state.animTimer = null;
  }
  $("#mapInfo").textContent = `${W}×${H} @ ${T}px · ${M.collision.size} solid`;
  const badge = $("#selBadge");
  if (badge) {
    badge.hidden = !r;
    if (r) badge.textContent = `masked ${r.x1-r.x0+1}×${r.y1-r.y0+1} ✕`;
  }
}

/* ------------------------------------------------------------ map editing */
function cellAt(ev) {
  const cv = $("#map"), b = cv.getBoundingClientRect(), S = state.tile * state.zoom;
  return { x: Math.floor((ev.clientX - b.left + state.cam.x) / S),
           y: Math.floor((ev.clientY - b.top + state.cam.y) / S) };
}
function pixelAt(ev, snap = true) {
  const cv = $("#map"), b = cv.getBoundingClientRect(), Z = state.zoom;
  const px = (ev.clientX - b.left + state.cam.x) / Z;
  const py = (ev.clientY - b.top + state.cam.y) / Z;
  if (!snap) return { x: px, y: py };
  const s = state.snap;
  return { x: Math.floor(px / s) * s, y: Math.floor(py / s) * s };
}
// An object occupies whole cells: snap its top-left to the grid so a 1x3 and a 3x2
// both sit square, whatever area they cover.
function snapObj(v) { return Math.round(v / state.snap) * state.snap; }
function objLayer() { return M.layers[state.layerIdx]?.role === "objects"
  ? M.layers[state.layerIdx]
  : M.layers.find(L => L.role === "objects"); }
function hitObject(px, py) {
  const L = objLayer(); if (!L) return null;
  for (let i = L.items.length - 1; i >= 0; i--) {
    const it = L.items[i];
    const a = state.singles?.byId?.[it.id]; if (!a) continue;
    const w = a.anim ? a.anim.frame[0] : a.bbox[2];
    const h = a.anim ? a.anim.frame[1] : a.bbox[3];
    if (px >= it.x && py >= it.y && px < it.x + w && py < it.y + h) return { L, it, i };
  }
  return null;
}
function inBounds(x, y) { return x >= 0 && y >= 0 && x < M.size[0] && y < M.size[1]; }

/*
 * An active marquee is a mask, not just a highlight: while one is up, editing is
 * confined to it. That is what lets you fill a specific area -- flood fill a room,
 * drop furniture into an alcove -- without anything spilling over the edge.
 */
function selRect() {
  const mq = state.marquee; if (!mq) return null;
  return { x0: Math.min(mq.x0, mq.x1), x1: Math.max(mq.x0, mq.x1),
           y0: Math.min(mq.y0, mq.y1), y1: Math.max(mq.y0, mq.y1) };
}
function inSel(x, y) {
  const r = selRect(); if (!r) return true;
  return x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
}
function editable(x, y) { return inBounds(x, y) && inSel(x, y); }
// an object must fit entirely inside the selection, measured by its own footprint
function objFits(x, y, w, h) {
  const r = selRect(); if (!r) return true;
  const T = M.tile;
  return Math.floor(x / T) >= r.x0 && Math.floor(y / T) >= r.y0
      && Math.floor((x + w - 1) / T) <= r.x1 && Math.floor((y + h - 1) / T) <= r.y1;
}
function objSize(id) {
  const a = state.singles?.byId?.[id];
  if (!a) return [M.tile, M.tile];
  return a.anim ? [a.anim.frame[0], a.anim.frame[1]] : [a.bbox[2], a.bbox[3]];
}

function applyStamp(x, y) {
  const st = state.stamp; if (!st) return;
  const L = M.layers[state.layerIdx];
  if (st.sprite) return;                 // sprites go through placeSprite()
  // A multi-tile stamp is one object: remember which cells came from it so erasing
  // any of them takes the whole thing, rather than punching a hole in a desk.
  const gid = (st.w * st.h > 1) ? state.nextGroup++ : 0;
  for (let dy = 0; dy < st.h; dy++) for (let dx = 0; dx < st.w; dx++) {
    const tx = x + dx, ty = y + dy;
    if (editable(tx, ty)) {
      L.grid[ty][tx] = makeRef(st.sheet, st.col + dx, st.row + dy);
      L.groups[ty][tx] = gid;
    }
  }
}
function eraseAt(x, y) {
  const L = M.layers[state.layerIdx];
  if (!L || L.role === "objects" || !editable(x, y)) return;
  const gid = L.groups?.[y]?.[x] || 0;
  if (!gid) { L.grid[y][x] = null; return; }
  // clear every cell that came from the same stamp
  for (let yy = 0; yy < M.size[1]; yy++)
    for (let xx = 0; xx < M.size[0]; xx++)
      if (L.groups[yy][xx] === gid) { L.grid[yy][xx] = null; L.groups[yy][xx] = 0; }
}
function eraseObjectAt(ev) {
  const b = $("#map").getBoundingClientRect(), Z = state.zoom;
  const px = (ev.clientX - b.left + state.cam.x) / Z;
  const py = (ev.clientY - b.top + state.cam.y) / Z;
  const hit = hitObject(px, py);
  if (!hit) return false;
  hit.L.items.splice(hit.i, 1);
  if (state.sel === hit.it) state.sel = null;
  return true;
}
function floodFill(x, y) {
  const L = M.layers[state.layerIdx], target = L.grid[y][x];
  const st = state.stamp; if (!st) return;
  const rep = makeRef(st.sheet, st.col, st.row);
  if (target === rep) return;
  const q = [[x, y]], seen = new Set();
  while (q.length) {
    const [cx, cy] = q.pop(); const k = key(cx, cy);
    if (!editable(cx, cy) || seen.has(k) || L.grid[cy][cx] !== target) continue;
    seen.add(k); L.grid[cy][cx] = rep;
    q.push([cx+1,cy],[cx-1,cy],[cx,cy+1],[cx,cy-1]);
  }
}
function pickAt(x, y) {
  for (let i = M.layers.length - 1; i >= 0; i--) {
    const r = parseRef(M.layers[i].grid?.[y]?.[x]);
    if (r) { state.layerIdx = i; selectSheet(r.id);
      state.stamp = { sheet: r.id, col: r.col, row: r.row, w: 1, h: 1 };
      drawPalette(); drawStampPreview(); renderLayers(); return; }
  }
}

let drag = null;
function onMapDown(ev) {
  if (state.playing) return;
  const c = cellAt(ev);
  if (state.sizing) { state.sizing.from = c; state.sizing.to = c;
                      drag = { sizing: true }; draw(); return; }
  if (ev.altKey) { pickAt(c.x, c.y); return; }
  const t = state.tool;
  if (t === "pan") { drag = { pan: true, sx: ev.clientX, sy: ev.clientY,
                              cx: state.cam.x, cy: state.cam.y }; return; }

  if (t === "select") {
    // click an object to grab it; click empty space to start a marquee
    const b = $("#map").getBoundingClientRect(), Z = state.zoom;
    const px = (ev.clientX - b.left + state.cam.x) / Z;
    const py = (ev.clientY - b.top + state.cam.y) / Z;
    const hit = hitObject(px, py);
    if (hit) {
      state.marquee = null; state.sel = hit.it;
      snapshot();
      const p = pixelAt(ev, false);
      drag = { obj: hit.it, dx: hit.it.x - p.x, dy: hit.it.y - p.y };
      draw(); return;
    }
    const c0 = cellAt(ev);
    state.sel = null;
    state.marquee = { x0: c0.x, y0: c0.y, x1: c0.x, y1: c0.y };
    drag = { marquee: true }; draw(); return;
  }

  if (t === "erase") {
    // an object layer has no grid: take the whole sprite under the cursor
    if (M.layers[state.layerIdx]?.role === "objects") {
      snapshot(); eraseObjectAt(ev); drag = { erasingObjects: true }; draw(); return;
    }
  }

  // objects: select and drag, or drop a new one
  if (t === "move" || (t === "paint" && state.stamp?.sprite)) {
    const p = pixelAt(ev);
    const hit = hitObject((ev.clientX - $("#map").getBoundingClientRect().left
                           + state.cam.x) / state.zoom,
                          (ev.clientY - $("#map").getBoundingClientRect().top
                           + state.cam.y) / state.zoom);
    if (t === "move") {
      state.sel = hit ? hit.it : null;
      if (hit) { snapshot(); drag = { obj: hit.it, dx: hit.it.x - p.x, dy: hit.it.y - p.y }; }
      draw(); return;
    }
    snapshot();
    const L = objLayer();
    if (!L) { toast("add an object layer first", false); return; }
    const [w, h] = objSize(state.stamp.sprite);
    // drop it into the cell under the cursor, aligned by its own footprint
    const it = { id: state.stamp.sprite, x: snapObj(p.x), y: snapObj(p.y) };
    if (!objFits(it.x, it.y, w, h)) {
      toast("does not fit in the selection", false); drag = null; return;
    }
    L.items.push(it); state.sel = it;
    drag = { obj: it, dx: 0, dy: 0 };
    draw(); return;
  }
  // A live selection masks editing. Silently ignoring clicks outside it is the one
  // thing that makes the editor feel broken, so say what is happening -- but only
  // for point tools. A rect drag may start outside and still overlap the mask, so
  // it is allowed through and clipped per cell.
  if (selRect() && !inSel(c.x, c.y) && t !== "rect") {
    toast("outside the selection — esc to clear", false);
    return;
  }
  snapshot();
  if (t === "rect") { drag = { rect: true, from: c, to: c }; draw(); return; }
  drag = { paint: true };
  applyTool(c.x, c.y);
  draw();
}
function applyTool(x, y) {
  switch (state.tool) {
    case "paint": applyStamp(x, y); break;
    case "erase": eraseAt(x, y); break;
    case "fill": if (inBounds(x, y)) floodFill(x, y); break;
    case "pick": pickAt(x, y); break;
    case "coll+": if (editable(x, y)) { M.collision.add(key(x, y));
                                        M.overrides.set(key(x, y), true); } break;
    case "coll-": M.collision.delete(key(x, y)); M.overrides.set(key(x, y), false); break;
    case "spawn": if (editable(x, y)) M.spawns = [{ name: "start", at: [x, y] }]; break;
  }
}
function onMapMove(ev) {
  const c = cellAt(ev);
  const r0 = selRect();
  $("#status").textContent = `${c.x},${c.y}`
    + (state.stamp ? `  stamp ${state.stamp.w}×${state.stamp.h}` : "")
    + (r0 ? `  · masked to ${r0.x1-r0.x0+1}×${r0.y1-r0.y0+1}  (esc to clear)` : "");
  if (!drag) return;
  if (drag.pan) {
    state.cam.x = drag.cx - (ev.clientX - drag.sx);
    state.cam.y = drag.cy - (ev.clientY - drag.sy);
    draw(); return;
  }
  if (drag.sizing) { state.sizing.to = cellAt(ev); draw(); return; }
  if (drag.marquee) { const c2 = cellAt(ev);
    state.marquee.x1 = c2.x; state.marquee.y1 = c2.y; draw(); return; }
  if (drag.erasingObjects) { eraseObjectAt(ev); draw(); return; }
  if (drag.obj) { const p = pixelAt(ev, false);
    const nx = snapObj(p.x + drag.dx), ny = snapObj(p.y + drag.dy);
    const [ow, oh] = objSize(drag.obj.id);
    if (objFits(nx, ny, ow, oh)) { drag.obj.x = nx; drag.obj.y = ny; }
    draw(); return; }
  if (drag.rect) { drag.to = c; draw(); previewRect(drag); return; }
  applyTool(c.x, c.y); draw();
}
function previewRect(d) {
  const ctx = $("#map").getContext("2d"), S = state.tile * state.zoom;
  const x0 = Math.min(d.from.x, d.to.x), x1 = Math.max(d.from.x, d.to.x);
  const y0 = Math.min(d.from.y, d.to.y), y1 = Math.max(d.from.y, d.to.y);
  ctx.strokeStyle = "#ffc65c"; ctx.lineWidth = 2;
  ctx.strokeRect(-state.cam.x + x0*S, -state.cam.y + y0*S, (x1-x0+1)*S, (y1-y0+1)*S);
}
function onMapUp() {
  if (drag && drag.sizing) {
    const z = state.sizing;
    const w = Math.abs(z.to.x - z.from.x) + 1, h = Math.abs(z.to.y - z.from.y) + 1;
    state.sizing = null; drag = null;
    if (w >= 4 && h >= 4) { newMap(w, h); toast(`new map ${w}×${h}`); }
    else toast("too small — drag out at least 4×4", false);
    return;
  }
  const wasEditing = drag && !drag.pan && !drag.marquee;
  if (drag && drag.marquee) {
    const mq = state.marquee;
    if (mq && mq.x0 === mq.x1 && mq.y0 === mq.y1) state.marquee = null;
  }
  if (drag && drag.rect) {
    const d = drag;
    const x0 = Math.min(d.from.x, d.to.x), x1 = Math.max(d.from.x, d.to.x);
    const y0 = Math.min(d.from.y, d.to.y), y1 = Math.max(d.from.y, d.to.y);
    const st = state.stamp;
    if (st && !st.sprite) {
      const L = M.layers[state.layerIdx];
      const multi = st.w * st.h > 1;
      // a click without a drag means "place one stamp", not "one cell of a stamp"
      if (multi && d.from.x === d.to.x && d.from.y === d.to.y) {
        applyStamp(d.from.x, d.from.y);
        drag = null; recomputeCollision(); draw(); return;
      }
      for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
        if (!editable(x, y)) continue;
        L.grid[y][x] = makeRef(st.sheet, st.col + ((x - x0) % st.w),
                                        st.row + ((y - y0) % st.h));
        // one group per repetition of the stamp, so erase still lifts a whole block
        L.groups[y][x] = multi
          ? 1 + state.nextGroup + Math.floor((y - y0) / st.h) * 4096
              + Math.floor((x - x0) / st.w)
          : 0;
      }
      if (multi) state.nextGroup += 4096 * (Math.floor((y1 - y0) / st.h) + 2);
      // a rect wholly outside the mask paints nothing: say so rather than no-op
      const r = selRect();
      if (r && (x1 < r.x0 || x0 > r.x1 || y1 < r.y0 || y0 > r.y1))
        toast("outside the selection — esc to clear", false);
    }
  }
  drag = null;
  if (wasEditing && !["coll+", "coll-"].includes(state.tool)) recomputeCollision();
  draw();
}

/* ----------------------------------------------------------------- layers */
function renderLayers() {
  $("#layers").innerHTML = M.layers.map((L, i) => `
    <div class="layer ${i === state.layerIdx ? "sel" : ""}" data-i="${i}">
      <input type="checkbox" ${L.visible ? "checked" : ""} data-vis="${i}">
      <span>${L.name}</span>
      <small style="color:var(--dim)">${L.role === "objects" ? "obj" : ""}</small>
    </div>`).join("");
  $$("#layers .layer").forEach(el => el.onclick = e => {
    if (e.target.dataset.vis !== undefined) return;
    state.layerIdx = +el.dataset.i; renderLayers(); });
  $$("#layers input").forEach(el => el.onchange = () => {
    M.layers[+el.dataset.vis].visible = el.checked; draw(); });
}

/* ------------------------------------------------------- save / load / new */
function serialise() {
  const layers = [];
  for (const L of M.layers) {
    if (L.role === "objects") {
      if (!L.items.length) continue;
      // tile position plus a pixel offset inside it: keeps the format readable and
      // backwards compatible (no "off" means tile-aligned, as before)
      layers.push({ name: L.name, role: "objects", units: "px",
        placements: L.items.map(it => {
          const tx = Math.floor(it.x / M.tile), ty = Math.floor(it.y / M.tile);
          const ox = it.x - tx * M.tile, oy = it.y - ty * M.tile;
          const p = { id: it.id, at: [tx, ty] };
          if (ox || oy) p.off = [ox, oy];
          return p;
        }) });
      continue;
    }
    const pal = [], pi = new Map();
    const grid = L.grid.map(row => row.map(ref => {
      if (!ref) return -1;
      if (!pi.has(ref)) { pi.set(ref, pal.length); pal.push(ref); }
      return pi.get(ref);
    }));
    if (pal.length) {
      const out = { name: L.name, role: "terrain", palette: pal, grid };
      // stamp grouping is an editing aid, not art: renderers ignore it, but keeping
      // it means a reopened map still erases multi-tile objects as one piece
      if (L.groups?.some(r => r.some(v => v))) out.groups = L.groups;
      layers.push(out);
    }
  }
  const runs = []; let run = null;
  [...M.collision].map(k => k.split(",").map(Number))
    .sort((a, b) => a[1] - b[1] || a[0] - b[0])
    .forEach(([x, y]) => {
      if (run && run[1] === y && run[0] + run[2] === x) run[2]++;
      else { if (run) runs.push(run); run = [x, y, 1, 1]; }
    });
  if (run) runs.push(run);
  const out = { format: "worldbuilder-map/1", tile: M.tile, size: M.size,
                background: M.background, layers, regions: [], collisions: runs,
                spawns: M.spawns, pois: [], character: state.charId || null };
  // your manual collision decisions, so reopening does not silently re-derive them
  if (M.overrides.size) out.collisionOverrides = [...M.overrides];
  if (!state.autoColl) out.collisionAuto = false;
  return out;
}
function deserialise(d) {
  M.tile = d.tile; state.tile = d.tile; $("#tileSize").value = d.tile;
  fillSheetSelect();
  M.size = d.size; M.background = d.background || DEFAULT_BG;
  const byName = Object.fromEntries((d.layers || []).map(L => [L.name, L]));
  const names = [...new Set([...LAYERS, ...(d.layers || []).map(L => L.name)])];
  const defRole = Object.fromEntries(LAYERS.map(L => [L.name, L.role]));
  M.layers = names.map(n => {
    const L = byName[n];
    if (L && L.role === "objects") {
      return { name: n, role: "objects", visible: true, grid: null,
        items: L.placements.filter(p => !p.id.startsWith("tile:")).map(p => ({
          id: p.id,
          x: p.at[0] * d.tile + (p.off ? p.off[0] : 0),
          y: p.at[1] * d.tile + (p.off ? p.off[1] : 0),
        })) };
    }
    const g = blankGrid(d.size[0], d.size[1]);
    const gr = blankGroups(d.size[0], d.size[1]);
    if (L && L.role === "terrain") L.grid.forEach((row, y) => row.forEach((v, x) => {
      if (v !== -1) g[y][x] = L.palette[v];
      if (L.groups?.[y]?.[x]) gr[y][x] = L.groups[y][x]; }));
    return { name: n, role: defRole[n] || "tiles", visible: true, grid: g,
             groups: gr, items: [] };
  });
  if (!M.layers.some(L => L.role === "objects"))
    M.layers.push({ name: "props", role: "objects", visible: true, grid: null, items: [] });
  // keep new stamps from colliding with group ids restored from the file
  state.nextGroup = 1 + M.layers.reduce((m, L) =>
    Math.max(m, ...(L.groups || []).map(r => Math.max(0, ...r))), 0);
  M.overrides = new Map(d.collisionOverrides || []);
  state.autoColl = d.collisionAuto !== false;
  $("#btnAuto")?.classList.toggle("on", state.autoColl);
  M.collision = new Set();
  (d.collisions || []).forEach(([x, y, w, h]) => {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) M.collision.add(key(x+i, y+j)); });
  M.spawns = d.spawns || [];
  // a map remembers which character it was built for; keep the picker in step
  if (d.character) {
    state.charId = d.character;
    const sel = $("#charSel");
    if (sel && [...sel.options].some(o => o.value === d.character)) sel.value = d.character;
  }
  ensureGrids(); renderLayers(); draw();
}
async function save() {
  const name = $("#mapName").value.trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(name)) return toast("bad map name", false);
  const r = await fetch("/api/save?name=" + encodeURIComponent(name),
    { method: "POST", body: JSON.stringify(serialise()) }).then(r => r.json());
  r.error ? toast(r.error, false) : toast(`saved ${r.saved} (${(r.bytes/1024).toFixed(0)} KB)`);
  refreshMapList();
}
/*
 * Deleting is the one action here with no undo, so it names the world in the prompt
 * rather than asking "are you sure?" about nothing in particular. The canvas is left
 * alone: losing the file you saved should not also lose what you have on screen.
 */
function deleteMapDialog() {
  const name = $("#loadSel").value || $("#mapName").value.trim();
  if (!name) return toast("no saved world selected", false);
  const dlg = $("#delDlg");
  $("#delWhat").textContent = `Delete “${name}”?`;
  dlg.returnValue = "";
  dlg.showModal();
  dlg.onclose = async () => {
    if (dlg.returnValue !== "ok") return;
    const r = await fetch("/api/delete?name=" + encodeURIComponent(name),
                          { method: "POST" }).then(r => r.json());
    if (r.error) return toast(r.error, false);
    toast(`deleted ${r.deleted}${r.bundle ? " and its export" : ""}`);
    await refreshMapList();
  };
}
async function refreshMapList() {
  const { maps } = await fetch("/api/maps").then(r => r.json());
  $("#loadSel").innerHTML = `<option value="">load…</option>` +
    maps.map(m => `<option>${m}</option>`).join("");
}

/* -------------------------------------------------------------- characters */
async function loadChars() {
  state.chars = await fetch("characters.json").then(r => r.json()).catch(() => []);
  const sel = $("#charSel");
  sel.innerHTML = state.chars.map(c => `<option value="${c.id}">${c.label}</option>`).join("");
  if (state.chars.length) { state.charId = state.charId || state.chars[0].id; sel.value = state.charId; }
  charImg();
}
function charDef() { return state.chars.find(c => c.id === state.charId) || state.chars[0]; }
function charImg() {
  const c = charDef(); if (!c) return null;
  return imgFor(c.image);
}

/* --------------------------------------------------------------- playtest */
const P = { x: 0, y: 0, dir: "down", t: 0, moving: false };
const keys = new Set();
function startPlay() {
  const sp = M.spawns[0]?.at || [1, 1];
  P.x = sp[0] * state.tile + state.tile / 2;
  P.y = sp[1] * state.tile + state.tile / 2;
  state.playing = true; $("#btnPlay").classList.add("on");
  $("#btnPlay").textContent = "■ stop";
  tick();
}
function stopPlay() { state.playing = false; $("#btnPlay").classList.remove("on");
  $("#btnPlay").textContent = "▶ walk"; draw(); }
function blocked(px, py) {
  const T = state.tile, FW = T * 0.44, FH = T * 0.3;
  for (let y = Math.floor((py - FH) / T); y <= Math.floor((py - 1) / T); y++)
    for (let x = Math.floor((px - FW/2) / T); x <= Math.floor((px + FW/2 - 1) / T); x++) {
      if (!inBounds(x, y)) return true;
      if (M.collision.has(key(x, y))) return true;
    }
  return false;
}
function tick() {
  if (!state.playing) return;
  let dx = 0, dy = 0;
  if (keys.has("a") || keys.has("arrowleft")) dx--;
  if (keys.has("d") || keys.has("arrowright")) dx++;
  if (keys.has("w") || keys.has("arrowup")) dy--;
  if (keys.has("s") || keys.has("arrowdown")) dy++;
  P.moving = !!(dx || dy);
  if (P.moving) {
    const sp = (keys.has("shift") ? 3.2 : 1.6), l = Math.hypot(dx, dy) || 1;
    const nx = P.x + dx/l*sp, ny = P.y + dy/l*sp;
    if (!blocked(nx, P.y)) P.x = nx;
    if (!blocked(P.x, ny)) P.y = ny;
    P.dir = dy > 0 ? "down" : dy < 0 ? "up" : dx < 0 ? "left" : "right";
    P.t += 0.18;
  } else P.t = 0;
  const cv = $("#map"), S = state.tile * state.zoom;
  state.cam.x = P.x * state.zoom - cv.width / 2;
  state.cam.y = P.y * state.zoom - cv.height / 2;
  draw();
  requestAnimationFrame(tick);
}
function drawPlayer(ctx, ox, oy, S) {
  const c = charDef(); if (!c) return;
  const im = charImg(); if (!im || !im.complete) return;
  const [FW, FH] = c.frame, Z = state.zoom;
  const row = P.moving ? c.rows.walk : c.rows.idle;
  const f = P.moving ? Math.floor(P.t) % c.framesPerDir : 0;
  const col = c.dirBlocks[P.dir] * c.framesPerDir + f;
  ctx.drawImage(im, col*FW, row*FH, FW, FH,
    Math.round(ox + P.x*Z - FW*Z/2), Math.round(oy + P.y*Z - FH*Z + 6*Z), FW*Z, FH*Z);
}

/* ----------------------------------------------------------------- export */
async function doExport() {
  const name = $("#mapName").value.trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(name)) return toast("bad map name", false);
  await fetch("/api/save?name=" + encodeURIComponent(name),
    { method: "POST", body: JSON.stringify(serialise()) });
  toast("exporting…");
  const r = await fetch("/api/export?name=" + encodeURIComponent(name) +
                        "&character=" + encodeURIComponent(state.charId || ""),
                        { method: "POST" }).then(r => r.json());
  if (r.error) return toast(r.error, false);
  toast(`exported ${r.tiles} tiles, ${r.kb} KB — downloading…`);
  // running on a server somewhere, out/ is not a folder you can open: send the
  // bundle to the browser as a zip
  if (r.download) {
    const a = document.createElement("a");
    a.href = r.download; a.download = name + ".zip";
    document.body.appendChild(a); a.click(); a.remove();
  }
}

/* ------------------------------------------------------------------- init */
// keep the map roughly on screen when panning
function clampCam() {
  const cv = $("#map"), S = state.tile * state.zoom;
  const pad = 4 * S;
  state.cam.x = Math.max(-pad, Math.min(state.cam.x, M.size[0]*S - cv.width + pad));
  state.cam.y = Math.max(-pad, Math.min(state.cam.y, M.size[1]*S - cv.height + pad));
}

function setTool(t) {
  state.tool = t;
  $$("[data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === t));
}
function newMapDialog() {
  const dlg = $("#newDlg");
  $("#nmW").value = M.size[0]; $("#nmH").value = M.size[1];
  $("#nmT").value = M.tile;
  $("#nmName").value = $("#mapName").value || "untitled";
  // tiles and pixels are two views of the same number: edit either
  const sync = from => {
    const t = +$("#nmT").value || 32;
    if (from === "px") {
      $("#nmW").value = Math.max(4, Math.round(+$("#nmWpx").value / t));
      $("#nmH").value = Math.max(4, Math.round(+$("#nmHpx").value / t));
    }
    const w = +$("#nmW").value, h = +$("#nmH").value;
    $("#nmWpx").value = w * t; $("#nmHpx").value = h * t;
    $("#nmInfo").textContent = `${w * h} tiles · ${w * t} × ${h * t} px`;
  };
  ["#nmW", "#nmH", "#nmT"].forEach(id =>
    $(id).oninput = $(id).onchange = () => sync("tiles"));
  ["#nmWpx", "#nmHpx"].forEach(id =>
    $(id).oninput = $(id).onchange = () => sync("px"));
  $$(".preset").forEach(b => b.onclick = () => {
    $("#nmW").value = b.dataset.w; $("#nmH").value = b.dataset.h; sync("tiles"); });
  $("#nmDrag").onclick = () => {
    const t = +$("#nmT").value, name = $("#nmName").value.trim();
    dlg.returnValue = "drag"; dlg.close();
    if (name) $("#mapName").value = name;
    if (t !== state.tile) { state.tile = t; M.tile = t; fillSheetSelect(); }
    startDragSize();
  };
  sync("tiles");
  dlg.returnValue = "";
  dlg.showModal();
  dlg.onclose = () => {
    if (dlg.returnValue !== "ok") return;
    const w = Math.max(4, Math.min(512, +$("#nmW").value || 0));
    const h = Math.max(4, Math.min(512, +$("#nmH").value || 0));
    const t = +$("#nmT").value;
    const name = $("#nmName").value.trim();
    if (name) $("#mapName").value = name;
    if (t !== state.tile) { state.tile = t; M.tile = t; fillSheetSelect(); }
    newMap(w, h);
    toast(`new map ${w}×${h} at ${t}px`);
  };
}

/*
 * Drag out the map size on the canvas. The readout updates as you go, so you can
 * size a room by eye instead of guessing a tile count and adjusting afterwards.
 */
function startDragSize() {
  state.sizing = { from: null, to: null };
  state.marquee = null; state.sel = null;
  toast("drag on the canvas to set the map size · esc to cancel");
  draw();
}
function drawSizing(ctx, ox, oy, S) {
  const z = state.sizing; if (!z || !z.from || !z.to) return;
  const x0 = Math.min(z.from.x, z.to.x), x1 = Math.max(z.from.x, z.to.x);
  const y0 = Math.min(z.from.y, z.to.y), y1 = Math.max(z.from.y, z.to.y);
  const w = x1 - x0 + 1, h = y1 - y0 + 1;
  ctx.fillStyle = "rgba(255,198,92,.12)";
  ctx.fillRect(ox + x0*S, oy + y0*S, w*S, h*S);
  ctx.strokeStyle = "#ffc65c"; ctx.lineWidth = 2;
  ctx.strokeRect(ox + x0*S, oy + y0*S, w*S, h*S);
  ctx.fillStyle = "#ffc65c";
  ctx.font = "12px ui-monospace, monospace";
  ctx.fillText(`${w} × ${h} tiles · ${w*state.tile} × ${h*state.tile} px`,
               ox + x0*S + 6, oy + y0*S + 16);
}

function newMap(w, h) {
  if (!w || !h) return;
  snapshot();
  M.size = [w, h];
  M.layers = LAYERS.map(L => ({
    name: L.name, role: L.role, visible: true,
    grid: L.role === "objects" ? null : blankGrid(w, h),
    groups: L.role === "objects" ? null : blankGroups(w, h),
    items: [],
  }));
  M.collision = new Set(); M.overrides.clear(); M.spawns = [];
  state.marquee = null; state.sel = null; state.nextGroup = 1;
  state.cam = { x: -state.tile, y: -state.tile };
  ensureGrids(); renderLayers(); recomputeCollision(); draw();
}
function deleteSelection() {
  const mq = state.marquee; if (!mq) return;
  const x0 = Math.min(mq.x0, mq.x1), x1 = Math.max(mq.x0, mq.x1);
  const y0 = Math.min(mq.y0, mq.y1), y1 = Math.max(mq.y0, mq.y1);
  snapshot();
  let tiles = 0, objs = 0;
  for (const L of M.layers) {
    if (!L.visible) continue;                 // hidden layers are left alone
    if (L.role === "objects") {
      const keep = [];
      for (const it of L.items) {
        const a = state.singles?.byId?.[it.id];
        const w = a ? (a.anim ? a.anim.frame[0] : a.bbox[2]) : M.tile;
        const h = a ? (a.anim ? a.anim.frame[1] : a.bbox[3]) : M.tile;
        // an object goes if it overlaps the selection at all
        const ox0 = Math.floor(it.x / M.tile), oy0 = Math.floor(it.y / M.tile);
        const ox1 = Math.floor((it.x + w - 1) / M.tile);
        const oy1 = Math.floor((it.y + h - 1) / M.tile);
        if (ox1 >= x0 && ox0 <= x1 && oy1 >= y0 && oy0 <= y1) objs++;
        else keep.push(it);
      }
      L.items = keep;
      continue;
    }
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      if (!inBounds(x, y) || !L.grid[y][x]) continue;
      L.grid[y][x] = null; L.groups[y][x] = 0; tiles++;
    }
  }
  state.sel = null;
  recomputeCollision();
  draw();
  toast(`deleted ${tiles} tiles and ${objs} objects`);
}

/*
 * Collision is derived from what is on the map, using each object's own type, and
 * then your manual edits are laid on top. Defaults come from the labelling pass:
 * a thing that stands on the floor blocks over the patch where it meets the floor,
 * while rugs, wall art and anything sitting on a desk do not block at all.
 * Painting or erasing collision by hand records an override that survives further
 * editing -- so the defaults are a starting point, not a straitjacket.
 */
const SOLID_TILE_LAYERS = new Set(["walls", "furniture", "objects"]);

function derivedCollision() {
  const out = new Set();
  for (const L of M.layers) {
    if (!L.visible) continue;
    if (L.role === "objects") {
      for (const it of L.items) {
        const a = state.singles?.byId?.[it.id];
        if (a && a.blocks === false) continue;
        const box = a?.cbox;
        const [w, h] = objSize(it.id);
        const bx = it.x + (box ? box[0] : 0), by = it.y + (box ? box[1] : 0);
        const bw = box ? box[2] : w, bh = box ? box[3] : h;
        for (let y = Math.floor(by / M.tile); y <= Math.floor((by + bh - 1) / M.tile); y++)
          for (let x = Math.floor(bx / M.tile); x <= Math.floor((bx + bw - 1) / M.tile); x++)
            if (inBounds(x, y)) out.add(key(x, y));
      }
      continue;
    }
    if (!SOLID_TILE_LAYERS.has(L.name) || !L.grid) continue;
    L.grid.forEach((row, y) => row.forEach((ref, x) => { if (ref) out.add(key(x, y)); }));
  }
  return out;
}

function recomputeCollision() {
  if (!state.autoColl) return;
  const out = derivedCollision();
  for (const [k, solid] of M.overrides) solid ? out.add(k) : out.delete(k);
  M.collision = out;
}

function collisionFromLayers() {
  snapshot();
  M.overrides.clear();
  state.autoColl = true;
  $("#btnAuto")?.classList.add("on");
  recomputeCollision();
  draw();
  toast(`${M.collision.size} tiles solid, from object types`);
}

/* ------------------------------------------------- thumbnail picker */
/*
 * A native <select> cannot show images, and these lists run to 69 sheets and 58
 * sprite categories whose names alone ("generic", "complete", "part") tell you very
 * little. The <select> stays in the DOM as the source of truth -- every existing
 * caller still reads and writes sheetSel.value, and change events still fire -- and
 * this draws a searchable grid of the same options with a preview per entry, baked
 * by tools/build_thumbnails.py.
 */
const THUMB_PX = 48;
let thumbs = null;

async function loadThumbs() {
  if (thumbs) return thumbs;
  const grab = f => fetch(f).then(r => r.ok ? r.json() : null).catch(() => null);
  const [sh, ca] = await Promise.all([grab("thumbs_sheets.json"), grab("thumbs_cats.json")]);
  thumbs = { sheets: sh, cats: ca };
  return thumbs;
}
// The atlas is drawn as a scaled background so one image serves every cell; the
// slot index is baked at CELL px and shown at THUMB_PX.
function thumbCss(key, px = THUMB_PX) {
  const singles = state.palMode === "singles";
  const meta = singles ? thumbs?.cats : thumbs?.sheets;
  const file = singles ? "thumbs_cats.png" : "thumbs_sheets.png";
  const slot = meta?.index?.[singles ? key : `${state.tile}:${key}`];
  if (slot === undefined) return "";
  const k = px / meta.cell;
  return `background-image:url(${file});background-size:${meta.cols * meta.cell * k}px auto;` +
         `background-position:${-(slot % meta.cols) * px}px ${-Math.floor(slot / meta.cols) * px}px`;
}
function pickerOptions() {
  const out = [];
  for (const node of $("#sheetSel").children) {
    if (node.tagName === "OPTGROUP")
      for (const o of node.children) out.push({ v: o.value, t: o.textContent, g: node.label });
    else out.push({ v: node.value, t: node.textContent, g: "Other" });
  }
  return out;
}
// The option text repeats its group so a closed native select still made sense;
// in the grid the group is already a heading above the cell.
function shortLabel(text, group) {
  return text.startsWith(group + " · ") ? text.slice(group.length + 3) : text;
}
function syncPickBtn() {
  const sel = $("#sheetSel"), btn = $("#pickBtn");
  if (!btn) return;
  const opt = sel.selectedOptions[0];
  $("#pickLbl").textContent = opt ? opt.textContent : "—";
  btn.querySelector(".th").style.cssText =
    "display:block;width:24px;height:24px;flex:0 0 24px;border-radius:3px;" +
    "background:#0b0c10;image-rendering:pixelated;" + thumbCss(sel.value, 24);
}
function renderPickList(q = "") {
  const list = $("#pickList"), cur = $("#sheetSel").value;
  const needle = q.trim().toLowerCase();
  const by = new Map();
  for (const o of pickerOptions()) {
    if (needle && !(o.g + " " + o.t).toLowerCase().includes(needle)) continue;
    if (!by.has(o.g)) by.set(o.g, []);
    by.get(o.g).push(o);
  }
  if (!by.size) { list.innerHTML = `<div id="pickNone">nothing matches “${q}”</div>`; return; }
  const esc = escapeHtml;
  list.innerHTML = [...by].map(([g, items]) =>
    `<h4>${esc(g)}</h4><div class="pgrid">` + items.map(o =>
      `<button class="pcell${o.v === cur ? " on" : ""}" data-v="${esc(o.v)}" title="${esc(o.t)}">` +
      `<i class="th" style="${thumbCss(o.v)}"></i><em>${esc(shortLabel(o.t, g))}</em></button>`
    ).join("") + `</div>`).join("");
  const on = list.querySelector(".pcell.on");
  if (on && !needle) on.scrollIntoView({ block: "center" });
}
function closePicker() {
  const pop = $("#pickPop"); if (pop) pop.hidden = true;
}
async function openPicker() {
  await loadThumbs();
  const pop = $("#pickPop");
  if (!pop._wired) {
    pop._wired = true;
    pop.addEventListener("click", e => {
      const cell = e.target.closest(".pcell"); if (!cell) return;
      const sel = $("#sheetSel");
      sel.value = cell.dataset.v;
      sel.dispatchEvent(new Event("change"));
      syncPickBtn(); closePicker();
    });
    $("#pickSearch").addEventListener("input", e => renderPickList(e.target.value));
    $("#pickSearch").addEventListener("keydown", e => {
      if (e.key === "Escape") { closePicker(); $("#pickBtn").focus(); }
      if (e.key === "Enter") { const c = $("#pickList").querySelector(".pcell"); if (c) c.click(); }
      e.stopPropagation();
    });
  }
  const r = $("#pickBtn").getBoundingClientRect();
  pop.style.left = Math.min(r.left, innerWidth - 400) + "px";
  pop.style.top = (r.bottom + 4) + "px";
  pop.hidden = false;
  $("#pickSearch").value = "";
  renderPickList("");
  $("#pickSearch").focus();
}


/* ------------------------------------------------- theme */
/*
 * Chrome colours all come from CSS variables, so switching theme is one attribute
 * on <html>. Canvas work cannot read those variables implicitly, so anything drawn
 * on a canvas asks for the current value.
 */
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
// Three states, not two. "system" is the default and follows the OS live, so the
// editor matches everything else on screen without being told to; picking light or
// dark pins it until you cycle back round to system.
const THEMES = ["system", "light", "dark"];
const THEME_ICON = { system: "◐", light: "☀", dark: "☾" };
const DARK_MQ = matchMedia("(prefers-color-scheme: dark)");
let themePref = "system";

function resolveTheme(pref) {
  return pref === "system" ? (DARK_MQ.matches ? "dark" : "light") : pref;
}
function setTheme(pref) {
  if (!THEMES.includes(pref)) pref = "system";
  themePref = pref;
  document.documentElement.dataset.theme = resolveTheme(pref);
  const b = $("#btnTheme");
  if (b) {
    b.textContent = THEME_ICON[pref];
    b.dataset.tip = pref === "system"
      ? "Following your system setting. Click for light."
      : `Pinned to ${pref}. Click for ${pref === "light" ? "dark" : "system"}.`;
  }
  try { localStorage.setItem("wb.theme", pref); } catch (e) { /* private mode */ }
  draw(); drawPalette(); if (state.palMode === "singles") drawSingles();
}
function cycleTheme() {
  setTheme(THEMES[(THEMES.indexOf(themePref) + 1) % THEMES.length]);
}
function initTheme() {
  let pref = null;
  try { pref = localStorage.getItem("wb.theme"); } catch (e) { /* private mode */ }
  // "light"/"dark" written by an older build still mean pinned; anything else is system
  setTheme(THEMES.includes(pref) ? pref : "system");
  // repaint when the OS flips while we are following it
  DARK_MQ.addEventListener("change", () => {
    if (themePref === "system") setTheme("system");
  });
}


/* ------------------------------------------------- resizable layout */
/*
 * The three columns are grid tracks driven by two CSS variables, so dragging a
 * gutter is just a variable write -- no reflow bookkeeping. The palette resizes on
 * its own bottom edge (native CSS resize) and its ResizeObserver repaints it.
 * All three sizes persist per browser.
 */
const LAYOUT = { colL: [190, 620, 280], colR: [170, 460, 210] };

function setCol(which, px) {
  const [lo, hi] = LAYOUT[which];
  const v = Math.max(lo, Math.min(hi, Math.round(px)));
  document.documentElement.style.setProperty("--" + which, v + "px");
  store("wb." + which, v);
  draw();                       // the stage changed width; the canvas is sized to it
  return v;
}
function store(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
function recall(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

/*
 * Collapsing is not just a width of zero: the clamp in setCol would fight it, and a
 * collapsed panel still needs somewhere to click to come back. The gutter stays put
 * and keeps the chevron, so the way out is where the way in was.
 */
const PANEL = { colL: "aside:not(.right)", colR: "aside.right",
                gut: { colL: "#gutL", colR: "#gutR" },
                chev: { colL: "#chevL", colR: "#chevR" },
                label: { colL: "tiles", colR: "tools" } };

function collapsed(which) { return recall("wb." + which + ".off") === "1"; }

function setCollapsed(which, off) {
  $(PANEL[which]).classList.toggle("collapsed", off);
  $(PANEL.gut[which]).classList.toggle("off", off);
  const width = off ? 0 : (+recall("wb." + which) || LAYOUT[which][2]);
  document.documentElement.style.setProperty("--" + which, width + "px");
  const chev = $(PANEL.chev[which]);
  const left = which === "colL";
  // the chevron always points the way the panel will move
  chev.textContent = off === left ? "›" : "‹";
  const tip = `${off ? "Show" : "Collapse"} the ${PANEL.label[which]} panel.`;
  chev.dataset.tip = tip;
  // the gutter chevron is a hairline you have to know about; the header button is
  // where someone actually looks for this
  const hdr = $(which === "colL" ? "#btnPanelL" : "#btnPanelR");
  if (hdr) { hdr.dataset.tip = tip; hdr.classList.toggle("on", off); }
  store("wb." + which + ".off", off ? "1" : "0");
  draw();
}

function initLayout() {
  for (const which of ["colL", "colR"]) {
    const saved = +recall("wb." + which);
    if (saved) setCol(which, saved);
    setCollapsed(which, collapsed(which));
  }
  const ph = recall("wb.palH");
  if (ph) $("#palWrap").style.height = ph + "px";

  const drag = (el, which, sign) => {
    el.addEventListener("mousedown", e => {
      if (e.target.closest(".chev")) return;      // the chevron is a button, not a grip
      if (collapsed(which)) return;               // nothing to drag while it is away
      e.preventDefault();
      const app = $("#app").getBoundingClientRect();
      el.classList.add("drag"); document.body.classList.add("resizing");
      const move = ev => setCol(which, sign > 0 ? ev.clientX - app.left : app.right - ev.clientX);
      const up = () => {
        removeEventListener("mousemove", move); removeEventListener("mouseup", up);
        el.classList.remove("drag"); document.body.classList.remove("resizing");
      };
      addEventListener("mousemove", move); addEventListener("mouseup", up);
    });
    // a double click restores the default width
    el.addEventListener("dblclick", e => {
      if (e.target.closest(".chev") || collapsed(which)) return;
      setCol(which, LAYOUT[which][2]);
    });
  };
  drag($("#gutL"), "colL", 1);
  drag($("#gutR"), "colR", -1);
  const toggle = which => () => setCollapsed(which, !collapsed(which));
  $("#chevL").onclick = toggle("colL");
  $("#chevR").onclick = toggle("colR");
  $("#btnPanelL").onclick = toggle("colL");
  $("#btnPanelR").onclick = toggle("colR");

  if (window.ResizeObserver)
    new ResizeObserver(() => {
      const h = $("#palWrap").clientHeight;
      if (h) store("wb.palH", h);
    }).observe($("#palWrap"));
}


/* ------------------------------------------------- tooltips */
/*
 * "rect", "pick" and "pan" are only obvious once you already know them. Every
 * control carrying data-tip explains itself on hover, with its keyboard shortcut
 * from data-key. One shared element positioned in JS, because the side panels
 * scroll and would clip a tip anchored inside them.
 */
function initTips() {
  const tip = $("#tip");
  let over = null;
  const show = el => {
    over = el;
    const key = el.dataset.key;
    tip.innerHTML = escapeHtml(el.dataset.tip) +
      (key ? ` <kbd>${escapeHtml(key)}</kbd>` : "");
    tip.hidden = false;
    const r = el.getBoundingClientRect(), t = tip.getBoundingClientRect();
    let x = r.left + r.width / 2 - t.width / 2;
    let y = r.bottom + 7;
    if (y + t.height > innerHeight - 6) y = r.top - t.height - 7;   // flip above
    tip.style.left = Math.max(6, Math.min(x, innerWidth - t.width - 6)) + "px";
    tip.style.top = Math.max(6, y) + "px";
  };
  const hide = () => { over = null; tip.hidden = true; };
  addEventListener("mouseover", e => {
    const el = e.target.closest("[data-tip]");
    if (el !== over) el ? show(el) : hide();
  });
  addEventListener("mousedown", hide);
  addEventListener("keydown", hide);
}
function escapeHtml(t) {
  return String(t).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}


function init() {
  ensureGrids(); renderLayers();
  state.cam = { x: -state.tile, y: -state.tile };

  $("#sheetSel").onchange = e => {
    if (state.palMode === "singles") { state.singleCat = e.target.value;
      const g = state.singles.groups?.[state.singleCat] || "";
      $("#sheetInfo").textContent = `${g} · whole sprites`;
      $("#palWrap").scrollTop = 0; drawSingles(); }
    else selectSheet(e.target.value);
  };
  initTheme();
  initLayout();
  initTips();
  $("#btnTheme").onclick = cycleTheme;
  $("#pickBtn").onclick = () => ($("#pickPop")?.hidden === false ? closePicker() : openPicker());
  addEventListener("mousedown", e => {
    if (!e.target.closest("#pickPop") && !e.target.closest("#pickBtn")) closePicker();
  });
  $("#modeSheets").onclick = () => setPalMode("sheets");
  $("#modeSingles").onclick = () => setPalMode("singles");
  $("#tileSize").onchange = e => { state.tile = +e.target.value; M.tile = state.tile;
    fillSheetSelect(); draw(); };
  $("#selBadge").onclick = () => { state.marquee = null; state.sel = null;
    $("#selBadge").hidden = true; draw(); };
  $("#btnGrid").onclick = e => { state.showGrid = !state.showGrid;
    e.target.classList.toggle("on", state.showGrid); draw(); };
  $("#btnColl").onclick = e => { state.showColl = !state.showColl;
    e.target.classList.toggle("on", state.showColl); draw(); };
  $("#btnPlay").onclick = () => state.playing ? stopPlay() : startPlay();
  $("#btnNew").onclick = newMapDialog;
  $("#btnSave").onclick = save;
  $("#btnDelete").onclick = deleteMapDialog;
  $("#btnUndo").onclick = undo; $("#btnRedo").onclick = redo;
  $("#btnExport").onclick = doExport;
  $("#charSel").onchange = e => { state.charId = e.target.value; charImg(); draw(); };
  $("#btnCollAuto").onclick = collisionFromLayers;
  $("#btnCollClear").onclick = () => { snapshot(); state.autoColl = false;
    $("#btnAuto").classList.remove("on");
    M.overrides.clear(); M.collision.clear(); draw();
    toast("collision cleared; auto off"); };
  $("#btnAuto").onclick = e => { state.autoColl = !state.autoColl;
    e.target.classList.toggle("on", state.autoColl);
    if (state.autoColl) { recomputeCollision(); draw(); }
    toast(state.autoColl ? "collision follows object types" : "collision is manual"); };
  $("#btnAddLayer").onclick = () => { const n = prompt("layer name"); if (!n) return;
    const obj = confirm("Object layer? (free pixel placement)\nCancel = tile layer");
    M.layers.push({ name: n, role: obj ? "objects" : "tiles", visible: true,
                    grid: obj ? null : blankGrid(...M.size), items: [] });
    state.layerIdx = M.layers.length - 1; ensureGrids(); renderLayers(); draw(); };
  $("#snapSel").onchange = e => { state.snap = +e.target.value; };
  $("#loadSel").onchange = async e => {
    if (!e.target.value) return;
    // through the API, not /maps/<name>.json: deployed, maps live on a mounted
    // volume outside the served root
    const d = await fetch("/api/map?name=" + encodeURIComponent(e.target.value))
      .then(r => r.json());
    $("#mapName").value = e.target.value; snapshot(); deserialise(d);
    toast("loaded " + e.target.value);
  };
  $$("[data-tool]").forEach(b => b.onclick = () => setTool(b.dataset.tool));

  const pal = $("#pal");
  let pdrag = null;
  const wrap = $("#palWrap");
  const palCell = ev => {
    const b = pal.getBoundingClientRect(), t = state.tile * (pal._z || 1);
    return { c: Math.floor((ev.clientX - b.left + wrap.scrollLeft) / t),
             r: Math.floor((ev.clientY - b.top + wrap.scrollTop) / t) };
  };
  const repaintPalette = () => {
    state.palMode === "sheets" ? drawPalette() : drawSingles();
  };
  wrap.addEventListener("scroll", repaintPalette);
  // redraw when the panel actually gets its size, without depending on rAF
  if (window.ResizeObserver) new ResizeObserver(repaintPalette).observe(wrap);
  pal.onmousedown = ev => {
    if (state.palMode === "singles") return pickSingle(ev);
    pdrag = palCell(ev);
    state.stamp = { sheet: state.sheet.id, col: pdrag.c, row: pdrag.r, w: 1, h: 1 };
    drawPalette(); drawStampPreview(); };
  pal.onmousemove = ev => { if (!pdrag || state.palMode === "singles") return; const p = palCell(ev);
    state.stamp = { sheet: state.sheet.id, col: Math.min(pdrag.c, p.c), row: Math.min(pdrag.r, p.r),
      w: Math.abs(p.c - pdrag.c) + 1, h: Math.abs(p.r - pdrag.r) + 1 };
    drawPalette(); drawStampPreview(); };
  addEventListener("mouseup", () => { pdrag = null; onMapUp(); });

  const map = $("#map");
  map.onmousedown = onMapDown;
  map.onmousemove = onMapMove;
  map.onwheel = ev => { ev.preventDefault();
    const before = state.zoom;
    state.zoom = Math.max(1, Math.min(6, state.zoom + (ev.deltaY < 0 ? 1 : -1)));
    if (state.zoom !== before) { $("#zoomLbl").textContent = state.zoom + "x"; draw(); } };

  addEventListener("keydown", e => {
    keys.add(e.key.toLowerCase());
    if (state.playing) { if (e.key === "Escape") stopPlay(); return; }
    // don't hijack typing in the map name box or the dropdowns
    const el = document.activeElement;
    if (el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) {
      if (e.key === "Escape") el.blur();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); return; }
    const k = e.key.toLowerCase();
    if (k === "b") setTool("paint"); if (k === "e") setTool("erase");
    if (k === "r") setTool("rect");  if (k === "f") setTool("fill");
    if (k === "i") setTool("pick");  if (k === " ") { e.preventDefault(); setTool("pan"); }
    if (k === "h") setTool("pan");
    if (k === "g") $("#btnGrid").click();
    if (k === "c") $("#btnColl").click();
    if ((k === "delete" || k === "backspace") && state.marquee) {
      e.preventDefault(); deleteSelection(); return;
    }
    if (k === "escape") { state.marquee = null; state.sel = null;
      if (state.sizing) { state.sizing = null; toast("cancelled"); }
      draw(); return; }
    if (k === "v") setTool("select");
    if ((k === "delete" || k === "backspace") && state.sel) {
      e.preventDefault(); snapshot();
      for (const L of M.layers) { const i = L.items?.indexOf(state.sel);
        if (i > -1) L.items.splice(i, 1); }
      state.sel = null; draw(); return;
    }
    if (state.sel && k.startsWith("arrow")) {          // nudge by whole cells
      e.preventDefault();
      const d = e.shiftKey ? state.snap / 2 : state.snap;
      if (k === "arrowleft") state.sel.x -= d; if (k === "arrowright") state.sel.x += d;
      if (k === "arrowup") state.sel.y -= d;   if (k === "arrowdown") state.sel.y += d;
      recomputeCollision(); draw(); return;
    }
    // WASD and the arrows pan the canvas. Arrows nudge instead when an object is
    // selected, which is the more specific intent.
    const PAN = { w: [0,-1], s: [0,1], a: [-1,0], d: [1,0],
                  arrowup: [0,-1], arrowdown: [0,1],
                  arrowleft: [-1,0], arrowright: [1,0] };
    if (PAN[k]) {
      e.preventDefault();
      const step = state.tile * state.zoom * (e.shiftKey ? 4 : 1);
      state.cam.x += PAN[k][0] * step;
      state.cam.y += PAN[k][1] * step;
      clampCam(); draw(); return;
    }
    if (k === "m") setTool("move");
    if (k === "[") { state.layerIdx = Math.max(0, state.layerIdx - 1); renderLayers(); }
    if (k === "]") { state.layerIdx = Math.min(M.layers.length - 1, state.layerIdx + 1); renderLayers(); }
    if (k === "-") { state.zoom = Math.max(1, state.zoom - 1); $("#zoomLbl").textContent = state.zoom+"x"; draw(); }
    if (k === "=" || k === "+") { state.zoom = Math.min(6, state.zoom + 1); $("#zoomLbl").textContent = state.zoom+"x"; draw(); }
  });
  addEventListener("keyup", e => keys.delete(e.key.toLowerCase()));
  addEventListener("resize", draw);

  loadSheets().then(() => { draw(); });
  loadSingles().catch(() => {});
  loadChars();
  refreshMapList();
}
init();
