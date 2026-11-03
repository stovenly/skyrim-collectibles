// Skyrim .ess reader for Skyrim (LE), Skyrim Special Edition and Skyrim VR saves.

const VERSIONS = { 9: 'le', 12: 'se' };
const CHANGE_FORM_FLAGS = 0x1;
const MOVED = 0x2 | 0x4;
const PROMOTED_OR_CELL_CHANGED = 0x02000000 | 0x8;
const CHANGE_REFR_INVENTORY = 0x20;
const ACHR = 1;
const CHANGE_QUEST_FLAGS = 0x2, CHANGE_QUEST_SCRIPT_DELAY = 0x4, CHANGE_QUEST_STAGES = 0x80000000;
const QUEST_COMPLETED = 0x2;
const MISC_STATS = 0, GLOBAL_VARIABLES = 3, PAPYRUS = 1001;
const LZ4 = 2, ZLIB = 1;

export class SaveError extends Error {}

class Reader {
  constructor(bytes, o = 0) {
    this.b = bytes;
    this.v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    this.o = o;
  }
  u8() { return this.b[this.o++]; }
  u16() { const x = this.v.getUint16(this.o, true); this.o += 2; return x; }
  u32() { const x = this.v.getUint32(this.o, true); this.o += 4; return x; }
  f32() { const x = this.v.getFloat32(this.o, true); this.o += 4; return x; }
  u64() { const x = this.v.getBigUint64(this.o, true); this.o += 8; return x; }
  skip(n) { this.o += n; }
  wstring() {
    const n = this.u16();
    const s = new TextDecoder('windows-1252').decode(this.b.subarray(this.o, this.o + n));
    this.o += n;
    return s;
  }
  refId() { const r = (this.b[this.o] << 16) | (this.b[this.o + 1] << 8) | this.b[this.o + 2]; this.o += 3; return r; }
  vsval() {
    const size = [1, 2, 4][this.b[this.o] & 3];
    let x = 0;
    for (let i = size - 1; i >= 0; i--) x = x * 256 + this.b[this.o + i];
    this.o += size;
    return Math.floor(x / 4);
  }
}

function lz4Block(src, outLen) {
  const out = new Uint8Array(outLen);
  let i = 0, o = 0;
  while (i < src.length) {
    const token = src[i++];
    let lit = token >> 4;
    if (lit === 15) { let b; do { b = src[i++]; lit += b; } while (b === 255); }
    out.set(src.subarray(i, i + lit), o);
    i += lit;
    o += lit;
    if (i >= src.length) break;
    const off = src[i] | (src[i + 1] << 8);
    i += 2;
    let len = token & 15;
    if (len === 15) { let b; do { b = src[i++]; len += b; } while (b === 255); }
    len += 4;
    for (let k = 0; k < len; k++, o++) out[o] = out[o - off];
  }
  if (o !== outLen) throw new SaveError('Save file is truncated or corrupt.');
  return out;
}

async function inflate(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export function parseSave(bytes) {
  if (bytes.byteLength < 64) throw new SaveError('File is too small to be a save.');
  if (new TextDecoder().decode(bytes.subarray(0, 13)) !== 'TESV_SAVEGAME') {
    throw new SaveError('Not a Skyrim save (.ess) file.');
  }
  let r = new Reader(bytes, 13);
  const headerSize = r.u32();
  const headerEnd = r.o + headerSize;
  const version = r.u32();
  let edition = VERSIONS[version];
  if (!edition) throw new SaveError(`Unsupported save version ${version}.`);
  const header = { version };
  header.saveNum = r.u32();
  header.name = r.wstring();
  header.level = r.u32();
  header.location = r.wstring();
  header.gameDate = r.wstring();
  header.race = r.wstring();
  header.sex = r.u16();
  r.skip(8);
  header.savedAt = new Date(Number(r.u64() / 10000n) - 11644473600000);
  const width = r.u32(), height = r.u32();
  const compression = version >= 12 ? r.u16() : 0;
  r.o = headerEnd;
  const bpp = version >= 12 ? 4 : 3;
  if (width && height) header.screenshot = { width, height, offset: r.o, bpp };
  r.skip(width * height * bpp);

  if (compression) {
    const uncompressed = r.u32(), compressed = r.u32();
    const src = bytes.subarray(r.o, r.o + compressed);
    if (compression !== LZ4) throw new SaveError(compression === ZLIB ? 'zlib-compressed saves are not supported yet.' : 'Unknown save compression.');
    r = new Reader(lz4Block(src, uncompressed));
  }

  const formVersion = r.u8();
  const pluginInfoSize = r.u32();
  const pluginsEnd = r.o + pluginInfoSize;
  const plugins = [];
  for (let n = r.u8(), i = 0; i < n; i++) plugins.push(r.wstring());
  const lightPlugins = [];
  if (formVersion >= 78) for (let n = r.u16(), i = 0; i < n; i++) lightPlugins.push(r.wstring());
  r.o = pluginsEnd;
  // VR writes SE's save format; its own master is the only tell.
  if (edition === 'se' && plugins.some(p => p.toLowerCase() === 'skyrimvr.esm')) edition = 'vr';
  header.edition = edition;

  const [formIdArrayOffset, , globals1Offset, , changeFormsOffset, globals3Offset, globals1Count, , globals3Count, changeFormCount] =
    Array.from({ length: 10 }, () => r.u32());
  r.skip(15 * 4);
  // Offsets count from the start of the file as if an SE body were stored inline; table 1 always starts here.
  const delta = r.o - globals1Offset;

  r.o = formIdArrayOffset + delta;
  const formIds = new Uint32Array(r.u32());
  for (let i = 0; i < formIds.length; i++) formIds[i] = r.u32();
  const resolve = ref => {
    const type = ref >>> 22, value = ref & 0x3FFFFF;
    if (type === 0) return value > 0 && value <= formIds.length ? formIds[value - 1] : null;
    if (type === 1) return value;
    if (type === 2) return (0xFF000000 | value) >>> 0;
    return null;
  };

  r.o = globals1Offset + delta;
  const globals = new Map();
  const stats = new Map();
  for (let i = 0; i < globals1Count; i++) {
    const type = r.u32(), length = r.u32(), end = r.o + length;
    if (type === MISC_STATS) {
      for (let n = r.u32(), k = 0; k < n; k++) {
        const name = r.wstring();
        r.skip(1);
        stats.set(name, r.v.getInt32(r.o, true));
        r.skip(4);
      }
    } else if (type === GLOBAL_VARIABLES) {
      for (let n = r.vsval(), k = 0; k < n; k++) {
        const id = resolve(r.refId());
        globals.set(id, r.f32());
      }
    }
    r.o = end;
  }

  r.o = changeFormsOffset + delta;
  const changeForms = new Map();
  for (let i = 0; i < changeFormCount; i++) {
    const id = resolve(r.refId());
    const flags = r.u32();
    const type = r.u8();
    r.skip(1);
    const width = type >> 6;
    const len = () => (width === 0 ? r.u8() : width === 1 ? r.u16() : r.u32());
    const length = len(), uncompressed = len();
    if (r.o + length > r.b.byteLength) throw new SaveError('Save file is truncated or corrupt.');
    changeForms.set(id, { flags, type: type & 0x3F, offset: r.o, length, uncompressed });
    r.o += length;
  }
  const body = r.b;

  // The file location table undercounts global data table 3 by one.
  let papyrusAt = null;
  r.o = globals3Offset + delta;
  for (let i = 0; i <= globals3Count && r.o + 8 <= body.byteLength; i++) {
    const type = r.u32(), length = r.u32();
    if (type === PAPYRUS) { papyrusAt = r.o; break; }
    r.o += length;
  }
  let vm;
  const papyrus = () => (vm ??= papyrusAt == null ? null : readPapyrus(new Reader(body, papyrusAt), edition !== 'le', resolve));

  async function data(form) {
    const raw = body.subarray(form.offset, form.offset + form.length);
    return form.uncompressed ? inflate(raw) : raw;
  }

  // Change flags and, when the save records them, the reference's form flags (0x800 disabled, 0x20 deleted).
  async function refFlags(id) {
    const form = changeForms.get(id);
    if (!form) return null;
    if (!(form.flags & CHANGE_FORM_FLAGS)) return { changeFlags: form.flags, formFlags: null };
    const d = await data(form);
    const skip = form.flags & PROMOTED_OR_CELL_CHANGED ? 34 : form.flags & MOVED ? 27 : 0;
    return { changeFlags: form.flags, formFlags: new DataView(d.buffer, d.byteOffset).getUint32(skip, true) };
  }

  // Change in `item` count held by the placed actor `holder`, relative to the game data; -1 means one was taken.
  async function inventoryChange(holder, item) {
    const form = changeForms.get(holder);
    if (!form || !(form.flags & CHANGE_REFR_INVENTORY)) return 0;
    const d = await data(form);
    const v = new DataView(d.buffer, d.byteOffset, d.byteLength);
    const refs = [];
    if (item >>> 24 === 0 && item < 0x400000) refs.push(0x400000 | item);
    const idx = formIds.indexOf(item);
    if (idx >= 0) refs.push(idx + 1);
    for (let o = 0; o + 7 <= d.length; o++) {
      const ref = (d[o] << 16) | (d[o + 1] << 8) | d[o + 2];
      if (refs.includes(ref)) {
        const count = v.getInt32(o + 3, true);
        if (count < 0) return count;
      }
    }
    return 0;
  }

  // For each wanted base form, the inventories whose count of it differs from the game data: [{ holder, count }].
  async function holdings(wanted) {
    const keys = new Map();
    for (const item of wanted) {
      if (item >>> 24 === 0 && item < 0x400000) keys.set(0x400000 | item, item);
      const idx = formIds.indexOf(item);
      if (idx >= 0) keys.set(idx + 1, item);
    }
    const out = new Map([...wanted].map(w => [w, []]));
    for (const [holder, form] of changeForms) {
      if (form.type > ACHR || !(form.flags & CHANGE_REFR_INVENTORY)) continue;
      const d = await data(form);
      const v = new DataView(d.buffer, d.byteOffset, d.byteLength);
      for (let o = 0; o + 7 <= d.length; o++) {
        const item = keys.get((d[o] << 16) | (d[o + 1] << 8) | d[o + 2]);
        if (item === undefined) continue;
        const count = v.getInt32(o + 3, true);
        if (count !== 0 && Math.abs(count) < 10000) out.get(item).push({ holder, count });
      }
    }
    return out;
  }

  // Runtime flags (0x2 completed) and the set of stages done, or null when the quest never changed.
  async function quest(id) {
    const form = changeForms.get(id);
    if (!form || !(form.flags & (CHANGE_QUEST_FLAGS | CHANGE_QUEST_STAGES))) return null;
    const q = new Reader(await data(form));
    const flags = form.flags & CHANGE_QUEST_FLAGS ? q.u16() : 0;
    if (form.flags & CHANGE_QUEST_SCRIPT_DELAY) q.skip(4);
    const done = new Set();
    if (form.flags & CHANGE_QUEST_STAGES) {
      for (let n = q.vsval(), i = 0; i < n; i++) {
        const stage = q.u16();
        if (q.u8() & 1) done.add(stage);
      }
    }
    return { flags, completed: (flags & QUEST_COMPLETED) !== 0, done };
  }

  return { header, plugins, lightPlugins, globals, stats, formIds, changeForms, data, refFlags, inventoryChange, holdings, quest, papyrus };
}

// Script instances and their variables from the Papyrus VM state. SE and VR count and index the string table in 32 bits.
function readPapyrus(r, wideStrings, resolve) {
  const eid = () => (wideStrings ? r.u32() + r.u32() * 2 ** 32 : r.u32());
  r.u16();
  let count = wideStrings ? r.u32() : r.u16();
  const big = wideStrings || count === 0xFFFF;
  if (count === 0xFFFF && !wideStrings) count = r.u32();
  const strings = Array.from({ length: count }, () => r.wstring());
  const str = () => strings[big ? r.u32() : r.u16()];

  const scripts = new Map();
  for (let n = r.u32(), i = 0; i < n; i++) {
    const name = str(), parent = str();
    const members = Array.from({ length: r.u32() }, () => { const m = str(); str(); return m; });
    scripts.set(name.toLowerCase(), { parent: parent.toLowerCase(), members });
  }
  const instances = new Map();
  for (let n = r.u32(), i = 0; i < n; i++) {
    const id = eid(), script = str();
    r.skip(4);
    const form = resolve(r.refId());
    r.skip(1);
    instances.set(id, { script, form });
  }
  for (let n = r.u32(), i = 0; i < n; i++) { eid(); str(); }
  for (let n = r.u32(), i = 0; i < n; i++) { eid(); if (r.u8() === 1) str(); r.skip(4); }
  r.skip(4);
  for (let n = r.u32(), i = 0; i < n; i++) r.skip(4 + 1);

  // Members of a derived script follow those of its parents, which is how the save orders the values.
  const memberNames = name => {
    const s = scripts.get(name.toLowerCase());
    return s ? [...(s.parent ? memberNames(s.parent) : []), ...s.members] : [];
  };
  const byForm = new Map();
  for (let i = 0; i < instances.size; i++) {
    const at = r.o, id = eid(), inst = instances.get(id);
    if (!inst) throw new SaveError(`papyrus data ${i} of ${instances.size} at ${at}: id ${id}`);
    const flag = r.u8();
    str();
    r.skip(flag & 4 ? 8 : 4);
    const names = memberNames(inst.script);
    const values = {};
    for (let n = r.u32(), k = 0; k < n; k++) values[names[k] ?? k] = variable();
    inst.values = values;
    if (!byForm.has(inst.form)) byForm.set(inst.form, []);
    byForm.get(inst.form).push(inst);
  }
  function variable() {
    const t = r.u8();
    if (t === 0) return (r.skip(4), null);
    if (t === 1 || t === 11) { str(); return eid(); }
    if (t === 2) return str();
    if (t === 3) return r.v.getInt32((r.o += 4) - 4, true);
    if (t === 4) return r.f32();
    if (t === 5) return r.u32() !== 0;
    if (t >= 12 && t <= 15) return eid();
    throw new SaveError(`Unknown Papyrus variable type ${t}.`);
  }
  // Values of `script` attached to `form`, by member name; null when the save holds no such instance.
  return {
    instances,
    get(form, script) {
      return byForm.get(form)?.find(i => i.script.toLowerCase() === script.toLowerCase())?.values ?? null;
    },
  };
}

export function screenshotImageData(bytes, shot) {
  const { width, height, offset, bpp } = shot;
  const out = new Uint8ClampedArray(width * height * 4);
  for (let i = 0, j = offset; i < width * height; i++, j += bpp) {
    out[i * 4] = bytes[j];
    out[i * 4 + 1] = bytes[j + 1];
    out[i * 4 + 2] = bytes[j + 2];
    out[i * 4 + 3] = 255;
  }
  return new ImageData(out, width, height);
}
