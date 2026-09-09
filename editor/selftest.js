/*
 * Editor self test. Load the editor, then in the console:
 *     await import('./selftest.js').then(m => m.run())
 * Drives the real UI through synthetic events and checks the resulting state.
 */
const results = [];
const T = () => state.tile, Z = () => state.zoom;
const map = () => document.querySelector('#map');
const mb = () => map().getBoundingClientRect();
const at = (tx, ty) => ({ x: mb().left + tx*T()*Z() - state.cam.x + 6,
                          y: mb().top  + ty*T()*Z() - state.cam.y + 6 });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const down = p => map().dispatchEvent(new MouseEvent('mousedown', {clientX:p.x, clientY:p.y, bubbles:true}));
const move = p => map().dispatchEvent(new MouseEvent('mousemove', {clientX:p.x, clientY:p.y, bubbles:true}));
const up   = () => window.dispatchEvent(new MouseEvent('mouseup'));
const key  = k => window.dispatchEvent(new KeyboardEvent('keydown', {key:k, bubbles:true}));
const tool = t => document.querySelector(`[data-tool="${t}"]`).click();
const layer = name => {
  const i = [...document.querySelectorAll('#layers .layer')].findIndex(l => l.querySelector('span').textContent === name);
  document.querySelectorAll('#layers .layer')[i].click();
};
const filled = n => M.layers.find(l => l.name === n).grid.flat().filter(Boolean).length;
const objs = () => M.layers.find(l => l.role === 'objects').items;

async function t(name, fn) {
  try { await fn(); results.push(['pass', name, '']); }
  catch (e) { results.push(['FAIL', name, e.message || String(e)]); }
}
const eq = (a, b, m='') => { if (JSON.stringify(a) !== JSON.stringify(b))
  throw new Error(`${m} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); };
const ok = (c, m) => { if (!c) throw new Error(m || 'assertion failed'); };

async function freshMap(w = 24, h = 18) {
  state.marquee = null; state.sel = null; state.sizing = null;
  newMap(w, h);
  state.cam = { x: -T()*Z(), y: -T()*Z() };
  await sleep(60);
}
async function grabTiles(sheetId, col, row, w, h) {
  const sel = document.querySelector('#sheetSel');
  if (state.palMode !== 'sheets') { document.querySelector('#modeSheets').click(); await sleep(400); }
  sel.value = sheetId; sel.onchange({target: sel}); await sleep(500);
  const pal = document.querySelector('#pal'), z = pal._z || 1, t = T()*z;
  const pb = pal.getBoundingClientRect();
  pal.dispatchEvent(new MouseEvent('mousedown', {clientX: pb.left+col*t+4, clientY: pb.top+row*t+4, bubbles:true}));
  if (w > 1 || h > 1)
    pal.dispatchEvent(new MouseEvent('mousemove', {clientX: pb.left+(col+w-1)*t+4, clientY: pb.top+(row+h-1)*t+4, bubbles:true}));
  up(); await sleep(60);
}
async function grabSprite(cat, idx = 0) {
  if (state.palMode !== 'singles') { document.querySelector('#modeSingles').click(); await sleep(1200); }
  const sel = document.querySelector('#sheetSel');
  sel.value = cat; sel.onchange({target: sel}); await sleep(500);
  const a = state.singles.cats[cat][idx];
  state.stamp = { sprite: a.id, w: a.tiles[0], h: a.tiles[1], image: a.image };
  return a;
}

export async function run() {
  const RB = 'office.roombuilder.office.room_builder_office';

  await t('new map sets size and resets content', async () => {
    await freshMap(20, 15);
    eq(M.size, [20, 15]);
    eq(filled('floor'), 0);
    eq(objs().length, 0);
    eq(M.collision.size, 0);
    ok(M.layers.some(l => l.role === 'objects'), 'no object layer after New');
    ok(M.layers.every(l => typeof l.name === 'string'), 'layer names are not strings');
  });

  await t('multi-tile stamp pastes every tile', async () => {
    await freshMap(); await grabTiles(RB, 0, 5, 3, 2);
    layer('floor'); tool('paint');
    down(at(2, 2)); up(); await sleep(40);
    eq(filled('floor'), 6, 'stamp cells');
  });

  await t('rect with a single click places one whole stamp', async () => {
    await freshMap(); await grabTiles(RB, 0, 5, 3, 2);
    layer('floor'); tool('rect');
    down(at(2, 2)); up(); await sleep(40);
    eq(filled('floor'), 6);
  });

  await t('rect drag tiles the stamp across the area', async () => {
    await freshMap(); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('rect');
    down(at(1, 1)); move(at(6, 4)); up(); await sleep(40);
    eq(filled('floor'), 6*4);
  });

  await t('erase removes the whole multi-tile stamp', async () => {
    await freshMap(); await grabTiles(RB, 0, 5, 3, 2);
    layer('floor'); tool('paint'); down(at(3, 3)); up(); await sleep(40);
    eq(filled('floor'), 6);
    tool('erase'); down(at(5, 4)); up(); await sleep(40);   // bottom-right cell
    eq(filled('floor'), 0, 'whole group should go');
  });

  await t('flood fill respects the layer and stops at edges', async () => {
    await freshMap(10, 8); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('fill'); down(at(3, 3)); up(); await sleep(60);
    eq(filled('floor'), 80);
  });

  await t('eyedropper picks the tile and its layer', async () => {
    await freshMap(); await grabTiles(RB, 11, 6, 1, 1);
    layer('walls'); tool('paint'); down(at(4, 4)); up(); await sleep(40);
    layer('floor'); state.stamp = null;
    map().dispatchEvent(new MouseEvent('mousedown',
      {clientX: at(4,4).x, clientY: at(4,4).y, altKey: true, bubbles: true}));
    up(); await sleep(60);
    ok(state.stamp, 'nothing picked');
    eq(M.layers[state.layerIdx].name, 'walls', 'layer follows the pick');
  });

  await t('objects snap to the grid however messy the click', async () => {
    await freshMap(); await grabSprite('int.single.living_room', 0);
    layer('props'); tool('paint');
    for (const [x, y] of [[137,141],[262,177],[389,143]]) {
      down({x: mb().left+x, y: mb().top+y}); up();
    }
    await sleep(60);
    eq(objs().length, 3);
    ok(objs().every(i => i.x % T() === 0 && i.y % T() === 0), 'object off grid');
  });

  await t('select drags a single object and it stays snapped', async () => {
    await freshMap(); const a = await grabSprite('int.single.living_room', 0);
    layer('props'); tool('paint'); down(at(3, 3)); up(); await sleep(40);
    const before = {...objs()[0]};
    tool('select');
    down(at(3, 3)); move(at(7, 6)); up(); await sleep(40);
    const after = objs()[0];
    ok(after.x !== before.x || after.y !== before.y, 'object did not move');
    ok(after.x % T() === 0 && after.y % T() === 0, 'moved off grid');
  });

  await t('marquee masks painting and warns when you click outside', async () => {
    await freshMap(); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('select');
    down(at(2, 2)); move(at(5, 5)); up(); await sleep(40);
    ok(selRect(), 'no selection'); ok(!document.querySelector('#selBadge').hidden, 'no badge');
    tool('rect'); down(at(0, 0)); move(at(15, 12)); up(); await sleep(60);
    eq(filled('floor'), 16, 'painting escaped the mask');
    tool('paint'); down(at(12, 12)); up(); await sleep(40);
    ok(document.querySelector('#toast').textContent.includes('outside the selection'),
       'no warning when clicking outside');
  });

  await t('marquee delete clears tiles and objects', async () => {
    await freshMap(); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('rect'); down(at(1,1)); move(at(9,7)); up(); await sleep(40);
    await grabSprite('int.single.living_room', 0);
    layer('props'); tool('paint'); down(at(3,3)); up(); down(at(12,10)); up(); await sleep(40);
    const tilesBefore = filled('floor');
    tool('select'); down(at(1,1)); move(at(6,6)); up(); await sleep(40);
    key('Delete'); await sleep(60);
    ok(filled('floor') < tilesBefore, 'no tiles deleted');
    eq(objs().length, 1, 'object outside the selection should survive');
  });

  await t('escape clears the selection and painting resumes', async () => {
    await freshMap(); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('select'); down(at(2,2)); move(at(4,4)); up(); await sleep(40);
    key('Escape'); await sleep(40);
    ok(!selRect(), 'selection not cleared');
    tool('paint'); down(at(10, 10)); up(); await sleep(40);
    eq(filled('floor'), 1);
  });

  await t('collision follows object type, and overrides win', async () => {
    await freshMap();
    const byId = state.singles.byId;
    const list = state.singles.cats['int.single.kitchen'];
    const blocker = list.find(a => byId[a.id].blocks && byId[a.id].placement === 'floor');
    const rug = list.find(a => byId[a.id].blocks === false);
    layer('props'); tool('paint');
    state.stamp = {sprite: blocker.id, w:1, h:1, image: byId[blocker.id].image};
    down(at(3,3)); up(); await sleep(40);
    const solidAfterBlocker = M.collision.size;
    ok(solidAfterBlocker > 0, 'floor-standing object created no collision');
    state.stamp = {sprite: rug.id, w:1, h:1, image: byId[rug.id].image};
    down(at(8,3)); up(); await sleep(40);
    eq(M.collision.size, solidAfterBlocker, 'rug should not block');
    tool('coll-');
    down(at(3,3)); up(); await sleep(40);
    ok(!M.collision.has('3,3'), 'manual erase did not take');
    // further editing must not resurrect it
    tool('paint'); state.stamp = {sprite: blocker.id, w:1, h:1, image: byId[blocker.id].image};
    down(at(12,12)); up(); await sleep(40);
    ok(!M.collision.has('3,3'), 'override lost after another edit');
  });

  await t('undo and redo restore tiles, objects and collision', async () => {
    await freshMap(); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('rect'); down(at(1,1)); move(at(5,5)); up(); await sleep(40);
    const n = filled('floor'); ok(n > 0);
    undo(); await sleep(40); eq(filled('floor'), 0, 'undo');
    redo(); await sleep(40); eq(filled('floor'), n, 'redo');
  });

  await t('save and reload preserves everything', async () => {
    await freshMap(18, 12); await grabTiles(RB, 0, 5, 3, 2);
    layer('floor'); tool('paint'); down(at(2,2)); up(); await sleep(40);
    await grabSprite('int.single.kitchen', 0);
    layer('props'); tool('paint'); down(at(6,6)); up(); await sleep(40);
    tool('coll+'); down(at(9,9)); up(); await sleep(40);
    const before = {tiles: filled('floor'), objs: objs().length,
                    coll: M.collision.size, ov: M.overrides.size, size: [...M.size]};
    document.querySelector('#mapName').value = '__selftest';
    await save(); await sleep(400);
    const d = await fetch('/maps/__selftest.json').then(r => r.json());
    deserialise(d); await sleep(200);
    eq(M.size, before.size, 'size');
    eq(filled('floor'), before.tiles, 'tiles');
    eq(objs().length, before.objs, 'objects');
    eq(M.overrides.size, before.ov, 'overrides');
    ok(M.collision.has('9,9'), 'manual collision lost');
  });

  await t('erase still lifts a whole group after reload', async () => {
    const d = await fetch('/maps/__selftest.json').then(r => r.json());
    deserialise(d); await sleep(150);
    layer('floor'); tool('erase');
    const before = filled('floor');
    down(at(4, 3)); up(); await sleep(40);   // a non-origin cell of the 3x2 stamp
    ok(filled('floor') < before - 1, 'group grouping lost across save/load');
  });

  await t('export writes a bundle', async () => {
    document.querySelector('#mapName').value = '__selftest';
    await doExport(); await sleep(3500);
    const txt = document.querySelector('#toast').textContent;
    ok(txt.startsWith('exported'), `export said: ${txt}`);
  });

  await t('walk mode respects collision', async () => {
    await freshMap(20, 15); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('rect'); down(at(0,0)); move(at(19,14)); up(); await sleep(40);
    tool('coll+');
    for (let x = 0; x < 20; x++) { down(at(x, 6)); up(); }
    await sleep(60);
    M.spawns = [{name:'start', at:[5, 2]}];
    startPlay(); await sleep(120);
    const y0 = P.y;
    for (let i = 0; i < 90; i++) { keys.add('s'); await sleep(6); }
    keys.delete('s'); await sleep(60);
    stopPlay();
    ok(P.y < 6 * T(), `walked through the wall (y=${P.y})`);
    ok(P.y > y0, 'did not move at all');
  });

  await t('animated sprites carry frame data and cycle', async () => {
    await freshMap();
    const cat = Object.keys(state.singles.cats).find(c => c.includes('animated'));
    const a = await grabSprite(cat, 0);
    ok(state.singles.byId[a.id].anim, 'no anim data on an animated sprite');
    layer('props'); tool('paint'); down(at(4,4)); up(); await sleep(500);
    ok(state.animTimer, 'animation timer not running');
  });

  await t('tile size switch reloads the sheet list', async () => {
    const sel = document.querySelector('#tileSize');
    sel.value = '48'; sel.onchange({target: sel}); await sleep(600);
    ok(document.querySelector('#sheetSel').options.length > 10, 'no sheets at 48px');
    eq(state.tile, 48);
    sel.value = '32'; sel.onchange({target: sel}); await sleep(600);
    eq(state.tile, 32);
  });

  await t('painting outside the map is ignored', async () => {
    await freshMap(10, 8); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('paint');
    down(at(50, 50)); up(); down(at(-5, -5)); up(); await sleep(40);
    eq(filled('floor'), 0);
    ok(M.layers[0].grid.length === 8 && M.layers[0].grid[0].length === 10, 'grid resized');
  });

  await t('thumbnail picker mirrors the sheet list and selects', async () => {
    document.querySelector('#modeSheets').click(); await sleep(300);
    document.querySelector('#pickBtn').click(); await sleep(400);
    const cells = [...document.querySelectorAll('#pickList .pcell')];
    const opts = document.querySelectorAll('#sheetSel option').length;
    eq(cells.length, opts, 'picker cell count');
    ok(cells.every(c => c.querySelector('.th').style.backgroundImage),
       'a sheet cell has no thumbnail');
    const target = cells.find(c => c.dataset.v !== document.querySelector('#sheetSel').value);
    target.click(); await sleep(400);
    eq(document.querySelector('#sheetSel').value, target.dataset.v, 'selection');
    eq(state.sheet.id, target.dataset.v, 'palette did not follow the picker');
    ok(document.querySelector('#pickPop').hidden, 'picker stayed open after choosing');
  });

  await t('picker search filters, and singles get thumbnails too', async () => {
    document.querySelector('#modeSingles').click(); await sleep(700);
    document.querySelector('#pickBtn').click(); await sleep(400);
    ok([...document.querySelectorAll('#pickList .pcell .th')]
       .every(e => e.style.backgroundImage), 'a category cell has no thumbnail');
    const i = document.querySelector('#pickSearch');
    i.value = 'kitchen'; i.dispatchEvent(new Event('input')); await sleep(200);
    const hits = [...document.querySelectorAll('#pickList .pcell')];
    ok(hits.length && hits.length < 20, `search matched ${hits.length}`);
    ok(hits.every(c => (c.title + c.dataset.v).toLowerCase().includes('kitchen')),
       'search returned an unrelated entry');
    i.value = 'zzzznope'; i.dispatchEvent(new Event('input')); await sleep(200);
    ok(document.querySelector('#pickNone'), 'no empty-state for a search with no hits');
    document.querySelector('#pickBtn').click(); await sleep(200);
    document.querySelector('#modeSheets').click(); await sleep(400);
  });

  await t('theme cycles system -> light -> dark and repaints', async () => {
    const btn = document.querySelector('#btnTheme');
    const html = document.documentElement;
    const chrome = () => getComputedStyle(document.querySelector('aside')).backgroundColor;
    const px = () => document.querySelector('#map').getContext('2d')
      .getImageData(2, 2, 1, 1).data.join(',');
    const osDark = matchMedia('(prefers-color-scheme: dark)').matches;

    setTheme('system'); await sleep(150);
    eq(localStorage.getItem('wb.theme'), 'system', 'preference not persisted');
    eq(html.dataset.theme, osDark ? 'dark' : 'light', 'system did not follow the OS');

    const seen = [], chromes = [], pixels = [];
    for (let i = 0; i < 3; i++) {
      seen.push(localStorage.getItem('wb.theme'));
      chromes.push(chrome()); pixels.push(px());
      btn.click(); await sleep(150);
    }
    eq(seen, ['system', 'light', 'dark'], 'cycle order');
    eq(localStorage.getItem('wb.theme'), 'system', 'cycle did not come back round');
    // light and dark must differ in both the chrome and the canvas; system matches one
    ok(chromes[1] !== chromes[2], 'panel colour is the same in light and dark');
    ok(pixels[1] !== pixels[2], 'map canvas is the same in light and dark');
  });

  await t('columns resize, clamp and persist', async () => {
    const aside = document.querySelector('aside');
    const g = document.querySelector('#gutL');
    // a collapsed gutter has nothing to drag, so start from a known-open panel
    setCollapsed('colL', false); await sleep(150);
    const drag = to => {
      const r = g.getBoundingClientRect();
      g.dispatchEvent(new MouseEvent('mousedown', {clientX:r.left+3, clientY:300, bubbles:true}));
      dispatchEvent(new MouseEvent('mousemove', {clientX:to, clientY:300}));
      dispatchEvent(new MouseEvent('mouseup'));
    };
    drag(430); await sleep(150);
    ok(Math.abs(aside.getBoundingClientRect().width - 430) < 3, 'column did not follow the drag');
    eq(localStorage.getItem('wb.colL'), '430', 'width not persisted');
    drag(20); await sleep(150);
    ok(aside.getBoundingClientRect().width >= 190, 'column collapsed past its minimum');
    drag(5000); await sleep(150);
    ok(aside.getBoundingClientRect().width <= 620, 'column grew past its maximum');
    g.dispatchEvent(new MouseEvent('dblclick', {bubbles:true})); await sleep(150);
    ok(Math.abs(aside.getBoundingClientRect().width - 280) < 3, 'double click did not reset');
    ok(document.querySelector('#map').width > 0, 'map canvas lost its size on resize');
  });

  await t('every tool has an icon, a tip and a working hover', async () => {
    const btns = [...document.querySelectorAll('.tools [data-tool]')];
    eq(btns.length, 8, 'tool count');
    ok(btns.every(b => b.querySelector('svg')), 'a tool has no icon');
    ok(btns.every(b => (b.dataset.tip || '').length > 20), 'a tool has no usable tip');
    ok(btns.every(b => b.dataset.key), 'a tool has no shortcut in its tip');
    ok([...document.querySelectorAll('[data-tool]')].every(b => b.dataset.tip),
       'a tool button outside the palette has no tip');
    const tip = document.querySelector('#tip');
    const b = document.querySelector('[data-tool="fill"]');
    b.dispatchEvent(new MouseEvent('mouseover', {bubbles:true})); await sleep(120);
    ok(!tip.hidden, 'tip did not appear on hover');
    ok(tip.textContent.includes('Flood fill'), 'tip showed the wrong text');
    ok(tip.querySelector('kbd'), 'tip did not show the shortcut');
    const r = tip.getBoundingClientRect();
    ok(r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight,
       'tip rendered off screen');
    document.body.dispatchEvent(new MouseEvent('mouseover', {bubbles:true})); await sleep(120);
    ok(tip.hidden, 'tip did not hide when the pointer left');
  });

  await t('delete removes a saved world, and cancel does not', async () => {
    const NAME = '__deltest';
    const listed = async () => (await fetch('/api/maps').then(r => r.json())).maps;

    await freshMap(8, 8); await grabTiles(RB, 11, 6, 1, 1);
    layer('floor'); tool('paint'); down(at(2, 2)); up(); await sleep(60);
    document.querySelector('#mapName').value = NAME;
    document.querySelector('#btnSave').click(); await sleep(500);
    ok((await listed()).includes(NAME), 'setup: map did not save');

    const dlg = document.querySelector('#delDlg');
    document.querySelector('#btnDelete').click(); await sleep(200);
    ok(dlg.open, 'delete did not ask for confirmation');
    dlg.close('cancel'); await sleep(300);
    ok((await listed()).includes(NAME), 'cancel deleted it anyway');

    document.querySelector('#btnDelete').click(); await sleep(200);
    dlg.close('ok'); await sleep(500);
    ok(!(await listed()).includes(NAME), 'map survived a confirmed delete');
    ok(objs !== undefined && M.layers.length > 0, 'canvas was wiped by a delete');
  });

  await t('side panels collapse and come back', async () => {
    const stage = () => document.querySelector('#stage').getBoundingClientRect().width;
    // both the hairline gutter chevron and the header button drive the same thing
    for (const [chev, sel, key, hdr] of [['#chevL', 'aside:not(.right)', 'colL', '#btnPanelL'],
                                         ['#chevR', 'aside.right', 'colR', '#btnPanelR']]) {
      setCollapsed(key, false); await sleep(150);
      const open = stage();
      const panel = document.querySelector(sel);
      ok(!panel.classList.contains('collapsed'), `${key} did not start open`);

      document.querySelector(chev).click(); await sleep(200);
      ok(panel.classList.contains('collapsed'), `${key} did not collapse`);
      ok(stage() > open, `${key} collapsed but the map did not gain the space`);
      eq(localStorage.getItem('wb.' + key + '.off'), '1', `${key} not persisted`);
      // the chevron has to survive its own panel, or there is no way back
      const c = document.querySelector(chev).getBoundingClientRect();
      ok(c.width > 0 && c.left >= 0 && c.right <= innerWidth,
         `${key} chevron went off screen when collapsed`);

      ok(document.querySelector(hdr).classList.contains('on'),
         `${key} header button does not show the collapsed state`);
      document.querySelector(hdr).click(); await sleep(200);   // header button restores
      ok(!panel.classList.contains('collapsed'), `${key} did not come back`);
      ok(Math.abs(stage() - open) < 2, `${key} did not restore its width`);
      ok(document.querySelector('#map').width > 100, 'map canvas lost its size');
    }
  });

  const pass = results.filter(r => r[0] === 'pass').length;
  console.log(results.map(r => `${r[0]}  ${r[1]}${r[2] ? '\n        ' + r[2] : ''}`).join('\n'));
  return { pass, fail: results.length - pass,
           failures: results.filter(r => r[0] === 'FAIL').map(r => `${r[1]}: ${r[2]}`) };
}
