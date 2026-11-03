// Decides each collectible's state in a parsed save; shared by the page and tools/check-saves.js.
import { SaveError } from './ess.js';

// Plugin keys build_data.py writes into collectibles.json, in tools/tes5.py ORDER.
const PLUGINS = { skyrim: 'skyrim.esm', update: 'update.esm', dawnguard: 'dawnguard.esm', hearthfires: 'hearthfires.esm', dragonborn: 'dragonborn.esm', saints: 'ccbgssse025-advdsgs.esm' };
// The Creation Club plugins every Special Edition install has had since 1.6; any other one means the Anniversary Edition.
const FREE_CC = new Set(['ccbgssse001-fish.esm', 'ccbgssse025-advdsgs.esm', 'ccbgssse037-curios.esl', 'ccqdrsse001-survivalmode.esl']);
const DISABLED = 0x800, DELETED = 0x20;
const PICKED_UP = 0x400;
const PLAYER = 0x14;

export const EDITION_NAMES = { le: 'Skyrim', se: 'Skyrim Special Edition', vr: 'Skyrim VR' };
export const DLC_NAMES = { dawnguard: 'Dawnguard', dragonborn: 'Dragonborn', saints: 'Saints & Seducers' };

export function context(save) {
  const plugins = save.plugins.map(p => p.toLowerCase());
  if (plugins.some(p => p.startsWith('enderal'))) {
    throw new SaveError('This is an Enderal save. Try the Enderal Collectibles Tracker instead.');
  }
  const index = Object.fromEntries(Object.entries(PLUGINS).map(([k, name]) => [k, plugins.indexOf(name)]));
  if (index.skyrim < 0) throw new SaveError("This save doesn't load Skyrim.esm, so it doesn't look like a Skyrim save.");
  const fid = ([plugin, local]) => (index[plugin] < 0 ? null : ((index[plugin] << 24) | local) >>> 0);
  const dlc = { base: true, dawnguard: index.dawnguard >= 0, dragonborn: index.dragonborn >= 0, saints: index.saints >= 0 };
  const anniversary = [...plugins, ...(save.lightPlugins ?? []).map(p => p.toLowerCase())].some(p => p.startsWith('cc') && !FREE_CC.has(p));
  return { save, fid, dlc, anniversary };
}

// Every item base form some rule asks about, so one pass over the inventories answers them all.
function wantedItems(ctx, items) {
  const out = new Set();
  for (const it of items) {
    const walk = evs => evs.forEach(e => { e.held?.forEach(i => out.add(ctx.fid(i))); e.item?.forEach(i => out.add(ctx.fid(i))); if (e.all) walk(e.all); });
    walk(it.rule);
    if (it.pickup) walk(it.pickup);
    if (it.pool) out.add(ctx.fid(it.pool));
    it.halves?.forEach(h => out.add(ctx.fid(h)));
  }
  out.delete(null);
  return out;
}

async function evidence(e, ctx) {
  const { save, fid, inv } = ctx;
  if (e.all) {
    for (const x of e.all) if (!(await evidence(x, ctx))) return false;
    return true;
  }
  if (e.ref) {
    const f = await save.refFlags(fid(e.ref));
    if (!f) return false;
    const flags = f.formFlags;
    if (e.how === 'disabled') return flags !== null && (flags & DISABLED) !== 0;
    if (e.how === 'shown') return flags !== null && (flags & DISABLED) === 0;
    return (f.changeFlags & PICKED_UP) !== 0 || (flags !== null && (flags & DELETED) !== 0);
  }
  if (e.held) {
    const skip = new Set((e.exclude ?? []).map(fid));
    return e.held.some(i => (inv.get(fid(i)) ?? []).some(h => h.count > 0 && !skip.has(h.holder)));
  }
  if (e.lost) {
    const holder = fid(e.lost);
    return e.item.some(i => (inv.get(fid(i)) ?? []).some(h => h.holder === holder && h.count < 0));
  }
  if (e.stage) {
    const q = await save.quest(fid(e.stage));
    return !!q && e.stages.some(s => q.done.has(s));
  }
  if (e.word) return save.changeForms.has(fid(e.word));
  if (e.wall) return !!ctx.vm?.get(fid(e.wall), e.script)?.['::wordLearned_var'];
  return false;
}

async function failed(it, ctx) {
  const f = it.fail;
  const q = await ctx.save.quest(ctx.fid(f.quest));
  if (!q) return false;
  return f.stages ? f.stages.some(s => q.done.has(s)) : q.completed;
}

// { state: Map(id -> 'found' | 'failed' | 'missing'), extra: per-item details, wordsKnown: words of power learned }.
export async function evaluate(save, data) {
  const ctx = context(save);
  const items = data.items.filter(i => ctx.dlc[i.dlc]);
  ctx.inv = await save.holdings(wantedItems(ctx, items));
  ctx.vm = save.papyrus();
  const state = new Map(), extra = new Map();
  for (const it of items) {
    let s = 'missing';
    for (const e of it.rule) if (await evidence(e, ctx)) { s = 'found'; break; }
    if (s === 'missing' && it.fail && (await failed(it, ctx))) s = 'failed';
    state.set(it.id, s);
    if (it.halves) {
      const have = it.halves.filter(h => (ctx.inv.get(ctx.fid(h)) ?? []).some(x => x.count > 0)).length;
      if (s !== 'found' && have) extra.set(it.id, `${have} of 2 halves found`);
    }
    if (s === 'missing' && it.pickup) {
      for (const e of it.pickup) if (await evidence(e, ctx)) { extra.set(it.id, 'Picked up. Sell it to Delvin in the Ragged Flagon to put it on the shelf.'); break; }
    }
  }
  pool(ctx, items, data, state);
  walls(ctx, items, data, state, extra);

  const wordsKnown = data.shouts.filter(s => ctx.dlc[s.dlc]).flatMap(s => s.words).filter(w => save.changeForms.has(ctx.fid(w))).length;
  return { ctx, items, state, extra, wordsKnown };
}

// The save does not always hold a wall's script state, so walls without it are judged from the shout's words known
// minus the words its quests gave.
function walls(ctx, items, data, state, extra) {
  for (const s of data.shouts.filter(x => ctx.dlc[x.dlc])) {
    const group = items.filter(i => i.shout === s.id);
    const ws = group.filter(i => i.source === 'wall');
    if (!ws.length) continue;
    const known = s.words.filter(w => ctx.save.changeForms.has(ctx.fid(w))).length;
    const taught = group.filter(i => i.source === 'quest' && state.get(i.id) === 'found').length;
    const used = Math.min(ws.length, Math.max(0, known - taught));
    const open = ws.filter(i => state.get(i.id) !== 'found');
    const unknown = used - (ws.length - open.length);
    if (unknown <= 0) continue;
    if (unknown >= open.length) {
      for (const i of open) { state.set(i.id, 'found'); extra.set(i.id, "Your save shows you have learned every word this shout's walls teach."); }
      continue;
    }
    for (const i of open) extra.set(i.id, `You have learned ${unknown} more ${unknown === 1 ? 'word' : 'words'} of this shout from walls, but your save does not record which walls.`);
  }
}

// Pool items share one base form, so the count obtained is spread over the entries without direct evidence.
function pool(ctx, items, data, state) {
  const groups = new Map();
  for (const it of items.filter(i => i.pool)) {
    const k = it.pool.join(':');
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(it);
  }
  for (const group of groups.values()) {
    const base = ctx.fid(group[0].pool);
    const held = (ctx.inv.get(base) ?? []).filter(h => h.holder === PLAYER && h.count > 0).reduce((n, h) => n + h.count, 0);
    const placed = Math.round(ctx.save.globals.get(ctx.fid(data.counters.kagrumez)) ?? 0);
    let left = held + placed - group.filter(i => state.get(i.id) === 'found').length;
    for (const it of group) if (left > 0 && state.get(it.id) !== 'found') { state.set(it.id, 'found'); left--; }
  }
}

// The game's own running totals, where it keeps one.
export function counters(save, data) {
  const ctx = context(save);
  const out = {};
  const stones = save.globals.get(ctx.fid(data.counters.stone));
  if (stones != null) out.stone = Math.round(stones);
  out.wordsLearned = save.stats.get('Words Of Power Learned');
  const ach = save.papyrus()?.get(ctx.fid(data.achievements), 'AchievementsScript');
  if (ach) out.artifacts = { count: ach.DaedricArtifactCount, max: ach.MaxDaedricArtifacts };
  return out;
}
