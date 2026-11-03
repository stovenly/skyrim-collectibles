"""Skyrim plugin reader for LE, SE and VR: merged records, localized strings, VMAD script names."""
import os, struct, zlib

STEAM = r'C:\Program Files (x86)\Steam\steamapps\common'
DATA = {
    'le': os.path.join(STEAM, 'Skyrim', 'Data'),
    'se': os.path.join(STEAM, 'Skyrim Special Edition', 'Data'),
    'vr': os.path.join(STEAM, 'SkyrimVR', 'Data'),
}
# Normalised form IDs carry the index into this list, so every edition agrees whatever its load order.
# Saints & Seducers is free Creation Club content that only Special Edition installs carry; plugins() skips it elsewhere.
ORDER = ['Skyrim.esm', 'Update.esm', 'Dawnguard.esm', 'HearthFires.esm', 'Dragonborn.esm', 'ccBGSSSE025-AdvDSGS.esm']
SKYRIM, UPDATE, DAWNGUARD, HEARTHFIRES, DRAGONBORN, SAINTS = range(6)
KEYS = ['skyrim', 'update', 'dawnguard', 'hearthfires', 'dragonborn', 'saints']
OPTIONAL = {'ccBGSSSE025-AdvDSGS.esm'}
LOCALIZED = 0x80
COMPRESSED = 0x40000
FID_GROUPS = {1, 6, 8, 9, 10}


def u32(b):
    return struct.unpack_from('<I', b)[0]


def subrecords(buf):
    i, big = 0, None
    while i + 6 <= len(buf):
        t = buf[i:i + 4].decode('latin1')
        sz = struct.unpack_from('<H', buf, i + 4)[0]
        i += 6
        if t == 'XXXX':
            big = struct.unpack_from('<I', buf, i)[0]
            i += sz
            continue
        if big is not None:
            sz, big = big, None
        yield t, buf[i:i + sz]
        i += sz


class Plugin:
    def __init__(self, edition, name):
        self.name = name
        with open(os.path.join(DATA[edition], name), 'rb') as f:
            self.buf = f.read()
        hsize = struct.unpack_from('<I', self.buf, 4)[0]
        self.flags = struct.unpack_from('<I', self.buf, 8)[0]
        masters = [v.split(b'\0')[0].decode('latin1') for k, v in subrecords(self.buf[24:24 + hsize]) if k == 'MAST']
        index = {n.lower(): i for i, n in enumerate(ORDER)}
        self.remap = {i: index.get(m.lower(), 0xFF) for i, m in enumerate(masters)}
        self.remap[len(masters)] = index.get(name.lower(), 0xFE)
        self.strings = load_strings(edition, name) if self.flags & LOCALIZED else {}

    def norm(self, fid):
        return (self.remap.get(fid >> 24, 0xFF) << 24) | (fid & 0xFFFFFF)

    def text(self, b):
        if not b:
            return ''
        if self.flags & LOCALIZED and len(b) == 4:
            return self.strings.get(u32(b), '')
        return b.split(b'\0')[0].decode('cp1252', errors='replace')


class Rec:
    __slots__ = ('type', 'flags', 'fid', 'raw', 'path', 'plugin', '_d')

    @property
    def data(self):
        if self._d is None:
            self._d = zlib.decompress(self.raw[4:]) if self.flags & COMPRESSED else self.raw
        return self._d

    def subs(self):
        return list(subrecords(self.data))

    def sub(self, t):
        for k, v in subrecords(self.data):
            if k == t:
                return v

    def all(self, t):
        return [v for k, v in subrecords(self.data) if k == t]

    def ref(self, t, offset=0):
        v = self.sub(t)
        return self.plugin.norm(u32(v[offset:])) if v and len(v) >= offset + 4 else None

    @property
    def edid(self):
        v = self.sub('EDID')
        return v.split(b'\0')[0].decode('cp1252') if v else ''

    @property
    def full(self):
        return self.plugin.text(self.sub('FULL'))

    def cell_world(self):
        cell = wrld = None
        for gtype, label in self.path:
            if gtype == 1:
                wrld = label
            elif gtype in (6, 8, 9, 10):
                cell = label
        return cell, wrld


def walk(p, start, end, path=()):
    buf, i = p.buf, start
    while i < end:
        if buf[i:i + 4] == b'GRUP':
            gsz, label, gtype = struct.unpack_from('<I4si', buf, i + 4)
            lab = p.norm(u32(label)) if gtype in FID_GROUPS else label
            yield from walk(p, i + 24, i + gsz, path + ((gtype, lab),))
            i += gsz
        else:
            dsz, flags, fid = struct.unpack_from('<III', buf, i + 4)
            r = Rec()
            r.type, r.flags, r.fid = buf[i:i + 4].decode('latin1'), flags, p.norm(fid)
            r.raw, r.path, r.plugin, r._d = buf[i + 24:i + 24 + dsz], path, p, None
            yield r
            i += 24 + dsz


def plugins(edition, names=ORDER):
    for name in names:
        if name in OPTIONAL and not os.path.exists(os.path.join(DATA[edition], name)):
            continue
        p = Plugin(edition, name)
        yield p, walk(p, 24 + struct.unpack_from('<I', p.buf, 4)[0], len(p.buf))


def load(edition, names=ORDER):
    """Every record of the masters, later plugins overriding earlier ones by form ID."""
    recs = {}
    for _, it in plugins(edition, names):
        for r in it:
            recs[r.fid] = r
    return recs


def parse_strings(b, sized):
    n = struct.unpack_from('<I', b)[0]
    dbase = 8 + n * 8
    out = {}
    for k in range(n):
        sid, off = struct.unpack_from('<II', b, 8 + k * 8)
        o = dbase + off
        s = b[o + 4:o + 4 + u32(b[o:])] if sized else b[o:b.index(b'\0', o)]
        out[sid] = s.split(b'\0')[0].decode('cp1252', errors='replace')
    return out


def load_strings(edition, plugin):
    """Loose Strings/ files if present (VR), otherwise the copies packed in the BSAs (LE, SE)."""
    import bsa
    base = os.path.splitext(plugin)[0].lower() + '_english.'
    out = {}
    for ext in ('strings', 'dlstrings', 'ilstrings'):
        path = os.path.join(DATA[edition], 'Strings', base + ext)
        b = open(path, 'rb').read() if os.path.exists(path) else bsa.extract(edition, f'strings\\{base}{ext}')
        if b:
            out.update(parse_strings(b, ext != 'strings'))
    return out


def vmad_scripts(v):
    """Script names attached by a VMAD subrecord; properties are skipped."""
    return [name for name, _ in vmad(v)]


def quest_fragments(v):
    """{fragment function name: (stage, log entry index)} from a QUST record's VMAD."""
    if not v:
        return {}
    o = _vmad_scripts(v, [])
    o += 1
    n = struct.unpack_from('<H', v, o)[0]
    o += 2
    o += 2 + struct.unpack_from('<H', v, o)[0]
    out = {}
    for _ in range(n):
        stage, _, log, _ = struct.unpack_from('<HhiB', v, o)
        o += 9
        o += 2 + struct.unpack_from('<H', v, o)[0]
        ln = struct.unpack_from('<H', v, o)[0]
        out[v[o + 2:o + 2 + ln].decode('latin1')] = (stage, log)
        o += 2 + ln
    return out


def info_fragment_script(v):
    """Script name holding an INFO record's dialogue fragments, if any."""
    if not v:
        return None
    o = _vmad_scripts(v, [])
    o += 2
    return v[o + 2:o + 2 + struct.unpack_from('<H', v, o)[0]].decode('latin1')


def vmad(v):
    """(script name, {property name: value}) pairs of a VMAD subrecord; object properties give the form ID."""
    if not v:
        return []
    out = []
    _vmad_scripts(v, out)
    return out


def _vmad_scripts(v, out):
    ver, objfmt, n = struct.unpack_from('<hhH', v)
    o = 6
    for _ in range(n):
        ln = struct.unpack_from('<H', v, o)[0]
        name = v[o + 2:o + 2 + ln].decode('latin1')
        o += 2 + ln + (1 if ver >= 4 else 0)
        count = struct.unpack_from('<H', v, o)[0]
        o += 2
        props = {}
        for _ in range(count):
            pl = struct.unpack_from('<H', v, o)[0]
            pname = v[o + 2:o + 2 + pl].decode('latin1')
            o += 2 + pl
            t = v[o]
            o += 2 if ver >= 4 else 1
            props[pname], o = _property(v, o, t, objfmt)
        out.append((name, props))
    return o


def _property(v, o, t, objfmt):
    if t == 1:
        fid = struct.unpack_from('<I', v, o + (4 if objfmt == 2 else 0))[0]
        return fid, o + 8
    if t == 2:
        n = struct.unpack_from('<H', v, o)[0]
        return v[o + 2:o + 2 + n].decode('latin1'), o + 2 + n
    if t == 3:
        return struct.unpack_from('<i', v, o)[0], o + 4
    if t == 4:
        return struct.unpack_from('<f', v, o)[0], o + 4
    if t == 5:
        return bool(v[o]), o + 1
    if 11 <= t <= 15:
        n = struct.unpack_from('<I', v, o)[0]
        o += 4
        vals = []
        for _ in range(n):
            x, o = _property(v, o, t - 10, objfmt)
            vals.append(x)
        return vals, o
    raise ValueError(f'VMAD property type {t}')
