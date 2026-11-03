import { parseSave, screenshotImageData, SaveError } from './ess.js';
import { evaluate, counters, EDITION_NAMES, DLC_NAMES } from './collect.js';

const KINDS = {
  mask: { name: 'Dragon Priest Masks', one: 'Dragon Priest Mask' },
  stone: { name: 'Stones of Barenziah', one: 'Stone of Barenziah' },
  artifact: { name: 'Daedric Artifacts', one: 'Daedric Artifact' },
  claw: { name: 'Dragon Claws', one: 'Dragon Claw' },
  blackbook: { name: 'Black Books', one: 'Black Book' },
  shout: { name: 'Words of Power', one: 'Word of Power' },
  paragon: { name: 'Paragons', one: 'Paragon' },
  jiub: { name: "Jiub's Opus", one: "Page of Jiub's Opus" },
  kagrumez: { name: 'Kagrumez Gems', one: 'Kagrumez Resonance Gem' },
  jar: { name: 'Insects in Jars', one: 'Insect in a Jar' },
  trophy: { name: 'Guild Trophies', one: 'Thieves Guild Trophy' },
};

// app.js sits at <root>/js/, so this resolves assets the same from the landing page and from a collectible page.
const BASE = new URL('../', import.meta.url);
const asset = path => new URL(path, BASE).href;
// A collectible page declares its own kind; the landing page can be sent one with ?kind=<key>.
const linkedKind = document.body.dataset.kind || new URLSearchParams(location.search).get('kind');

const $ = id => document.getElementById(id);
const el = (tag, { dataset, ...props } = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  if (dataset) Object.assign(e.dataset, dataset);
  e.append(...kids.filter(k => k != null));
  return e;
};
const icon = kind => el('img', { className: 'icon', src: asset(`img/${kind}.png`), alt: '', draggable: false });
const dlcIcon = dlc => (dlc === 'base' ? null : el('img', { className: 'dlc', src: asset(`img/${dlc}.png`), alt: DLC_NAMES[dlc], title: DLC_NAMES[dlc], draggable: false }));

const state = {
  data: null,
  result: null,
  kinds: new Set([Object.hasOwn(KINDS, linkedKind) ? linkedKind : 'mask']),
  showFound: false,
  selected: new Set(),
  world: 'skyrim',
  view: { s: 1, x: 0, y: 0 },
  shown: false,
};
const st = i => state.result.state.get(i.id);

const dataReady = fetch(asset('data/collectibles.json')).then(r => r.json()).then(d => (state.data = d));

// ---------- file input ----------

const drop = $('drop');
const fileInput = $('file');
function choose() {
  fileInput.value = '';
  fileInput.click();
}

drop.addEventListener('click', e => { if (!e.target.closest('.copy')) choose(); });
drop.addEventListener('keydown', e => { if (e.target === drop && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); choose(); } });
fileInput.addEventListener('change', () => fileInput.files[0] && load(fileInput.files[0]));
$('reload').addEventListener('click', choose);

for (const b of document.querySelectorAll('.copy')) {
  b.addEventListener('click', async () => {
    await navigator.clipboard.writeText(b.dataset.path);
    b.textContent = 'Copied';
    setTimeout(() => (b.textContent = 'Copy'), 1500);
  });
}
for (const t of ['dragenter', 'dragover']) window.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); });
for (const t of ['dragleave', 'drop']) window.addEventListener(t, e => { e.preventDefault(); drop.classList.remove('over'); });
window.addEventListener('drop', e => e.dataTransfer.files[0] && load(e.dataTransfer.files[0]));

async function load(file) {
  $('error').hidden = true;
  try {
    const [bytes] = await Promise.all([file.arrayBuffer().then(b => new Uint8Array(b)), dataReady]);
    const save = parseSave(bytes);
    const result = await evaluate(save, state.data);
    show(save, bytes, result);
  } catch (err) {
    console.error(err);
    $('error').textContent = err instanceof SaveError ? err.message : `Could not read that file: ${err.message}`;
    $('error').hidden = false;
  }
}

// ---------- corner menus ----------

for (const box of document.querySelectorAll('.corner')) {
  const btn = box.querySelector('.corner-btn');
  const pop = box.querySelector('.corner-pop');
  const set = open => { pop.hidden = !open; btn.setAttribute('aria-expanded', open); };
  btn.addEventListener('click', () => set(pop.hidden));
  box.querySelector('.pop-close')?.addEventListener('click', () => set(false));
  addEventListener('pointerdown', e => { if (!box.contains(e.target)) set(false); });
  addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
}

const DYSLEXIC_KEY = 'skyrim-dyslexic';
const dyslexicSwitch = $('dyslexic');
let dyslexicFont = 'idle';
let wantDyslexic = false;
try { wantDyslexic = localStorage.getItem(DYSLEXIC_KEY) === '1'; } catch {}

function applyDyslexic() {
  dyslexicSwitch.setAttribute('aria-checked', wantDyslexic);
  document.body.classList.toggle('is-dyslexic', wantDyslexic && dyslexicFont === 'ready');
  dyslexicSwitch.firstChild.textContent = wantDyslexic && dyslexicFont === 'loading' ? 'Dyslexia-friendly font — fetching…' : 'Dyslexia-friendly font';
  if (!wantDyslexic || dyslexicFont !== 'idle') return;
  dyslexicFont = 'loading';
  new FontFace('OpenDyslexic', `url(${asset('fonts/OpenDyslexic-Regular.otf')})`).load()
    .then(face => { document.fonts.add(face); dyslexicFont = 'ready'; })
    .catch(() => { dyslexicFont = 'failed'; })
    .finally(applyDyslexic);
}

dyslexicSwitch.addEventListener('click', () => {
  wantDyslexic = !wantDyslexic;
  try { localStorage.setItem(DYSLEXIC_KEY, wantDyslexic ? '1' : '0'); } catch {}
  applyDyslexic();
});
applyDyslexic();

// ---------- results ----------

function kindsPresent() {
  return Object.keys(KINDS).filter(k => state.result.items.some(i => i.kind === k));
}

function show(save, bytes, result) {
  state.result = result;
  state.save = save;
  const h = save.header;
  $('edition').textContent = EDITION_NAMES[h.edition];
  $('map-notice').hidden = h.edition !== 'le';
  $('dlcs').replaceChildren(...Object.keys(DLC_NAMES).filter(d => result.ctx.dlc[d])
    .map(d => el('span', { className: 'dlc-badge' }, dlcIcon(d), d === 'saints' && result.ctx.anniversary ? 'Anniversary Edition' : DLC_NAMES[d])));
  $('pc-name').textContent = h.name;
  $('pc-line').textContent = `Level ${h.level} · ${h.location}`;
  $('save-line').textContent = `Saved ${h.savedAt.toLocaleString()} · Save ${h.saveNum}`;
  const shot = $('shot');
  if (h.screenshot) {
    shot.width = h.screenshot.width;
    shot.height = h.screenshot.height;
    shot.getContext('2d').putImageData(screenshotImageData(bytes, h.screenshot), 0, 0);
  } else {
    shot.width = shot.height = 0;
  }

  const game = counters(save, state.data);
  const warnings = $('warnings');
  warnings.replaceChildren();
  const stones = result.items.filter(i => i.kind === 'stone' && st(i) === 'found').length;
  if (game.stone != null && game.stone !== stones) {
    warnings.append(el('p', { className: 'warn', textContent:
      `The game's own Stones of Barenziah counter says ${game.stone}, but ${stones} are marked collected in this save. A mod or console command may have changed some of them.` }));
  }

  const present = kindsPresent();
  if (![...state.kinds].some(k => present.includes(k))) state.kinds = new Set([present[0]]);
  drop.hidden = true;
  $('about').hidden = true;
  $('results').hidden = false;
  renderWalker(game);
  renderTallies();
  renderChips();
  renderMapTabs();
  if (!state.shown) state.shown = true;
  setWorld(worlds().includes(state.world) ? state.world : 'skyrim');
  render();
}

function renderTallies() {
  $('tallies').replaceChildren(...kindsPresent().map(k => {
    const all = state.result.items.filter(i => i.kind === k);
    const got = all.filter(i => st(i) === 'found').length;
    const lost = all.filter(i => st(i) === 'failed').length;
    const left = all.length - got - lost;
    const sub = [left ? `${left} still to find` : 'All found', lost ? `${lost} lost` : null].filter(Boolean).join(' · ');
    const help = k === 'artifact' && state.walker
      ? el('button', { type: 'button', className: 'tally-help', title: 'Oblivion Walker', ariaLabel: 'Oblivion Walker', textContent: '?', onclick: () => $('walker').showModal() })
      : null;
    return el('div', { className: 'tally panel', dataset: { kind: k } },
      el('div', { className: 'tally-head' }, icon(k), KINDS[k].name, help),
      el('div', { className: 'tally-num', innerHTML: `${got}<small> / ${all.length}</small>` }),
      el('div', { className: `tally-sub${lost ? ' has-lost' : ''}`, textContent: sub }),
      el('div', { className: 'bar' }, el('i', { style: `width:${(got / all.length) * 100}%` }), el('b', { style: `width:${(lost / all.length) * 100}%` })));
  }));
}

$('walker').addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.close(); });

// The Oblivion Walker achievement keeps its own count, which drifts from the artifacts held for known reasons.
function renderWalker(game) {
  const box = $('walker');
  box.replaceChildren();
  const a = game.artifacts;
  state.walker = !!a;
  if (!a) return;
  const r = state.result;
  const found = r.items.filter(i => i.kind === 'artifact' && st(i) === 'found');
  const has = name => found.some(i => i.name === name);
  const notes = [];
  if (has("Savior's Hide") && has('Ring of Hircine')) {
    notes.push('Savior\'s Hide and the uncursed Ring of Hircine both counted, so Hircine\'s quest added two.');
  }
  if (state.save.header.edition === 'le' && r.ctx.dlc.dawnguard && has('Masque of Clavicus Vile')) {
    notes.push("On the 2011 edition with Dawnguard, the Masque of Clavicus Vile never counts: Dawnguard's copy of A Daedra's Best Friend lost its link to the achievement. Skyrim Special Edition and VR fixed it.");
  }
  const done = a.count >= a.max;
  const close = el('button', { type: 'button', className: 'pop-close', ariaLabel: 'Close', textContent: '×', onclick: () => box.close() });
  box.append(
    el('div', { className: 'walker-head' }, icon('artifact'), el('span', { id: 'walker-title', textContent: 'Oblivion Walker' }),
      el('span', { className: 'walker-state', textContent: done ? 'Achievement earned' : `${a.max - a.count} to go` }), close),
    el('div', { className: 'walker-num', innerHTML: `${a.count}<small> / ${a.max} counted by the game</small>` }),
    el('div', { className: 'bar' }, el('i', { style: `width:${Math.min(1, a.count / a.max) * 100}%` })),
    el('p', { className: 'walker-sub', textContent: `You have collected ${found.length} of the ${r.items.filter(i => i.kind === 'artifact').length} Daedric artifacts on this page. The game keeps its own running count for the achievement, which it adds to as each quest hands an artifact over.` }),
    notes.length ? el('ul', { className: 'walker-notes' }, ...notes.map(n => el('li', { textContent: n }))) : null);
}

function renderChips() {
  $('kind-chips').replaceChildren(...kindsPresent().map(k => {
    const b = el('button', { type: 'button', className: 'chip', dataset: { kind: k } }, icon(k), KINDS[k].name);
    b.setAttribute('aria-pressed', state.kinds.has(k));
    b.addEventListener('click', () => {
      state.kinds.has(k) ? state.kinds.delete(k) : state.kinds.add(k);
      b.setAttribute('aria-pressed', state.kinds.has(k));
      render();
    });
    return b;
  }));
}

$('show-found').addEventListener('change', e => { state.showFound = e.target.checked; render(); });

function title(i) {
  if (i.kind === 'shout') return i.source === 'wall' ? `${i.shoutName} word wall` : `${i.shoutName}: ${i.name}`;
  if (i.kind === 'jiub') return `Jiub's Opus, ${i.name.toLowerCase()}`;
  if (i.kind === 'stone' || i.kind === 'kagrumez') return i.area || i.near?.name || KINDS[i.kind].one;
  return i.name;
}

function where(i) {
  const bits = [];
  if (i.kind === 'shout' && i.translation) bits.push(`“${i.translation}”, word ${i.wordIndex} of 3`);
  if (i.kind === 'artifact') bits.push(`${i.prince} · ${i.source}`);
  if (i.holder) bits.push(`Carried by ${i.holder}`);
  if (i.area && !['stone', 'kagrumez'].includes(i.kind) && i.kind !== 'artifact') bits.push(i.area);
  if (i.realm) bits.push('Separate realm');
  else if (i.near) {
    const rel = i.near.metres < 25 ? `at ${i.near.name}` : `${i.near.metres} m ${i.near.dir} of ${i.near.name}`;
    bits.push(i.viaDoor ? `Entrance ${rel}` : rel[0].toUpperCase() + rel.slice(1));
  } else if (i.map && !i.area) bits.push(state.data.worlds[i.map.world].name);
  return bits.join(' · ');
}

const sortKey = i => (i.kind === 'shout' ? `${i.shoutName}|${i.source === 'wall' ? `0${i.area ?? ''}` : `1${i.wordIndex}`}` : title(i));

function visible() {
  return state.result.items.filter(i => state.kinds.has(i.kind) && (state.showFound || st(i) !== 'found'));
}

function render() {
  const items = visible().sort((a, b) => Object.keys(KINDS).indexOf(a.kind) - Object.keys(KINDS).indexOf(b.kind) || sortKey(a).localeCompare(sortKey(b)) || a.id.localeCompare(b.id));
  const missing = items.filter(i => st(i) === 'missing').length;
  const lost = items.filter(i => st(i) === 'failed').length;
  const found = items.length - missing - lost;
  $('list-count').textContent = !state.kinds.size ? 'Pick a collectible type above.'
    : items.length ? [`${missing} missing`, lost ? `${lost} lost` : null, state.showFound ? `${found} collected` : null].filter(Boolean).join(', ')
    : 'All found.';
  $('list').replaceChildren(...items.map(listItem));
  renderPins(items);
}

const BADGES = { found: ['ok', 'collected'], failed: ['lost', 'lost'] };

function listItem(i) {
  const s = st(i);
  const li = el('li', { className: `item ${s}${state.selected.has(i.id) ? ' active' : ''}`, id: `item-${i.id}`, dataset: { kind: i.kind } },
    el('div', { className: 'item-top' },
      icon(i.kind),
      el('span', { className: 'item-title', textContent: title(i) }),
      dlcIcon(i.dlc),
      BADGES[s] ? el('span', { className: `badge ${BADGES[s][0]}`, textContent: BADGES[s][1] }) : null,
      el('span', { className: 'item-id', textContent: i.id, title: KINDS[i.kind].one })),
    el('div', { className: 'item-where', textContent: where(i) }),
    s === 'failed' && i.fail?.reason ? el('div', { className: 'item-note lost-note', textContent: i.fail.reason }) : null,
    i.realmNote && s !== 'failed' ? el('div', { className: 'item-note realm-note', textContent: i.realmNote }) : null,
    state.result.extra.get(i.id) ? el('div', { className: 'item-note', textContent: state.result.extra.get(i.id) }) : null,
    i.note ? el('div', { className: 'item-note', textContent: i.note }) : null,
    state.selected.has(i.id) ? localMap(i) : null);
  li.addEventListener('click', () => { select([i]); focusItem(i); });
  return li;
}

// ---------- map ----------

const map = $('map');
const stage = $('stage');
const pins = $('pins');
const img = $('map-img');
const tiles = $('tiles');
const tip = $('tip');
const world = () => state.data.worlds[state.world];
// The part of the square render that has map on it, as [u0, v0, u1, v1]; the panel shows only that.
const crop = () => world().crop ?? [0, 0, 1, 1];
// Width in screen pixels of the whole square render at the current zoom.
const fullSize = (width, s = state.view.s) => (width * s) / (crop()[2] - crop()[0]);

// Tabs for maps holding at least one collectible this save can have.
function worlds() {
  const used = new Set(state.result.items.map(i => i.map?.world));
  return Object.keys(state.data.worlds).filter(k => used.has(k));
}

function renderMapTabs() {
  $('map-tabs').replaceChildren(...worlds().map(k => {
    const b = el('button', { type: 'button', role: 'tab', textContent: state.data.worlds[k].name, dataset: { world: k } });
    b.addEventListener('click', () => { setWorld(k); render(); });
    return b;
  }));
}

function setWorld(k) {
  const changed = state.world !== k || !img.src;
  state.world = k;
  for (const b of $('map-tabs').children) b.setAttribute('aria-selected', b.dataset.world === k);
  if (!changed) return;
  const w = world();
  const c = crop();
  map.style.aspectRatio = `${(c[2] - c[0]) * w.width} / ${(c[3] - c[1]) * w.height}`;
  img.src = asset(w.image);
  for (const t of tileEls.values()) t.remove();
  tileEls.clear();
  resetView();
}

function renderPins(items) {
  pins.replaceChildren();
  const groups = new Map();
  const add = (key, entry) => { if (!groups.has(key)) groups.set(key, []); groups.get(key).push(entry); };
  for (const i of items) {
    if (!i.map || i.map.world !== state.world) continue;
    add(i.map.realm ? `realm|${i.map.realm}` : `${i.kind}|${i.map.u.toFixed(3)}|${i.map.v.toFixed(3)}`, i);
  }
  const frag = document.createDocumentFragment();
  for (const group of groups.values()) {
    const i = group[0];
    const allFound = group.every(g => st(g) === 'found');
    const allLost = group.every(g => st(g) === 'failed');
    const cls = allFound ? ' found' : allLost ? ' lost' : '';
    const realm = i.map.realm;
    const kindIcon = k => asset(`img/${k}.png`);
    const pin = realm
      ? el('div', { className: `pin realm${cls}`, dataset: { ids: group.map(g => g.id).join(' ') } },
        el('b', { className: 'ring' }),
        el('div', { className: 'realm-icons' }, ...[...new Set(group.map(g => g.kind))].map(k => el('img', { src: kindIcon(k), alt: '', draggable: false }))),
        el('em', { textContent: realm }),
        group.length > 1 ? el('span', { textContent: group.length }) : null)
      : el('div', { className: `pin ${i.kind}${cls}`, dataset: { ids: group.map(g => g.id).join(' ') } },
        el('img', { src: kindIcon(i.kind), alt: '', draggable: false }), group.length > 1 ? el('span', { textContent: group.length }) : null);
    pin._u = i.map.u;
    pin._v = i.map.v;
    pin._items = group;
    frag.append(pin);
  }
  pins.append(frag);
  layoutPins();
}


let laidOut = null;
function layoutPins() {
  const { width } = map.getBoundingClientRect();
  const s = state.view.s;
  const full = fullSize(width);
  for (const pin of pins.children) {
    pin.style.left = `${pin._u * full}px`;
    pin.style.top = `${pin._v * full}px`;
  }
  laidOut = `${width}|${s}`;
}

function tipLine(i) {
  const s = st(i);
  return el('div', {}, el('strong', { textContent: title(i) }), s === 'found' ? ' (collected)' : s === 'failed' ? ' (lost)' : '');
}

pins.addEventListener('pointerover', e => {
  const pin = e.target.closest('.pin');
  if (!pin) return;
  const realm = pin._items[0].map.realm;
  tip.replaceChildren(...(realm ? [el('div', { className: 'tip-head', textContent: `${realm} — separate realm` })] : []), ...pin._items.map(tipLine));
  tip.hidden = false;
  placeTip(pin);
});
pins.addEventListener('pointerout', e => { if (e.target.closest('.pin')) tip.hidden = true; });

function placeTip(pin) {
  const m = map.getBoundingClientRect();
  const p = (pin.querySelector('img') || pin).getBoundingClientRect();
  let x = p.right - m.left + 6, y = p.top - m.top;
  if (x + tip.offsetWidth > m.width) x = Math.max(4, p.left - m.left - 6 - tip.offsetWidth);
  if (y + tip.offsetHeight > m.height) y = p.bottom - m.top - tip.offsetHeight;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

pins.addEventListener('click', e => {
  const pin = e.target.closest('.pin');
  if (!pin || moved) return;
  select(pin._items, true);
});

function localMap(i) {
  const box = el('div', { className: 'item-map' });
  box.append(el('img', { src: asset(`img/local/${i.id}.webp`), alt: `Local map around ${title(i)}`, onerror: () => box.remove() }));
  return box;
}

function select(items, scroll = false) {
  state.selected = new Set(items.map(i => i.id));
  for (const n of $('list').querySelectorAll('.item.active')) n.classList.remove('active');
  for (const n of $('list').querySelectorAll('.item-map')) n.remove();
  const nodes = items.map(i => document.getElementById(`item-${i.id}`)).filter(Boolean);
  for (const i of items) document.getElementById(`item-${i.id}`)?.append(localMap(i));
  for (const n of nodes) {
    n.classList.add('active');
    n.classList.remove('flash');
    void n.offsetWidth;
    n.classList.add('flash');
  }
  if (scroll && nodes[0]) nodes[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function focusItem(i) {
  const m = i.map;
  if (!m) return;
  if (m.world !== state.world) { setWorld(m.world); render(); }
  const { width, height } = map.getBoundingClientRect();
  const s = Math.max(state.view.s, 3);
  const full = fullSize(width, s);
  animateView({ s, x: width / 2 - m.u * full, y: height / 2 - m.v * full });
  const pin = [...pins.querySelectorAll('.pin')].find(p => p._items.includes(i));
  if (pin) { pin.classList.remove('hot'); void pin.offsetWidth; pin.classList.add('hot'); }
  if (matchMedia('(max-width: 900px)').matches) map.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function resetView() {
  stopAnim();
  const full = fullSize(map.getBoundingClientRect().width, 1);
  state.view = { s: 1, x: -crop()[0] * full, y: -crop()[1] * full };
  applyView();
}

function applyView() {
  const { width, height } = map.getBoundingClientRect();
  const v = state.view;
  v.s = Math.min(16, Math.max(1, v.s));
  const c = crop(), full = fullSize(width);
  v.x = Math.min(-c[0] * full, Math.max(width - c[2] * full, v.x));
  v.y = Math.min(-c[1] * full, Math.max(height - c[3] * full, v.y));
  // Sized in real pixels and only translated: a scale() here would make the browser stretch one cached raster of the
  // whole map instead of drawing the tiles at their own resolution.
  lastWidth = width;
  stage.style.width = `${full}px`;
  stage.style.height = `${full}px`;
  stage.style.transform = `translate(${v.x}px, ${v.y}px)`;
  if (laidOut !== `${width}|${v.s}`) layoutPins();
  pins.style.transform = `translate(${v.x}px, ${v.y}px)`;
  renderTiles(width, height);
  tip.hidden = true;
}

// The flat image under .tiles is the whole map at zoom 3, so it stands in wherever sharper tiles are not loaded yet.
const tileEls = new Map();
function renderTiles(width, height) {
  const t = world().tiles;
  const v = state.view;
  const full = fullSize(width);
  const z = Math.max(t.min, Math.min(t.max, Math.ceil(Math.log2(full / t.size))));
  const n = 2 ** z;
  const side = full / n;
  const first = (off, box) => [Math.max(0, Math.floor(-off / side)), Math.min(n - 1, Math.floor((box - off) / side))];
  const [x0, x1] = first(v.x, width);
  const [y0, y1] = first(v.y, height);
  const keep = new Set();
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      const key = `${z}/${x}/${y}`;
      keep.add(key);
      let e = tileEls.get(key);
      if (!e) {
        e = el('img', { src: asset(`${t.path}/${key}.webp`), alt: '', draggable: false, decoding: 'async' });
        e.onerror = () => e.remove();
        tiles.append(e);
        tileEls.set(key, e);
      }
      e.style.cssText = `left:${x * side}px;top:${y * side}px;width:${side}px;height:${side}px`;
    }
  }
  for (const [key, e] of tileEls) {
    if (!keep.has(key)) {
      e.remove();
      tileEls.delete(key);
    }
  }
}

// Tweened in JS, not by a CSS transition: the pin layer has to track the map's scale frame by frame.
let anim = null;
const stopAnim = () => { if (anim) cancelAnimationFrame(anim); anim = null; };

function animateView(to, ms = 350) {
  stopAnim();
  const from = { ...state.view };
  const t0 = performance.now();
  const step = now => {
    const k = Math.min(1, (now - t0) / ms);
    const e = k < .5 ? 2 * k * k : 1 - (2 - 2 * k) ** 2 / 2;
    state.view = { s: from.s + (to.s - from.s) * e, x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e };
    applyView();
    anim = k < 1 ? requestAnimationFrame(step) : null;
  };
  anim = requestAnimationFrame(step);
}

function zoomAt(factor, cx, cy) {
  stopAnim();
  const v = state.view;
  const s = Math.min(16, Math.max(1, v.s * factor));
  v.x = cx - (cx - v.x) * (s / v.s);
  v.y = cy - (cy - v.y) * (s / v.s);
  v.s = s;
  applyView();
}

map.addEventListener('wheel', e => {
  e.preventDefault();
  const r = map.getBoundingClientRect();
  zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
}, { passive: false });

$('zoom-in').addEventListener('click', () => { const r = map.getBoundingClientRect(); zoomAt(1.6, r.width / 2, r.height / 2); });
$('zoom-out').addEventListener('click', () => { const r = map.getBoundingClientRect(); zoomAt(1 / 1.6, r.width / 2, r.height / 2); });
$('zoom-reset').addEventListener('click', resetView);
// Pan offsets are screen pixels of a map that scales with the panel, so a resize scales them too and keeps the view.
let lastWidth = 0;
window.addEventListener('resize', () => {
  if (!state.shown) return;
  const width = map.getBoundingClientRect().width;
  if (lastWidth && width) {
    state.view.x *= width / lastWidth;
    state.view.y *= width / lastWidth;
  }
  lastWidth = width;
  applyView();
});

const pointers = new Map();
let moved = false;
let start = null;
let pinch = null;
// Capture only once a drag starts: capturing on pointerdown retargets the click away from the pin.
map.addEventListener('pointerdown', e => {
  if (e.target.closest('.map-ctrl')) return;
  stopAnim();
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  start = { x: e.clientX, y: e.clientY };
  moved = false;
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    pinch = Math.hypot(a.x - b.x, a.y - b.y);
  }
  map.classList.add('dragging');
});
map.addEventListener('pointermove', e => {
  const prev = pointers.get(e.pointerId);
  if (!prev) return;
  const cur = { x: e.clientX, y: e.clientY };
  pointers.set(e.pointerId, cur);
  if (pointers.size === 2 && pinch) {
    const [a, b] = [...pointers.values()];
    const d = Math.hypot(a.x - b.x, a.y - b.y);
    const r = map.getBoundingClientRect();
    zoomAt(d / pinch, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
    pinch = d;
    moved = true;
    return;
  }
  if (!moved && Math.hypot(cur.x - start.x, cur.y - start.y) > 4) {
    moved = true;
    map.setPointerCapture(e.pointerId);
  }
  if (moved) {
    state.view.x += cur.x - prev.x;
    state.view.y += cur.y - prev.y;
    applyView();
  }
});
const endPointer = e => {
  pointers.delete(e.pointerId);
  if (pointers.size < 2) pinch = null;
  if (!pointers.size) map.classList.remove('dragging');
};
map.addEventListener('pointerup', endPointer);
map.addEventListener('pointercancel', endPointer);
