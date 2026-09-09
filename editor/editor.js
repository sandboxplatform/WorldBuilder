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

// Whole numbers to work at, halves below to see a big map at once: Chester Harbour
// is 116x72 tiles, 3712px of art at 1x, which no window shows in one piece.
const ZOOMS = [0.25, 0.5, 1, 2, 3, 4, 5, 6];

const state = {
  tile: 32, zoom: 2, cam: { x: 0, y: 0 },
  sheets: {}, sheetsBySize: {}, sheet: null, img: new Map(),
  stamp: null,                       // {sheet, col, row, w, h}
  tool: "paint", showGrid: true, showColl: false, snap: 32,
  night: 0, lightsIdx: null, selLight: null, sel: null, nextGroup: 1, marquee: null,
  palMode: "sheets", singles: null, singleCat: null, singlePage: 0,
  clock: 0, animTimer: null, autoColl: true,
  layerIdx: 0, undo: [], redo: [], playing: false,
  chars: [], charId: null,
};

const M = {
  name: "untitled", tile: 32, size: [40, 30], background: DEFAULT_BG,
  // lights you placed by hand; the derived ones are not stored, they are read
  // back off the sprites every time so they follow what you paint
  lights: [],
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

/* ------------------------------------------------- lighting */
/*
 * Two kinds of light. Derived ones are read off the sprites already placed -- a
 * street lamp lights because the catalog knows it is a street lamp -- and are never
 * stored, so they follow the map as you paint it. Authored ones are yours, live in
 * the map file, and are what you reach for when the art implies nothing.
 *
 * The editor draws them with the same arithmetic the runtime uses, because a night
 * preview that disagrees with the game is worse than no preview at all.
 */
async function loadLightsIndex() {
  if (state.lightsIdx) return state.lightsIdx;
  state.lightsIdx = await fetch("lights.json").then(r => r.ok ? r.json() : null)
                                              .catch(() => null);
  return state.lightsIdx;
}

function derivedLights() {
  const idx = state.lightsIdx;
  if (!idx) return [];
  const T = M.tile, out = [];
  for (const L of M.layers) {
    if (!L.visible) continue;
    for (const it of (L.items || [])) {
      const kind = idx.byId[it.id];
      if (!kind) continue;
      const a = state.singles?.byId?.[it.id];
      const bw = a?.anim ? a.anim.frame[0] : (a?.bbox?.[2] ?? T);
      const bh = a?.anim ? a.anim.frame[1] : (a?.bbox?.[3] ?? T);
      // a lamp glows at its head, not its feet -- the same rule the exporter uses
      out.push({ ...(idx.kinds[kind] || idx.kinds._default), kind,
                 x: it.x + bw / 2,
                 y: it.y + (bh > 2 * T ? Math.min(bh / 4, T) : bh / 2) });
    }
    if (!L.grid) continue;
    for (let y = 0; y < L.grid.length; y++) {
      const row = L.grid[y];
      for (let x = 0; x < row.length; x++) {
        const ref = row[x];
        if (!ref || isSprite(ref)) continue;
        const kind = idx.sheetCells[ref.slice(5)];   // drop the "tile:" prefix
        if (!kind) continue;
        out.push({ ...(idx.kinds[kind] || idx.kinds._default), kind,
                   x: x * T + T / 2, y: y * T + T / 2 });
      }
    }
  }
  return out;
}

function allLights() { return derivedLights().concat(M.lights || []); }

function ambientAt(n) {
  const amb = state.lightsIdx?.ambient
    || { day: "#ffffff", dusk: "#e0a86a", night: "#1b2a4a", darkness: 0.72 };
  const hex = h => { const m = hexA(h, 1).match(/[\d.]+/g); return [+m[0], +m[1], +m[2]]; };
  const [a, b, t] = n < 0.5 ? [amb.day, amb.dusk, n * 2] : [amb.dusk, amb.night, (n - .5) * 2];
  const A = hex(a), B = hex(b);
  const c = A.map((v, i) => Math.round(v + (B[i] - v) * t));
  return { rgb: `rgb(${c[0]},${c[1]},${c[2]})`, darkness: amb.darkness };
}

// flicker as two slow sines rather than noise: a candle breathes, it does not glitch
function lightStrength(l, i) {
  const gate = (l.when === "night") ? state.night : 1;
  if (gate <= 0) return 0;
  if (!l.flicker) return l.intensity * gate;
  const p = i * 1.7 + l.x * 0.013 + l.y * 0.017;
  const w = Math.sin(state.clock * 0.009 + p) * 0.6
          + Math.sin(state.clock * 0.021 + p * 2.3) * 0.4;
  return l.intensity * gate * (1 - l.flicker * 0.5 * (1 - w));
}

function lightBuf(w, h) {
  let c = lightBuf._c;
  if (!c) c = lightBuf._c = document.createElement("canvas");
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  return c;
}

function drawLighting(ctx, cv, ox, oy) {
  if (state.night <= 0) return false;
  const lights = allLights();
  const Z = state.zoom;
  const { rgb, darkness } = ambientAt(state.night);
  const buf = lightBuf(cv.width, cv.height);
  const b = buf.getContext("2d");

  b.globalCompositeOperation = "source-over";
  b.clearRect(0, 0, buf.width, buf.height);
  b.globalAlpha = darkness * state.night;
  b.fillStyle = rgb;
  b.fillRect(0, 0, buf.width, buf.height);

  // punch the pools of light out of the dark, then add their colour back on top --
  // holes alone give you grey daylight through a stencil, with no warmth
  b.globalCompositeOperation = "destination-out";
  let anyFlicker = false;
  lights.forEach((l, i) => {
    const s = lightStrength(l, i);
    if (s <= 0.01) return;
    if (l.flicker) anyFlicker = true;
    const cx = ox + l.x * Z, cy = oy + l.y * Z, r = l.r * Z;
    if (cx + r < 0 || cy + r < 0 || cx - r > buf.width || cy - r > buf.height) return;
    const g = b.createRadialGradient(cx, cy, 0, cx, cy, r);
    g.addColorStop(0, `rgba(255,255,255,${Math.min(1, s)})`);
    g.addColorStop(0.55, `rgba(255,255,255,${Math.min(1, s) * 0.45})`);
    g.addColorStop(1, "rgba(255,255,255,0)");
    b.globalAlpha = 1; b.fillStyle = g;
    b.fillRect(cx - r, cy - r, r * 2, r * 2);
  });
  b.globalCompositeOperation = "source-over";
  ctx.drawImage(buf, 0, 0);

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  lights.forEach((l, i) => {
    const s = lightStrength(l, i);
    if (s <= 0.01) return;
    const cx = ox + l.x * Z, cy = oy + l.y * Z, r = l.r * Z;
    if (cx + r < 0 || cy + r < 0 || cx - r > cv.width || cy - r > cv.height) return;
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    g.addColorStop(0, hexA(l.color, s * 0.5));
    g.addColorStop(1, hexA(l.color, 0));
    ctx.fillStyle = g;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
  });
  ctx.restore();
  return anyFlicker;
}
// #rgb, #rrggbb, or something a hand-edited map made up: never return a colour the
// canvas will throw on, because one bad light would take the whole frame down
function hexA(hex, a) {
  let h = String(hex || "").replace("#", "");
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  if (h.length !== 6 || /[^0-9a-f]/i.test(h)) h = "ffd9a0";
  const v = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${v[0]},${v[1]},${v[2]},${a})`;
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
    // sprites sit on whichever layer they were placed on, so every layer draws its
    // own -- after its tiles, and in layer order, which is what makes "put this lamp
    // on overhead" mean anything
    const drawItems = () => {
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
    };
    if (L.role === "objects" || !L.grid) { drawItems(); continue; }
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
    drawItems();                 // this layer's sprites sit above its own tiles
  }
  if (state.playing) {
    drawPlayerShadow(ctx, ox, oy);
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
  // Everything the map is made of has been drawn; now it gets dark. The character
  // is inside this, not on top of it -- a figure standing unlit in a dark street is
  // the one thing that gives a lighting system away.
  if (drawLighting(ctx, cv, ox, oy)) anyAnim = true;

  if (state.showGrid) {
    // crisp 1px lines: offset by .5 so they land on a pixel instead of straddling two
    ctx.lineWidth = 1;
    // read once, not per line: getComputedStyle inside the loop costs a reflow each
    const minor = cssVar("--gridMinor"), major = cssVar("--gridMajor");
    // zoomed out, a line every few pixels is a haze over the map rather than a
    // guide: keep the every-8 majors, which still say where you are
    const minors = S >= 12;
    for (let x = 0; x <= W; x++) {
      if (x % 8 && !minors) continue;
      const gx = Math.round(ox + x*S) + .5;
      ctx.strokeStyle = x % 8 ? minor : major;
      ctx.beginPath(); ctx.moveTo(gx, oy); ctx.lineTo(gx, oy + H*S); ctx.stroke();
    }
    for (let y = 0; y <= H; y++) {
      if (y % 8 && !minors) continue;
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
  if (state.tool === "light" || state.selLight) {
    const Z = state.zoom;
    for (const l of (M.lights || [])) {
      const cx = ox + l.x * Z, cy = oy + l.y * Z;
      const on = l === state.selLight;
      ctx.strokeStyle = on ? "#ffc65c" : "rgba(255,214,120,.55)";
      ctx.lineWidth = on ? 2 : 1;
      ctx.beginPath(); ctx.arc(cx, cy, l.r * Z, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = l.color;
      ctx.beginPath(); ctx.arc(cx, cy, on ? 5 : 4, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#000"; ctx.lineWidth = 1; ctx.stroke();
    }
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
// A sprite goes on the layer you have selected -- that is the whole point of picking
// one. Only when nothing is selected does it fall back to the objects layer.
function objLayer() {
  return M.layers[state.layerIdx] || M.layers.find(L => L.role === "objects");
}
function hitObject(px, py) {
  // topmost first, across every visible layer: you click what you can see, not what
  // happens to live on the layer that is selected
  for (let li = M.layers.length - 1; li >= 0; li--) {
    const L = M.layers[li];
    if (!L.visible || !L.items) continue;
    for (let i = L.items.length - 1; i >= 0; i--) {
      const it = L.items[i];
      const a = state.singles?.byId?.[it.id]; if (!a) continue;
      const w = a.anim ? a.anim.frame[0] : a.bbox[2];
      const h = a.anim ? a.anim.frame[1] : a.bbox[3];
      if (px >= it.x && py >= it.y && px < it.x + w && py < it.y + h) return { L, it, i };
    }
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
// One drop of the sprite stamp, snapped to its own footprint. Quiet on a drag,
// where a cell that does not fit is passed over rather than announced each time.
function dropSprite(ev, quiet) {
  const L = objLayer();
  if (!L) { if (!quiet) toast("add an object layer first", false); return null; }
  const p = pixelAt(ev);
  const it = { id: state.stamp.sprite, x: snapObj(p.x), y: snapObj(p.y) };
  const [w, h] = objSize(it.id);
  if (!objFits(it.x, it.y, w, h)) {
    if (!quiet) toast("does not fit in the selection", false);
    return null;
  }
  L.items.push(it); state.sel = it;
  return it;
}
function objSize(id) {
  const a = state.singles?.byId?.[id];
  if (!a) return [M.tile, M.tile];
  return a.anim ? [a.anim.frame[0], a.anim.frame[1]] : [a.bbox[2], a.bbox[3]];
}

/*
 * A stamp block is a rectangle, but the art inside it rarely is: the camping dock
 * comes with transparent corners, and writing those cells anyway replaced whatever
 * they were laid over -- water became blank canvas. Cells that are fully transparent
 * in the sheet are skipped, so a stamp only ever adds pixels.
 *
 * Emptiness is measured from the sheet itself, one tile at a time and cached, rather
 * than baked into an index: the sheets are already loaded for the palette, and it
 * keeps this true for any sheet without another build step.
 */
const tileAlphaCache = new Map();
// "empty" nothing at all, "partial" art with see-through gaps, "solid" edge to edge
function tileAlpha(sheetId, col, row) {
  const key = `${sheetId}#${col},${row}`;
  const hit = tileAlphaCache.get(key);
  if (hit !== undefined) return hit;
  const sh = sheetOf(sheetId); if (!sh) return "solid";
  const im = imgFor(sh.image);
  if (!im.complete || !im.naturalWidth) return "solid";   // unknown yet: paint it
  const T = state.tile;
  let c = tileAlpha._c;
  if (!c) { c = tileAlpha._c = document.createElement("canvas"); }
  if (c.width !== T) { c.width = c.height = T; }
  const x = c.getContext("2d", { willReadFrequently: true });
  x.clearRect(0, 0, T, T);
  x.drawImage(im, col * T, row * T, T, T, 0, 0, T, T);
  const d = x.getImageData(0, 0, T, T).data;
  let opaque = 0, clear = 0;
  for (let i = 3; i < d.length; i += 4) {
    if (d[i] > 200) opaque++; else if (d[i] < 8) clear++;
  }
  const cls = opaque === 0 ? "empty" : clear > 0 ? "partial" : "solid";
  tileAlphaCache.set(key, cls);
  return cls;
}
function tileIsEmpty(sheetId, col, row) { return tileAlpha(sheetId, col, row) === "empty"; }

/*
 * One cell holds one tile, so painting sand with see-through edges straight onto the
 * grass replaces the grass and the gaps show the empty canvas. Layers are the answer
 * and they already work -- but nothing said so, and the result reads as a bug. Say it
 * once, when it actually happens.
 */
let coverWarned = 0;
function warnCoveringWithHoles(layerName) {
  const now = Date.now();
  if (now - coverWarned < 12000) return;
  coverWarned = now;
  const i = M.layers.findIndex(L => L.name === layerName);
  const above = M.layers[i + 1];
  toast(`that tile has see-through parts — paint it on ${above ? `"${above.name}"` : "a higher layer"} to keep "${layerName}" showing underneath`, false);
}

function applyStamp(x, y) {
  const st = state.stamp; if (!st) return;
  const L = M.layers[state.layerIdx];
  if (st.sprite) return;                 // sprites go through placeSprite()
  // A multi-tile stamp is one object: remember which cells came from it so erasing
  // any of them takes the whole thing, rather than punching a hole in a desk.
  const gid = (st.w * st.h > 1) ? state.nextGroup++ : 0;
  let covering = false;
  for (let dy = 0; dy < st.h; dy++) for (let dx = 0; dx < st.w; dx++) {
    const tx = x + dx, ty = y + dy;
    if (!editable(tx, ty)) continue;
    const cls = tileAlpha(st.sheet, st.col + dx, st.row + dy);
    if (cls === "empty") continue;                 // never blank out what is under
    if (cls === "partial" && L.grid[ty][tx]) covering = true;
    L.grid[ty][tx] = makeRef(st.sheet, st.col + dx, st.row + dy);
    L.groups[ty][tx] = gid;
  }
  if (covering) warnCoveringWithHoles(L.name);
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
  // A sprite stamp has no sheet, column or row: makeRef used to build
  // "tile:undefined#undefined,undefined" out of them and flood the region with a ref
  // nothing can resolve -- invisible in the editor and broken in every exporter.
  // A sprite fills as itself, and one bigger than a cell cannot: it would overlap
  // its neighbour on every side, so say so rather than lay down a mess.
  if (st.sprite && (st.w > 1 || st.h > 1)) {
    toast(`${st.w}×${st.h} is too big to fill with — try a 1×1 sprite or a tile`, false);
    return;
  }
  const rep = st.sprite ? "sprite:" + st.sprite : makeRef(st.sheet, st.col, st.row);
  if (target === rep) return;
  const q = [[x, y]], seen = new Set();
  while (q.length) {
    const [cx, cy] = q.pop(); const k = key(cx, cy);
    if (!editable(cx, cy) || seen.has(k) || L.grid[cy][cx] !== target) continue;
    seen.add(k); L.grid[cy][cx] = rep;
    q.push([cx+1,cy],[cx-1,cy],[cx,cy+1],[cx,cy-1]);
  }
}
async function pickTile(i, r) {
  state.layerIdx = i;
  // the stamp and the palette have to agree: picking a sheet tile while the singles
  // palette is up left you holding a tile the palette could not show
  if (state.palMode !== "sheets") await setPalMode("sheets");
  selectSheet(r.id);
  state.stamp = { sheet: r.id, col: r.col, row: r.row, w: 1, h: 1 };
  drawPalette(); drawStampPreview(); renderLayers();
}

async function pickSprite(i, id) {
  const a = state.singles?.byId?.[id];
  if (!a) return false;
  state.layerIdx = i;
  state.stamp = { sprite: id, w: a.tiles[0], h: a.tiles[1], image: a.image };
  // ids read pack.kind.category.name, and the category is the palette's own key
  const cats = state.singles.cats;
  let cat = id.slice(0, id.lastIndexOf("."));
  if (!cats[cat]) cat = Object.keys(cats).find(c => cats[c].some(e => e.id === id));
  if (cat) {
    state.singleCat = cat;
    if (state.palMode !== "singles") await setPalMode("singles");
    else { fillSingleSelect(); drawSingles(); }
    // a category runs to hundreds of sprites, so scroll the one you picked into view
    const n = singleList().findIndex(e => e.id === id), wrap = $("#palWrap");
    if (n >= 0 && wrap) {
      const row = Math.floor(n / SINGLE_COLS);
      wrap.scrollTop = Math.max(0, row * SINGLE_CELL - wrap.clientHeight / 2);
    }
    drawSingles();
  }
  drawStampPreview(); renderLayers();
  return true;
}

// The eyedropper hands back whatever is under the cursor. A tile layer holds sheet
// tiles and whole sprites, and objects sit above both, so all three have to answer
// -- picking used to parse for a tile: ref and give up on anything else, which on a
// map painted from the singles palette meant it never picked anything at all.
function pickAt(x, y, ev) {
  // objects first, the way erase already takes the sprite on top before the tiles
  if (ev) {
    const p = pixelAt(ev, false), hit = hitObject(p.x, p.y);
    if (hit) { pickSprite(M.layers.indexOf(hit.L), hit.it.id); return; }
  }
  for (let i = M.layers.length - 1; i >= 0; i--) {
    const L = M.layers[i];
    if (L.visible === false) continue;   // a hidden layer is not what you clicked on
    const ref = L.grid?.[y]?.[x];
    const r = parseRef(ref);
    if (r) { pickTile(i, r); return; }
    const sd = isSprite(ref) ? spriteDef(ref) : null;
    if (sd) { pickSprite(i, sd.id); return; }
  }
}

let drag = null;
function onMapDown(ev) {
  if (state.playing) return;
  const c = cellAt(ev);
  if (state.sizing) { state.sizing.from = c; state.sizing.to = c;
                      drag = { sizing: true }; draw(); return; }
  if (ev.altKey) { pickAt(c.x, c.y, ev); return; }
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
    // an object layer has no grid: take the whole sprite under the cursor. A tile
    // layer may now hold sprites too, so try one before falling through to tiles.
    if (M.layers[state.layerIdx]?.role === "objects") {
      snapshot(); eraseObjectAt(ev); drag = { erasingObjects: true }; draw(); return;
    }
    const b = $("#map").getBoundingClientRect();
    if (hitObject((ev.clientX - b.left + state.cam.x) / state.zoom,
                  (ev.clientY - b.top + state.cam.y) / state.zoom)) {
      snapshot(); eraseObjectAt(ev); draw(); return;
    }
  }

  if (t === "light") {
    const p = pixelAt(ev, false);
    const hit = lightAt(p.x, p.y);
    if (hit) { snapshot(); selectLight(hit); drag = { light: hit,
                 dx: hit.x - p.x, dy: hit.y - p.y }; return; }
    snapshot();
    const l = { ...NEW_LIGHT, x: Math.round(p.x), y: Math.round(p.y), kind: "custom" };
    M.lights.push(l);
    selectLight(l);
    updateLightInfo();
    // placing a light in broad daylight shows nothing, so bring the night up
    if (state.night === 0) { $("#nightSlider").value = 60; setNight(60); }
    drag = { light: l, dx: 0, dy: 0 };
    return;
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
    const it = dropSprite(ev);
    if (!it) { drag = null; return; }
    // dragging on goes on painting, the way a tile stamp does. Nudging what you
    // just put down is the move tool's job, and it used to steal the drag here.
    drag = { paintObj: true, last: `${it.x},${it.y}` };
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
  applyTool(c.x, c.y, ev);
  draw();
}
function applyTool(x, y, ev) {
  switch (state.tool) {
    case "paint": applyStamp(x, y); break;
    case "erase": eraseAt(x, y); break;
    case "fill": if (inBounds(x, y)) floodFill(x, y); break;
    case "pick": pickAt(x, y, ev); break;
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
    + `  → ${M.layers[state.layerIdx]?.name ?? "?"}`
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
  if (drag.paintObj) {
    // one per cell entered: without this a wobble inside one cell stacks copies
    const p = pixelAt(ev), k = `${snapObj(p.x)},${snapObj(p.y)}`;
    if (k !== drag.last && dropSprite(ev, true)) drag.last = k;
    draw(); return;
  }
  if (drag.light) { const p = pixelAt(ev, false);
    // free placement: a light is not a tile and rarely wants to sit on a corner
    drag.light.x = Math.round(p.x + drag.dx);
    drag.light.y = Math.round(p.y + drag.dy);
    draw(); return; }
  if (drag.obj) { const p = pixelAt(ev, false);
    const nx = snapObj(p.x + drag.dx), ny = snapObj(p.y + drag.dy);
    const [ow, oh] = objSize(drag.obj.id);
    if (objFits(nx, ny, ow, oh)) { drag.obj.x = nx; drag.obj.y = ny; }
    draw(); return; }
  if (drag.rect) { drag.to = c; draw(); previewRect(drag); return; }
  applyTool(c.x, c.y, ev); draw();
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
        const sc = st.col + ((x - x0) % st.w), sr = st.row + ((y - y0) % st.h);
        if (tileIsEmpty(st.sheet, sc, sr)) continue;   // never blank out what is under
        L.grid[y][x] = makeRef(st.sheet, sc, sr);
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
    } else if (st) {
      // A sprite has no sheet to slice, so the rect used to fall past this branch
      // and do nothing at all. It fills as a grid of drops instead, stepping by the
      // sprite's own footprint the way a multi-tile tile stamp repeats -- and only
      // where a whole one fits, since half an object is not something to place.
      const L = objLayer();
      if (!L) toast("add an object layer first", false);
      else {
        const T = M.tile, [pw, ph] = objSize(st.sprite);
        const cw = Math.max(1, Math.round(pw / T)), ch = Math.max(1, Math.round(ph / T));
        let n = 0;
        for (let y = y0; y + ch - 1 <= y1; y += ch)
          for (let x = x0; x + cw - 1 <= x1; x += cw) {
            if (!objFits(x * T, y * T, pw, ph)) continue;
            L.items.push({ id: st.sprite, x: x * T, y: y * T });
            n++;
          }
        if (!n) toast(`nothing placed — a ${cw}×${ch} sprite does not fit`, false);
      }
    }
  }
  drag = null;
  if (wasEditing && !["coll+", "coll-"].includes(state.tool)) recomputeCollision();
  draw();
}

/* ----------------------------------------------------------------- layers */
function renderLayers() {
  $("#layers").innerHTML = M.layers.map((L, i) => `
    <div class="layer ${i === state.layerIdx ? "sel" : ""}" data-i="${i}"
         data-tip="${i === state.layerIdx ? "You are drawing here."
                     : "Click to draw on " + L.name + "."} The box only hides it.">
      <input type="checkbox" ${L.visible ? "checked" : ""} data-vis="${i}"
             data-tip="Show or hide ${L.name}.">
      <span>${L.name}</span>
      <small style="color:var(--dim)">${L.items?.length
        ? L.items.length + (L.role === "objects" ? " obj" : " spr")
        : (L.role === "objects" ? "obj" : "")}</small>
    </div>`).join("");
  $$("#layers .layer").forEach(el => el.onclick = e => {
    if (e.target.dataset.vis !== undefined) return;
    state.layerIdx = +el.dataset.i; renderLayers(); });
  $$("#layers input").forEach(el => el.onchange = () => {
    M.layers[+el.dataset.vis].visible = el.checked; draw(); });
}

/* ------------------------------------------------------- save / load / new */
// tile position plus a pixel offset inside it: keeps the format readable and
// backwards compatible (no "off" means tile-aligned, as before)
function placementsOf(L) {
  return L.items.map(it => {
    const tx = Math.floor(it.x / M.tile), ty = Math.floor(it.y / M.tile);
    const ox = it.x - tx * M.tile, oy = it.y - ty * M.tile;
    const p = { id: it.id, at: [tx, ty] };
    if (ox || oy) p.off = [ox, oy];
    return p;
  });
}
function serialise() {
  const layers = [];
  for (const L of M.layers) {
    if (L.role === "objects") {
      if (!L.items.length) continue;
      // tile position plus a pixel offset inside it: keeps the format readable and
      // backwards compatible (no "off" means tile-aligned, as before)
      layers.push({ name: L.name, role: "objects", units: "px",
                    placements: placementsOf(L) });
      continue;
    }
    const pal = [], pi = new Map();
    const grid = L.grid.map(row => row.map(ref => {
      if (!ref) return -1;
      if (!pi.has(ref)) { pi.set(ref, pal.length); pal.push(ref); }
      return pi.get(ref);
    }));
    if (pal.length || L.items.length) {
      const out = { name: L.name, role: "terrain", palette: pal, grid };
      // stamp grouping is an editing aid, not art: renderers ignore it, but keeping
      // it means a reopened map still erases multi-tile objects as one piece
      if (L.groups?.some(r => r.some(v => v))) out.groups = L.groups;
      // sprites dropped on a tile layer travel with it; readers that only know about
      // grids ignore the key, and the exporter already walks placements on any layer
      if (L.items.length) out.placements = placementsOf(L);
      layers.push(out);
    }
  }
  const lights = (M.lights || []).map(l => ({ ...l }));
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
                lights,
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
  M.lights = (d.lights || []).map(l => ({ ...l }));
  state.selLight = null;
  const byName = Object.fromEntries((d.layers || []).map(L => [L.name, L]));
  const names = [...new Set([...LAYERS.map(L => L.name), ...(d.layers || []).map(L => L.name)])];
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
    const items = (L?.placements || [])
      .filter(p => !p.id.startsWith("tile:"))
      .map(p => ({ id: p.id,
                   x: p.at[0] * d.tile + (p.off ? p.off[0] : 0),
                   y: p.at[1] * d.tile + (p.off ? p.off[1] : 0) }));
    return { name: n, role: defRole[n] || "tiles", visible: true, grid: g,
             groups: gr, items };
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

/*
 * The shadow a character stands in.
 *
 * Nothing is baked into the character sheets -- measured: zero semi-transparent
 * pixels along the bottom of a frame -- so without this they float. The pack's
 * objects carry their own shadows, drawn for a sun somewhere off the top-left,
 * which is what the daylight case matches.
 *
 * After dark the sun is not what is casting it. Every light in reach pulls the
 * shadow away from itself, weighted by how strongly it falls here, so walking past
 * a lamp swings the shadow around and stretches it as you leave. With no light
 * nearby there is nothing to cast one, and it fades to nothing -- which is the
 * point: an unlit figure with a crisp shadow looks worse than no shadow at all.
 */
// Tuned against the pack's own baked shadows, which are strong: a timid ellipse
// under a character reads as dirt when the lamp post beside it has a hard shadow.
const SHADOW = { rx: 8, ry: 3.2, reach: 30, minAlpha: 0.28, maxAlpha: 0.58 };

function shadowCast(wx, wy) {
  // Daylight: the sun the pack's own object shadows were drawn for, off to the
  // upper left, so a character agrees with the scenery around it.
  const day = 1 - state.night;
  let sx = -0.35 * day, sy = 0.62 * day, weight = day, lenAcc = 0.34 * day;

  if (state.night > 0) {
    const lights = allLights();
    for (let i = 0; i < lights.length; i++) {
      const l = lights[i];
      const d = Math.hypot(wx - l.x, wy - l.y);
      if (d > l.r) continue;
      const s = lightStrength(l, i) * (1 - d / l.r) * state.night;
      if (s <= 0.01) continue;
      const k = Math.max(d, 1);
      sx += ((wx - l.x) / k) * s;
      sy += ((wy - l.y) / k) * s * 0.55;   // squashed: the ground is seen at an angle
      // stand under the lamp and the shadow is a puddle; walk to the edge of its
      // pool and it stretches out behind you
      lenAcc += Math.min(1, d / (l.r * 0.55)) * s;
      weight += s;
    }
  }
  if (weight < 0.02) return null;          // nothing is casting it
  const len = lenAcc / weight;
  const m = Math.hypot(sx, sy) || 1;
  return { ux: sx / m, uy: sy / m, len,
           alpha: SHADOW.minAlpha + (SHADOW.maxAlpha - SHADOW.minAlpha)
                  * Math.min(1, weight) };
}

function drawPlayerShadow(ctx, ox, oy) {
  if (!charDef()) return;
  const cast = shadowCast(P.x, P.y);
  if (!cast) return;
  const Z = state.zoom;
  const reach = SHADOW.reach * cast.len;
  // anchored at the feet and thrown outward, rather than centred on the offset:
  // a shadow that detaches from the character reads as a smudge on the floor
  const cx = ox + (P.x + cast.ux * reach * 0.5) * Z;
  const cy = oy + (P.y + cast.uy * reach * 0.5) * Z;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(Math.atan2(cast.uy, cast.ux));
  ctx.beginPath();
  ctx.ellipse(0, 0, (SHADOW.rx + reach * 0.5) * Z, SHADOW.ry * Z, 0, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(6,8,14,${cast.alpha})`;
  ctx.filter = `blur(${(1.1 * Z).toFixed(1)}px)`;
  ctx.fill();
  ctx.restore();
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
function stepZoom(dir) {
  const i = ZOOMS.indexOf(state.zoom);
  const next = ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, i + dir))];
  if (i < 0 || next === state.zoom) return;
  state.zoom = next;
  $("#zoomLbl").textContent = next + "x";
  // zooming out shrinks the map under a camera that was aimed at the old extent
  clampCam(); draw();
}

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
    // sprites block from wherever they were placed, not only from the props layer
    for (const it of (L.items || [])) {
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
    if (L.role === "objects") continue;
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
// [minimum, default]. The maximum is not a fixed number of pixels: on a 5120px
// display a 620px cap is arbitrary, and the only real constraint is leaving the map
// something to live in.
const LAYOUT = { colL: [140, 280], colR: [140, 210] };
const MAP_MIN = 280;              // the map never shrinks below this

function colMax(which) {
  const other = $(PANEL[which === "colL" ? "colR" : "colL"]);
  const taken = other && !other.classList.contains("collapsed")
    ? other.getBoundingClientRect().width : 0;
  return Math.max(LAYOUT[which][0], innerWidth - taken - MAP_MIN - 24);
}

function setCol(which, px) {
  const v = Math.max(LAYOUT[which][0], Math.min(colMax(which), Math.round(px)));
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
  const width = off ? 0 : (+recall("wb." + which) || LAYOUT[which][1]);
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
      setCol(which, LAYOUT[which][1]);
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

  // the cap moves with the window, so a panel sized on a wide screen re-clamps
  // rather than squeezing the map out of existence on a narrow one
  addEventListener("resize", () => {
    for (const which of ["colL", "colR"])
      if (!collapsed(which)) {
        const now = $(PANEL[which]).getBoundingClientRect().width;
        if (now > colMax(which)) setCol(which, colMax(which));
      }
  });
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


/* ------------------------------------------------- light authoring */
const NEW_LIGHT = { r: 96, color: "#ffd9a0", intensity: 0.85, flicker: 0, when: "night" };

function lightAt(px, py) {
  // topmost first, and generous: the marker is small but the thing you are aiming
  // at is a light, so anywhere in its inner third counts
  for (let i = (M.lights || []).length - 1; i >= 0; i--) {
    const l = M.lights[i];
    const d = Math.hypot(px - l.x, py - l.y);
    if (d <= Math.max(10, l.r * 0.33)) return l;
  }
  return null;
}
function selectLight(l) {
  state.selLight = l;
  const box = $("#lightEdit");
  if (!box) return;
  box.hidden = !l;
  if (!l) return draw();
  $("#liR").value = l.r; $("#liRv").textContent = l.r + "px";
  $("#liC").value = l.color;
  $("#liW").value = l.when;
  $("#liF").value = Math.round(l.flicker * 100);
  draw();
}
function updateLightInfo() {
  const el = $("#lightInfo"); if (!el) return;
  const d = derivedLights().length, a = (M.lights || []).length;
  el.textContent = state.lightsIdx
    ? `${d} from sprites · ${a} placed by hand`
    : "lights.json missing — run tools/build_lights_index.py";
}
function setNight(v) {
  state.night = v / 100;
  $("#nightVal").textContent = v ? `${v}%` : "off";
  updateLightInfo();
  // flicker rides the existing animation timer: drawLighting reports it the same
  // way an animated sprite does, so there is no second clock to keep in step
  draw();
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
  loadLightsIndex().then(updateLightInfo);
  $("#nightSlider").oninput = e => setNight(+e.target.value);
  const editLight = (fn) => {
    const l = state.selLight; if (!l) return;
    fn(l); draw();
  };
  $("#liR").oninput = e => editLight(l => {
    l.r = +e.target.value; $("#liRv").textContent = l.r + "px"; });
  $("#liC").oninput = e => editLight(l => { l.color = e.target.value; });
  $("#liW").onchange = e => editLight(l => { l.when = e.target.value; });
  $("#liF").oninput = e => editLight(l => { l.flicker = +e.target.value / 100; });
  $("#liDel").onclick = () => {
    const l = state.selLight; if (!l) return;
    snapshot();
    M.lights = M.lights.filter(x => x !== l);
    selectLight(null); updateLightInfo();
  };
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
  map.onwheel = ev => { ev.preventDefault(); stepZoom(ev.deltaY < 0 ? 1 : -1); };

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
    if (k === "-") stepZoom(-1);
    if (k === "=" || k === "+") stepZoom(1);
  });
  addEventListener("keyup", e => keys.delete(e.key.toLowerCase()));
  addEventListener("resize", draw);

  loadSheets().then(() => { draw(); });
  loadSingles().catch(() => {});
  loadChars();
  refreshMapList();
}
init();
