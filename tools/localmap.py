"""Renders local maps from Skyrim-engine data files, without the game, using the engine's camera and ISLocalMap shader."""
import hashlib, io, json, pickle, struct, sys, time, zlib
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import tes5

ROOT = Path(__file__).parent.parent
CACHE = ROOT / 'research' / 'localmap_cache'
OUT = ROOT / 'docs' / 'img' / 'local'

CELL = 4096.0
NEAR = 100.0
CAMERA_LIFT = 40000.0  # fMapLocalHeight
RT_SCALE = 1  # displayed pixels per target pixel
UNITS_PER_PX = 16.5  # of the target, measured from an in-game screenshot
MAX_ZOOM = 8
FRAME_MARGIN = 1.15
OUTPUT_SIZE = (512, 512)
BACKDROP = np.array([0.075, 0.09, 0.09])  # the menu behind the map, sampled from a screenshot's lake
MIN_SHAPE_RADIUS = 50.0  # render mode 0x12 skips shapes whose stored model bound is smaller
LAND_REPEATS = 24  # per cell: vertex UV steps fLandTextureTilingMult / 4 across 16 quads in each of 2 quadrants
LAND_OUTPUT_MULT = 1 / 1.2  # FogColor.w in the lit land shader, a static in the exe
MAP_HOUR = 12.0  # the game lights land with its current time and weather; the tool fixes noon
SUN_EXTREME_X, SUN_Y, SUN_Z = 400.0, 25.0, 100.0  # fSunXExtreme, fSunYExtreme, -fSunZExtreme
DAY = 1  # time-of-day index in NAM0, DALC and IMSP: sunrise, day, sunset, night
SUNLIGHT_COLOUR = 4  # index in NAM0
USE_PARENT_CLIMATE = 16  # WRLD PNAM
NO_WEATHER_SUN, NO_WEATHER_AMBIENT = np.array([0.95, 0.85, 0.85]), np.array([0.35, 0.35, 0.43])  # the sky's defaults with no weather
MAP_TAB_WORLDS = {'skyrim': 0x3C, 'vale': 0x02000BB5, 'soulcairn': 0x02001408, 'solstheim': 0x04000800}  # item map.world
MODEL_TYPES = {'STAT', 'MSTT', 'TREE', 'FLOR', 'FURN', 'ACTI', 'DOOR', 'CONT', 'LIGH', 'MISC', 'WEAP', 'ARMO', 'BOOK',
               'ALCH', 'APPA', 'INGR', 'KEYM', 'SLGM', 'AMMO', 'SCRL', 'TACT'}
HIDDEN_FROM_MAP = 0x200  # same bit on the base form and the reference
IS_MARKER = 0x800000
DISABLED, DELETED = 0x800, 0x20
USE_PARENT_LAND, USE_PARENT_WATER = 1, 8
SLSF1_SKINNED, SLSF1_REFRACTION, SLSF1_HIDE_SECRET = 1 << 1, 1 << 15, 1 << 20
SLSF2_DOUBLE_SIDED, SLSF2_HIDE_ON_LOCAL_MAP = 1 << 4, 1 << 18


# ---------- archives ----------

def bsa_entries(path):
    with open(path, 'rb') as f:
        _, ver, _, aflags, nfold, _, _, fnl_files, _ = struct.unpack('<4s8I', f.read(36))
        folders = [f.read(16 if ver == 104 else 24) for _ in range(nfold)]
        recs = []
        for b in folders:
            count = struct.unpack_from('<QI', b)[1]
            dname = f.read(f.read(1)[0])[:-1].decode('latin1')
            for _ in range(count):
                _, size, off = struct.unpack('<QII', f.read(16))
                recs.append((dname, size, off))
        names = f.read(fnl_files).split(b'\0')
        for (dname, size, off), n in zip(recs, names):
            compressed = bool(aflags & 4) != bool(size & 0x40000000)
            yield f'{dname}\\{n.decode("latin1")}'.lower(), size & 0x3FFFFFFF, off, compressed, bool(aflags & 0x100), ver


class Assets:
    # Archives only: both Data folders also hold mods, and later archives in this order override earlier ones.
    ORDER = [r'skyrim - ', r'highrestexturepack', r'update', r'dawnguard', r'hearthfires', r'dragonborn', r'cc', r'_resourcepack',
             r'e - ', r'l - ']

    def __init__(self, edition):
        rank = lambda p: next((k for k, o in enumerate(self.ORDER) if p.name.lower().startswith(o)), None)
        archives = [p for p in Path(tes5.DATA[edition]).glob('*.bsa') if rank(p) is not None]
        self.files = {}
        for p in sorted(archives, key=lambda p: (rank(p), p.name.lower())):
            for name, *rest in bsa_entries(p):
                self.files[name] = (p, *rest)

    def read(self, name):
        hit = self.files.get(name.lower().replace('/', '\\'))
        if not hit:
            return None
        p, size, off, compressed, embedded, ver = hit
        with open(p, 'rb') as f:
            f.seek(off)
            blob = f.read(size)
        if embedded:
            blob = blob[1 + blob[0]:]
        if not compressed:
            return blob
        if ver == 104:
            return zlib.decompress(blob[4:])
        import lz4.frame
        return lz4.frame.decompress(blob[4:])


# ---------- meshes: LE NiTriShape and SE BSTriShape ----------

class Reader:
    def __init__(self, b, o=0):
        self.b, self.o = b, o

    def take(self, fmt):
        v = struct.unpack_from('<' + fmt, self.b, self.o)
        self.o += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]

    def array(self, dtype, n):
        a = np.frombuffer(self.b, dtype, n, self.o)
        self.o += a.nbytes
        return a

    def sized(self):
        n = self.take('I')
        self.o += n
        return self.b[self.o - n:self.o].decode('latin1')

    def short(self):
        n = self.take('B')
        self.o += n
        return self.b[self.o - n:self.o].decode('latin1')


NODES = {'NiNode', 'BSFadeNode', 'BSLeafAnimNode', 'BSTreeNode', 'BSOrderedNode', 'BSValueNode', 'BSMultiBoundNode',
         'NiBillboardNode', 'BSBlastNode', 'BSDamageStage', 'NiSwitchNode', 'NiLODNode', 'BSRangeNode', 'BSDebrisNode'}


def nif_blocks(buf):
    r = Reader(buf, buf.index(b'\n') + 1)
    version, _, _, nblocks = r.take('IBII')
    if version != 0x14020007:
        raise ValueError(hex(version))
    bs = r.take('I')
    r.short(), r.short(), r.short()
    if bs >= 103:
        r.short()
    types = [r.sized() for _ in range(r.take('H'))]
    kinds = [types[r.take('H')] for _ in range(nblocks)]
    sizes = [r.take('I') for _ in range(nblocks)]
    nstrings, _ = r.take('II')
    strings = [r.sized() for _ in range(nstrings)]
    for _ in range(r.take('I')):
        r.take('I')
    blocks, o = [], r.o
    for t, s in zip(kinds, sizes):
        blocks.append((t, buf[o:o + s]))
        o += s
    return blocks, strings


def net_fields(r):
    name = r.take('i')
    extras = r.take('I')
    r.o += 4 * extras
    r.take('i')
    return name


def av_fields(r):
    name = net_fields(r)
    flags = r.take('I')
    t = np.array(r.take('3f'), 'f8')
    rot = np.array(r.take('9f'), 'f8').reshape(3, 3)
    s = r.take('f')
    r.take('i')
    return name, flags, t, rot, s


def shape_material(blocks, shader_ref, alpha_ref):
    """None for shapes render mode 0x12 does not draw; otherwise texture and alpha test state."""
    if shader_ref < 0 or blocks[shader_ref][0] != 'BSLightingShaderProperty':
        return None
    r = Reader(blocks[shader_ref][1])
    r.take('I')
    net_fields(r)
    f1, f2 = r.take('II')
    if f1 & (SLSF1_SKINNED | SLSF1_REFRACTION | SLSF1_HIDE_SECRET) or f2 & SLSF2_HIDE_ON_LOCAL_MAP:
        return None
    r.take('4f')
    ts = r.take('i')
    r.take('4fI')
    if r.take('f') < 1:
        return None
    tex = ''
    if ts >= 0:
        rr = Reader(blocks[ts][1])
        paths = [rr.sized() for _ in range(rr.take('I'))]
        tex = paths[0] if paths else ''
    threshold = 0.0
    if alpha_ref >= 0 and blocks[alpha_ref][0] == 'NiAlphaProperty':
        ra = Reader(blocks[alpha_ref][1])
        net_fields(ra)
        flags, thr = ra.take('HB')
        if flags & 1:
            return None
        threshold = (thr + 1) / 256 if flags & 0x200 else 0.0
    return dict(tex=tex.lower(), threshold=threshold, two_sided=bool(f2 & SLSF2_DOUBLE_SIDED))


def le_shape(blocks, data):
    r = Reader(data)
    name, flags, t, rot, s = av_fields(r)
    dref, _ = r.take('ii')
    r.take('IiB')  # material count, active material, dirty flag
    shader, alpha = r.take('2i')
    material = shape_material(blocks, shader, alpha)
    if material is None or dref < 0 or blocks[dref][0] != 'NiTriShapeData':
        return None
    r = Reader(blocks[dref][1])
    r.take('i')
    n = r.take('H')
    r.take('BB')
    if not r.take('B'):
        return None
    v = r.array('<f4', n * 3).reshape(-1, 3)
    vflags = r.take('H')
    r.take('I')
    nrm = r.array('<f4', n * 3).reshape(-1, 3) if r.take('B') else None
    if nrm is not None and vflags & 0x1000:
        r.o += n * 24
    radius = r.take('4f')[3]
    if r.take('B'):
        r.o += n * 16
    uv = r.array('<f4', n * 2).reshape(-1, 2) if vflags & 1 else None
    r.take('H')
    r.take('i')
    ntri = r.take('H')
    r.take('I')
    tris = r.array('<u2', ntri * 3).reshape(-1, 3) if r.take('B') else None
    return dict(material, v=v, uv=uv, i=tris, radius=radius, flags=flags, t=t, rot=rot, s=s)


def se_shape(blocks, data):
    r = Reader(data)
    name, flags, t, rot, s = av_fields(r)
    radius = r.take('4f')[3]
    _, shader, alpha = r.take('3i')
    material = shape_material(blocks, shader, alpha)
    if material is None:
        return None
    desc = r.take('Q')
    ntri, n, size = r.take('HHI')
    if not size:
        return None
    stride = (desc & 0xF) * 4
    attrs = desc >> 44
    raw = r.array('u1', n * stride).reshape(n, stride)
    at = lambda shift: ((desc >> shift) & 0xF) * 4
    field = lambda off, dtype, count: np.frombuffer(raw[:, off:off + np.dtype(dtype).itemsize * count].tobytes(), dtype).reshape(n, count)
    v = field(0, '<f4', 3)
    uv = field(at(8), '<f2', 2).astype('f4') if attrs & 2 else None
    tris = r.array('<u2', ntri * 3).reshape(-1, 3)
    return dict(material, v=v, uv=uv, i=tris, radius=radius, flags=flags, t=t, rot=rot, s=s)


def parse_nif(buf):
    """Flat list of drawable parts in model space."""
    blocks, strings = nif_blocks(buf)
    parts = []

    def label(i):
        return strings[i].lower() if 0 <= i < len(strings) else ''

    def visit(i, m_rot, m_t, m_s):
        kind, data = blocks[i]
        if kind in NODES:
            r = Reader(data)
            name, flags, t, rot, s = av_fields(r)
            if flags & 1 or 'editormarker' in label(name) or 'collision' in label(name):
                return
            children = r.array('<i4', r.take('I'))
            rot2, t2, s2 = m_rot @ rot, m_t + m_s * (m_rot @ t), m_s * s
            for c in children:
                if c >= 0:
                    visit(int(c), rot2, t2, s2)
        elif kind in ('NiTriShape', 'BSLODTriShape', 'BSTriShape', 'BSMeshLODTriShape', 'BSSubIndexTriShape'):
            p = (le_shape if kind in ('NiTriShape', 'BSLODTriShape') else se_shape)(blocks, data)
            if p is None or p['flags'] & 1 or p['radius'] < MIN_SHAPE_RADIUS or p['i'] is None or not len(p['i']) or not len(p['v']):
                return
            rot2, t2, s2 = m_rot @ p['rot'], m_t + m_s * (m_rot @ p['t']), m_s * p['s']
            v = (p['v'].astype('f8') * s2) @ rot2.T + t2
            parts.append(dict(v=v.astype('f4'), i=p['i'].astype('u4'), tex=p['tex'], threshold=p['threshold'], two_sided=p['two_sided'],
                              uv=np.zeros((len(v), 2), 'f4') if p['uv'] is None else p['uv'].astype('f4')))

    if blocks:
        visit(0, np.eye(3), np.zeros(3), 1.0)
    return parts


# ---------- plugin index ----------

def land_fields(rec):
    layers, current = [], None
    out = dict(VHGT=None, VNML=None, VCLR=None)
    for t, v in rec.subs():
        if t in out:
            out[t] = v
        elif t == 'BTXT':
            fid, quad, _, _ = struct.unpack('<IBBh', v[:8])
            layers.append(dict(fid=rec.plugin.norm(fid), quad=quad, layer=-1, alpha=None))
        elif t == 'ATXT':
            fid, quad, _, layer = struct.unpack('<IBBh', v[:8])
            current = dict(fid=rec.plugin.norm(fid), quad=quad, layer=min(layer, 5), alpha=np.zeros((17, 17), 'f4'))
            layers.append(current)
        elif t == 'VTXT' and current is not None:
            for i in range(len(v) // 8):
                pos, _, op = struct.unpack_from('<HHf', v, i * 8)
                if pos < 289:
                    current['alpha'][pos // 17, pos % 17] = int((op * 0.01 if op > 1 else op) * 255) / 255
    return dict(out, layers=layers)


def build_index(edition):
    path = CACHE / f'index-{edition}.pkl'
    if path.exists():
        return pickle.loads(path.read_bytes())
    CACHE.mkdir(parents=True, exist_ok=True)
    print('indexing plugins', flush=True)
    records = tes5.load(edition)
    grids, cell_water, models, north_bases, ltex, txst, worlds = {}, {}, {}, set(), {}, {}, {}
    climates, weathers, imagespaces = {}, {}, {}
    for r in records.values():
        t = r.type
        if t == 'CELL':
            xclc, data, xclw = r.sub('XCLC'), r.sub('DATA'), r.sub('XCLW')
            if xclc:
                grids[r.fid] = struct.unpack('<ii', xclc[:8])
            flags = data[0] if data else 0
            cell_water[r.fid] = (bool(flags & 2), struct.unpack('<f', xclw)[0] if xclw else None)
        elif t == 'WRLD':
            dnam = r.sub('DNAM')
            pnam = r.sub('PNAM')
            worlds[r.fid] = dict(edid=r.edid, parent=r.ref('WNAM'), uses=pnam[0] if pnam else 0, climate=r.ref('CNAM'),
                                 water=struct.unpack('<ff', dnam[:8])[1] if dnam else None)
        elif t == 'TXST':
            tx = r.sub('TX00')
            if tx:
                nm = r.sub('TX01')
                txst[r.fid] = (tx.split(b'\0')[0].decode('latin1'), nm.split(b'\0')[0].decode('latin1') if nm else None)
        elif t == 'LTEX':
            ltex[r.fid] = r.ref('TNAM')
        elif t == 'CLMT':
            wlst, tnam = r.sub('WLST') or b'', r.sub('TNAM')
            entries = [struct.unpack_from('<Ii', wlst, o) for o in range(0, len(wlst) - 11, 12)]
            climates[r.fid] = dict(weathers=[(r.plugin.norm(f), c) for f, c in entries], timing=tuple(tnam[:4]) if tnam else None)
        elif t == 'WTHR':
            nam0, imsp = r.sub('NAM0'), r.sub('IMSP')
            weathers[r.fid] = dict(colours=nam0, dalc=[v for k, v in r.subs() if k == 'DALC'],
                                   imsp=[r.plugin.norm(f) for f in struct.unpack('<4I', imsp[:16])] if imsp else None)
        elif t == 'IMGS':
            hnam = r.sub('HNAM')
            if hnam:
                imagespaces[r.fid] = struct.unpack('<9f', hnam[:36])
    for r in records.values():
        if r.type in MODEL_TYPES:
            if r.edid == 'NorthMarker':
                north_bases.add(r.fid)
            if r.flags & (HIDDEN_FROM_MAP | IS_MARKER) or 'marker' in r.edid.lower():
                continue
            modl = r.sub('MODL')
            if modl:
                models[r.fid] = modl.split(b'\0')[0].decode('latin1')
    interiors, exteriors, land, by_ref, north, base_refs = {}, {}, {}, {}, {}, {}
    for r in records.values():
        if r.type not in ('REFR', 'ACHR', 'LAND'):
            continue
        cell, wrld = r.cell_world()
        if r.type == 'LAND':
            if wrld is not None and cell in grids:
                land[(wrld, *grids[cell])] = (r.raw, r.flags, r.plugin.name)
            continue
        data, base = r.sub('DATA'), r.ref('NAME')
        if not data or base is None:
            continue
        pos = struct.unpack('<6f', data[:24])
        by_ref[r.fid] = (wrld, cell, pos)
        if r.type != 'REFR' or r.flags & DELETED:
            continue
        if base in north_bases and wrld is None:
            north[cell] = pos[5]
        if r.flags & (DISABLED | HIDDEN_FROM_MAP) or base not in models:
            continue
        scale = r.sub('XSCL')
        ref = (base, pos, struct.unpack('<f', scale)[0] if scale else 1.0)
        if wrld is None:
            interiors.setdefault(cell, []).append(ref)
        else:
            exteriors.setdefault((wrld, int(pos[0] // CELL), int(pos[1] // CELL)), []).append(ref)
    index = dict(models=models, ltex=ltex, txst=txst, interiors=interiors, exteriors=exteriors, land=land, by_ref=by_ref,
                 north=north, worlds=worlds, cell_water=cell_water, climates=climates, weathers=weathers, imagespaces=imagespaces)
    index['cell_grid'] = {}
    for r in records.values():
        if r.type == 'CELL' and r.fid in grids:
            _, wrld = r.cell_world()
            index['cell_grid'][(wrld, *grids[r.fid])] = r.fid
    path.write_bytes(pickle.dumps(index, protocol=4))
    return index


# ---------- land ----------

def read_land(entry, plugins):
    raw, flags, name = entry
    rec = tes5.Rec()
    rec.type, rec.flags, rec.raw, rec.plugin, rec.path, rec.fid, rec._d = 'LAND', flags, raw, plugins[name], (), 0, None
    return land_fields(rec)


def land_mesh(rec, gx, gy):
    raw = rec['VHGT']
    if not raw:
        return None
    offset = struct.unpack('<f', raw[:4])[0]
    deltas = np.frombuffer(raw[4:4 + 1089], 'i1').reshape(33, 33).astype('f8')
    h = np.zeros((33, 33))
    row = offset
    for r in range(33):
        row += deltas[r, 0]
        h[r, 0] = row
        h[r, 1:] = row + np.cumsum(deltas[r, 1:])
    h *= 8
    xs, ys = np.meshgrid(np.arange(33) * 128.0 + gx * CELL, np.arange(33) * 128.0 + gy * CELL)
    v = np.stack([xs, ys, h], -1).reshape(-1, 3).astype('f4')
    if rec['VNML'] and len(rec['VNML']) >= 3267:
        n = np.frombuffer(rec['VNML'][:3267], 'i1').reshape(-1, 3).astype('f4') / 127
    else:
        n = np.tile(np.array([0, 0, 1], 'f4'), (1089, 1))
    u, w = np.meshgrid(np.arange(33) / 32, np.arange(33) / 32)
    uv = np.stack([u, w], -1).reshape(-1, 2).astype('f4')
    ids = []
    for r in range(32):
        for c in range(32):
            a, b, d, e = r * 33 + c, r * 33 + c + 1, (r + 1) * 33 + c, (r + 1) * 33 + c + 1
            ids += [a, b, e, a, e, d]
    return dict(v=v, n=n, uv=uv, col=np.ones_like(v), i=np.array(ids, 'u4').reshape(-1, 3), h=h)


def land_lighting(index, wrld):
    """Sun and ambient for land at MAP_HOUR, in the climate's most likely weather."""
    world = index['worlds'][wrld]
    while world.get('uses', 0) & USE_PARENT_CLIMATE and world.get('parent'):
        world = index['worlds'][world['parent']]
    climate = index['climates'].get(world.get('climate'))
    weathers = climate and [w for w in climate['weathers'] if w[0] in index['weathers']]
    if not weathers:
        to_sun = np.array([0.0, SUN_Y, SUN_Z])
        return dict(sun=NO_WEATHER_SUN, to_sun=to_sun / np.linalg.norm(to_sun), ambient_axes=np.zeros((3, 3)), ambient_mean=NO_WEATHER_AMBIENT)
    weather = index['weathers'][max(weathers, key=lambda w: w[1])[0]]
    sun = np.frombuffer(weather['colours'], 'u1').reshape(-1, 4, 4)[SUNLIGHT_COLOUR, DAY, :3] / 255
    sunlight_scale = index['imagespaces'][weather['imsp'][DAY]][6]
    t0, t1, t2, t3 = climate['timing']
    rise, sunset = (t0 + t1) / 12, (t2 + t3) / 12
    x = SUN_EXTREME_X * (1 - 2 * (MAP_HOUR - rise + 1) / (sunset - rise + 2))
    to_sun = np.array([x, SUN_Y, SUN_Z])
    c = np.frombuffer(weather['dalc'][DAY][:24], 'u1').reshape(6, 4)[:, :3] / 255
    return dict(sun=sun * sunlight_scale, to_sun=to_sun / np.linalg.norm(to_sun),
                ambient_axes=(c[1::2] - c[0::2]).T / 2, ambient_mean=c.mean(0))


def upsample(grid, size):
    """Bilinear resize of a (33, 33, n) float grid."""
    return np.stack([np.asarray(Image.fromarray(grid[..., i].astype('f4'), 'F').resize((size, size), Image.BILINEAR))
                     for i in range(grid.shape[-1])], -1)


def land_color(rec, part, tile_of, light):
    """The lit land shader, baked: (sun * sat(n.l) + ambient(n)) * albedo * vertex colour * LAND_OUTPUT_MULT. Clip-space fog is 0."""
    S = 21 * LAND_REPEATS // 2
    albedo, normal = np.zeros((S * 2, S * 2, 3), 'f4'), np.zeros((S * 2, S * 2, 3), 'f4')
    for quad in range(4):
        y0, x0 = (quad >> 1) * S, (quad & 1) * S
        base = next((l['fid'] for l in rec['layers'] if l['quad'] == quad and l['alpha'] is None), None)
        tile, bump = np.zeros((S, S, 3), 'f4'), np.zeros((S, S, 3), 'f4')
        total = np.zeros((S, S, 1), 'f4')
        for l in rec['layers']:
            if l['quad'] != quad or l['alpha'] is None or l['layer'] >= 5 or l['fid'] == base:
                continue
            alpha = np.asarray(Image.fromarray(l['alpha']).resize((S, S), Image.BILINEAR))[..., None]
            tex, nm = tile_of(l['fid'])
            tile, bump, total = tile + tex * alpha, bump + nm * alpha, total + alpha
        tex, nm = tile_of(base) if base is not None else (np.full((S, S, 3), 0.3, 'f4'), np.tile(np.array([0, 0, 1], 'f4'), (S, S, 1)))
        rest = np.clip(1 - total, 0, 1)
        tile, bump = tile + tex * rest, bump + nm * rest
        albedo[y0:y0 + S, x0:x0 + S] = tile
        normal[y0:y0 + S, x0:x0 + S] = bump
    h = part['h']
    tangent = np.stack([np.full_like(h, 256.0), np.zeros_like(h), np.gradient(h, axis=1) * 2], -1)
    binormal = np.stack([np.zeros_like(h), np.full_like(h, 256.0), np.gradient(h, axis=0) * 2], -1)
    unit = lambda a: a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-6)
    t, b = unit(upsample(tangent, S * 2)), unit(upsample(binormal, S * 2))
    n = unit(upsample(part['n'].reshape(33, 33, 3), S * 2))
    world = unit(t * normal[..., :1] + b * normal[..., 1:2] + n * normal[..., 2:])
    diffuse = np.clip(world @ light['to_sun'], 0, 1)[..., None] * light['sun'] + world @ light['ambient_axes'].T + light['ambient_mean']
    img = albedo * diffuse * LAND_OUTPUT_MULT
    if rec['VCLR'] and len(rec['VCLR']) >= 3267:
        vc = np.frombuffer(rec['VCLR'][:3267], 'u1').reshape(33, 33, 3)
        img = img * upsample(vc.astype('f4') / 255, S * 2)
    return (np.clip(img, 0, 1) * 255).astype('u1')


# ---------- renderer ----------

VERT = """#version 330
uniform vec4 frame; uniform vec2 depth;
in vec3 p; in vec2 uv; in vec3 c;
out vec2 vuv; out vec3 vc;
void main(){
  float z01 = (depth.x - p.z - 100.0) / (depth.y - 100.0);
  gl_Position = vec4((p.x - frame.x) / frame.z, (p.y - frame.y) / frame.w, z01 * 2.0 - 1.0, 1.0);
  vuv = uv; vc = c;
}"""
FRAG = """#version 330
uniform sampler2D base; uniform float threshold;
in vec2 vuv; in vec3 vc; out vec4 o;
void main(){
  vec4 t = texture(base, vuv);
  if (t.a < threshold) discard;
  o = vec4(t.rgb * vc, 1.0);
}"""


def local_map_shader(image, backdrop=BACKDROP):
    """ISLocalMap, drawn straight-alpha over the menu. Alpha's (1 - a) term is fog of war, left fully explored."""
    h, w = image.shape[:2]
    scene = image[..., :3]
    pad = np.pad(scene, ((1, 1), (1, 1), (0, 0)), mode='edge')
    at = lambda dx, dy: pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
    card, diag = np.array([1, 0.5, 2]), np.array([0.5, 0.25, 1])
    gy = (at(-1, -1) + at(1, -1) - at(-1, 1) - at(1, 1)) * diag + (at(0, -1) - at(0, 1)) * card
    gx = (at(-1, -1) + at(-1, 1) - at(1, -1) - at(1, 1)) * diag + (at(-1, 0) - at(1, 0)) * card
    edge = ((gx * gx + gy * gy) * 4).sum(-1) * 1.75
    luma = scene @ np.array([0.3, 0.59, 0.11])
    yy, xx = np.mgrid[0:h, 0:w]
    vignette = (1 - (2 * np.abs((xx + 0.5) / w - 0.5)) ** 5) * (1 - (2 * np.abs((yy + 0.5) / h - 0.5)) ** 5)
    alpha = (np.clip(luma + edge, 0, 1) * vignette)[..., None]
    colour = np.clip(luma * 1.04, 0, 1)[..., None]
    return np.clip(colour * alpha + backdrop * (1 - alpha), 0, 1)


def euler(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    rot_x = np.array([[1, 0, 0], [0, cx, sx], [0, -sx, cx]])
    rot_y = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
    rot_z = np.array([[cz, sz, 0], [-sz, cz, 0], [0, 0, 1]])
    return rot_z @ rot_y @ rot_x  # column vectors; game angles run clockwise


def north_view(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


class Renderer:
    def __init__(self, index, edition, repeats=LAND_REPEATS):
        self.index, self.edition, self.repeats = index, edition, repeats
        self.assets = Assets(edition)
        self.gl = moderngl.create_standalone_context()
        self.program = self.gl.program(vertex_shader=VERT, fragment_shader=FRAG)
        self.white = self.gl.texture((1, 1), 4, b'\xff\xff\xff\xff')
        self.textures, self.tiles, self.meshes, self.plugins = {}, {}, {}, {}
        self.skipped = {}

    def plugin(self, name):
        if name not in self.plugins:
            # The Skyrim site's Plugin takes an edition, the Enderal site's a data folder.
            source = self.edition if tes5.Plugin.__init__.__code__.co_varnames[1] == 'edition' else tes5.DATA[self.edition]
            self.plugins[name] = tes5.Plugin(source, name)
        return self.plugins[name]

    def mesh(self, name):
        key = name.lower()
        if key not in self.meshes:
            blob = self.assets.read('meshes\\' + key)
            parts = []
            if blob:
                try:
                    parts = parse_nif(blob)
                except Exception as e:
                    self.skipped[key] = repr(e)[:100]
            self.meshes[key] = parts
        return self.meshes[key]

    def image(self, name):
        name = name.lower().replace('/', '\\')
        name = name[name.rfind('textures\\'):] if 'textures\\' in name else 'textures\\' + name  # some paths carry a build folder
        cached = CACHE / 'tex' / (hashlib.sha1(f'{self.edition}{name}'.encode()).hexdigest() + '.png')
        if cached.exists():
            return Image.open(cached).convert('RGBA')
        blob = self.assets.read(name)
        if not blob:
            return None
        try:
            im = Image.open(io.BytesIO(blob)).convert('RGBA')
        except Exception:
            return None
        im.thumbnail((256, 256))
        cached.parent.mkdir(parents=True, exist_ok=True)
        im.save(cached)
        return im

    def texture(self, name):
        if not name:
            return self.white
        key = name.lower()
        if key not in self.textures:
            im = self.image(name)
            if im is None:
                self.textures[key] = self.white
            else:
                tex = self.gl.texture(im.size, 4, im.tobytes())
                tex.build_mipmaps()
                tex.repeat_x = tex.repeat_y = True
                self.textures[key] = tex
        return self.textures[key]

    def land_tile(self, fid):
        """Colour and tangent-space normal, tiled to one quadrant's repeats."""
        if fid not in self.tiles:
            paths = self.index['txst'].get(self.index['ltex'].get(fid)) or (None, None)
            n = self.repeats // 2
            S = 21 * n
            im, nm = (self.image(p) if p else None for p in paths)
            arr = np.full((S, S, 3), 0.3, 'f4')
            bump = np.tile(np.array([0, 0, 1], 'f4'), (S, S, 1))
            if im is not None:
                small = im.convert('RGB').resize((21, 21), Image.BILINEAR)
                arr = np.tile(np.asarray(small, 'f4') / 255, (n, n, 1))
            if nm is not None:
                small = nm.convert('RGB').resize((21, 21), Image.BILINEAR)
                bump = np.tile(np.asarray(small, 'f4') / 127.5 - 1, (n, n, 1))
            self.tiles[fid] = (arr, bump)
        return self.tiles[fid]

    def gather(self, refs, view):
        groups = {}
        for base, pos, scale in refs:
            name = self.index['models'].get(base)
            if not name:
                continue
            rot = euler(pos[3], pos[4], pos[5])
            for part in self.mesh(name):
                vw = (part['v'].astype('f8') * scale) @ rot.T + np.array(pos[:3])
                key = (part['tex'], part['threshold'], part['two_sided'])
                groups.setdefault(key, []).append((vw @ view.T, part['uv'], np.ones_like(vw), part['i']))
        return groups

    def buffers(self, items):
        arrays, indices, offset = [], [], 0
        for v, uv, col, tris in items:
            arrays.append(np.hstack([v, uv, col]).astype('f4'))
            indices.append(tris.astype('u4') + offset)
            offset += len(v)
        return self.gl.buffer(np.vstack(arrays).tobytes()), self.gl.buffer(np.vstack(indices).tobytes())

    def scene_pass(self, refs, center, size, zrange, lands=(), view=np.eye(3), upp=UNITS_PER_PX):
        """Colour target, cleared to black as the engine does before the local map draw."""
        groups = self.gather(refs, view)
        cam_z = zrange[1] + CAMERA_LIFT
        far = cam_z - zrange[0] + NEAR
        draws = [(self.texture(k[0]), k[1], k[2], items) for k, items in groups.items()]
        draws += [(tex, 0.0, False, [(p['v'] @ view.T, p['uv'], p['col'], p['i'])]) for p, tex in lands]
        fbo = self.gl.simple_framebuffer(size, components=4, dtype='f1')
        fbo.use()
        fbo.clear(0, 0, 0, 1, depth=1.0)
        self.gl.enable(moderngl.DEPTH_TEST)
        p = self.program
        p['frame'] = (center[0], center[1], size[0] * upp / 2, size[1] * upp / 2)
        p['depth'] = (cam_z, far)
        for tex, threshold, two_sided, items in draws:
            (self.gl.disable if two_sided else self.gl.enable)(moderngl.CULL_FACE)
            vbo, ibo = self.buffers(items)
            vao = self.gl.vertex_array(p, [(vbo, '3f 2f 3f', 'p', 'uv', 'c')], ibo)
            tex.use(0)
            p['threshold'] = threshold
            vao.render(moderngl.TRIANGLES)
            vao.release(); vbo.release(); ibo.release()
        arr = np.frombuffer(fbo.read(components=4, dtype='f1'), 'u1').reshape(size[1], size[0], 4)
        fbo.release()
        return arr[::-1].astype('f8') / 255


def water_quads(r, wrld, cells):
    """Black flat planes at each cell's water height: the map does not draw water, only the land's edge against it."""
    out = []
    world = r.index['worlds'].get(wrld, {})
    if world.get('uses', 0) & USE_PARENT_WATER and world.get('parent'):
        wrld = world['parent']
        world = r.index['worlds'].get(wrld, {})
    for gx, gy in cells:
        fid = r.index['cell_grid'].get((wrld, gx, gy))
        has, z = r.index['cell_water'].get(fid, (False, None))
        if not has:
            continue
        if z is None or abs(z) > 1e7:
            z = world.get('water')
        if z is None or abs(z) > 1e7:
            continue
        out.append((z, gx, gy))
    return out


def plane_mesh(z, gx, gy):
    x0, y0 = gx * CELL, gy * CELL
    v = np.array([[x0, y0, z], [x0 + CELL, y0, z], [x0 + CELL, y0 + CELL, z], [x0, y0 + CELL, z]], 'f4')
    return dict(v=v, n=np.tile(np.array([0, 0, 1], 'f4'), (4, 1)), uv=np.zeros((4, 2), 'f4'), col=np.zeros((4, 3), 'f4'),
                i=np.array([[0, 1, 2], [0, 2, 3]], 'u4'), h=np.array([z]))


def land_source(r, wrld):
    """The world whose LAND a world draws: its parent's when PNAM has the use-land-data bit."""
    world = r.index['worlds'].get(wrld, {})
    return world['parent'] if world.get('uses', 0) & USE_PARENT_LAND and world.get('parent') else wrld


def exterior_scene(r, wrld, x, y, size, upp):
    half = max(size) * upp / 2
    g0x, g1x = int((x - half) // CELL), int((x + half) // CELL)
    g0y, g1y = int((y - half) // CELL), int((y + half) // CELL)
    cells = [(gx, gy) for gx in range(g0x, g1x + 1) for gy in range(g0y, g1y + 1)]
    refs, lands, zrange = [], [], None
    land_world = land_source(r, wrld)
    light = land_lighting(r.index, wrld)
    for gx in range(g0x - 1, g1x + 2):
        for gy in range(g0y - 1, g1y + 2):
            refs += r.index['exteriors'].get((wrld, gx, gy), [])
    for gx, gy in cells:
        entry = r.index['land'].get((land_world, gx, gy))
        if not entry:
            continue
        rec = read_land(entry, _Plugins(r))
        part = land_mesh(rec, gx, gy)
        if part is None:
            continue
        img = land_color(rec, part, r.land_tile, light)
        tex = r.gl.texture((img.shape[1], img.shape[0]), 3, img.tobytes())
        tex.build_mipmaps()
        lands.append((part, tex))
        low, high = float(part['h'].min()), float(part['h'].max())
        zrange = (min(zrange[0], low), max(zrange[1], high)) if zrange else (low, high)
    for z, gx, gy in water_quads(r, wrld, cells):
        lands.append((plane_mesh(z, gx, gy), r.white))
    return refs, lands, zrange or (0.0, 1.0)


class _Plugins:
    def __init__(self, r):
        self.r = r

    def __getitem__(self, name):
        return self.r.plugin(name)


def interior_scene(r, cell):
    refs = r.index['interiors'].get(cell, [])
    low, high = [], []
    for base, pos, scale in refs:
        name = r.index['models'].get(base)
        for part in r.mesh(name) if name else []:
            low.append(part['v'].min(0) * scale + pos[:3])
            high.append(part['v'].max(0) * scale + pos[:3])
    if not low:
        return refs, (0.0, 1.0)
    low, high = np.min(low, 0), np.max(high, 0)
    mid, radius = (low + high) / 2, np.linalg.norm(high - low) / 2
    return refs, (float(mid[2] - radius), float(mid[2] + radius))


def interior_frame(r, refs, view, item, size):
    """Fits the cell to the image, zooming small ones, and keeps the item well inside the frame."""
    lows, highs = [], []
    for base, pos, scale in refs:
        name = r.index['models'].get(base)
        rot = euler(pos[3], pos[4], pos[5])
        for part in r.mesh(name) if name else []:
            v = ((part['v'] * scale) @ rot.T + np.array(pos[:3])) @ view.T
            lows.append(v[:, :2].min(0))
            highs.append(v[:, :2].max(0))
    if not lows:
        return tuple(item), UNITS_PER_PX
    low = np.minimum(np.percentile(lows, 1, axis=0), item)  # percentiles drop stray objects far from the rooms
    high = np.maximum(np.percentile(highs, 99, axis=0), item)
    side = (high - low).max() * FRAME_MARGIN
    upp = float(np.clip(side / max(size), UNITS_PER_PX / MAX_ZOOM, UNITS_PER_PX))
    reach = np.array(size) * upp * 0.38
    center = np.clip((low + high) / 2, np.array(item) - reach, np.array(item) + reach)
    return (float(center[0]), float(center[1])), upp


def draw_pin(rgb, x, y):
    S, R = 4, 8
    im = Image.fromarray((rgb * 255 + 0.5).astype('u1'), 'RGB')
    stamp = Image.new('RGBA', ((R * 2 + 2) * S,) * 2, (0, 0, 0, 0))
    d = ImageDraw.Draw(stamp)
    mid = (R + 1) * S
    d.ellipse([mid - R * S, mid - R * S, mid + R * S, mid + R * S], fill=(255, 255, 255, 255))
    d.ellipse([mid - (R - 2) * S, mid - (R - 2) * S, mid + (R - 2) * S, mid + (R - 2) * S], fill=(200, 40, 30, 255))
    stamp = stamp.resize((R * 2 + 2,) * 2, Image.LANCZOS)
    im.paste(stamp, (round(x) - R - 1, round(y) - R - 1), stamp)
    return im


def finish(image, size):
    rgb = local_map_shader(image)
    bands = [np.asarray(Image.fromarray(rgb[..., c].astype('f4')).resize(size, Image.BILINEAR), 'f8') for c in range(3)]
    return np.clip(np.stack(bands, -1), 0, 1)


def render_point(r, wrld, x, y, size=OUTPUT_SIZE):
    target = (size[0] // RT_SCALE, size[1] // RT_SCALE)
    refs, lands, zrange = exterior_scene(r, wrld, x, y, target, UNITS_PER_PX)
    image = r.scene_pass(refs, (x, y), target, zrange, lands=lands, upp=UNITS_PER_PX)
    for _, tex in lands:
        if tex is not r.white:
            tex.release()
    return draw_pin(finish(image, size), size[0] / 2, size[1] / 2)


def render_ref(r, fid, size=OUTPUT_SIZE):
    wrld, cell, pos = r.index['by_ref'][fid]
    if wrld is not None:
        return render_point(r, wrld, pos[0], pos[1], size)
    target = (size[0] // RT_SCALE, size[1] // RT_SCALE)
    refs, zrange = interior_scene(r, cell)
    view = north_view(r.index['north'].get(cell, 0.0))
    item = (view @ np.array([pos[0], pos[1], 0]))[:2]
    center, upp = interior_frame(r, refs, view, item, target)
    image = r.scene_pass(refs, center, target, zrange, view=view, upp=upp)
    return draw_pin(finish(image, size), size[0] / 2 + (item[0] - center[0]) / upp * RT_SCALE,
                    size[1] / 2 - (item[1] - center[1]) / upp * RT_SCALE)


def item_position(item):
    """The placed reference an item's map centres on: Enderal's ref or holder, or the first one in a Skyrim item's rules."""
    keys = getattr(tes5, 'KEYS', None)
    if keys is None:
        plugin, fid = (item['plugin'], item['ref']) if item.get('ref') else (item.get('holderPlugin'), item.get('holder'))
        return ((tes5.FS if plugin == 'fs' else tes5.SKYRIM) << 24) | fid if fid else None
    for rule in item.get('rule', []):
        at = rule.get('ref') or rule.get('lost') or rule.get('wall')
        if at:
            return (keys.index(at[0]) << 24) | at[1]
    return None


def item_target(item, index):
    """A placed reference's form ID, or (world, x, y) for an item known only by its map pin."""
    fid = item_position(item)
    if fid in index['by_ref']:
        return fid
    pin = item.get('map')
    if pin and pin['world'] in MAP_TAB_WORLDS:
        return MAP_TAB_WORLDS[pin['world']], pin['x'], pin['y']
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--edition', default='se')
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--ref', nargs='*', default=[], help='hex form IDs to render instead of items')
    ap.add_argument('--out', default=str(OUT))
    args = ap.parse_args()
    index = build_index(args.edition)
    r = Renderer(index, args.edition)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(ref, int(ref, 16)) for ref in args.ref]
    if not args.ref:
        items = json.loads((ROOT / 'docs' / 'data' / 'collectibles.json').read_text(encoding='utf8'))['items']
        jobs = [(i['id'], item_target(i, index)) for i in items if not args.only or i['id'] in args.only]
    missing = []
    for n, (name, target) in enumerate(jobs):
        if target is None or (isinstance(target, int) and target not in index['by_ref']):
            missing.append(name)
            continue
        t = time.time()
        image = render_point(r, *target) if isinstance(target, tuple) else render_ref(r, target)
        image.save(out / f'{name}.webp', quality=88, method=6)
        print(n + 1, len(jobs), name, round(time.time() - t, 2), flush=True)
    if missing:
        print('no reference found:', missing)
    if r.skipped:
        print('meshes not read:', r.skipped)


if __name__ == '__main__':
    main()
