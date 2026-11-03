"""Minimal reader for Skyrim LE meshes (NIF 20.2.0.7, user version 12): tri-shapes with transforms, UVs and textures."""
import struct

TEXTURED = 0x1
TANGENTS = 0x1000


class R:
    def __init__(self, b, o=0):
        self.b, self.o = b, o

    def take(self, fmt):
        v = struct.unpack_from('<' + fmt, self.b, self.o)
        self.o += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]

    def sized(self):
        n = self.take('I')
        s = self.b[self.o:self.o + n].decode('latin1')
        self.o += n
        return s

    def short(self):
        n = self.take('B')
        s = self.b[self.o:self.o + n].decode('latin1')
        self.o += n
        return s


def parse(buf):
    end = buf.index(b'\n')
    r = R(buf, end + 1)
    version, _, user, nblocks = r.take('IBII')
    assert version == 0x14020007, hex(version)
    bs_version = r.take('I')
    r.short(), r.short(), r.short()
    if bs_version >= 103:
        r.short()
    types = [r.sized() for _ in range(r.take('H'))]
    type_of = [types[r.take('H')] for _ in range(nblocks)]
    sizes = [r.take('I') for _ in range(nblocks)]
    nstrings, _ = r.take('II')
    strings = [r.sized() for _ in range(nstrings)]
    for _ in range(r.take('I')):
        r.take('I')
    blocks, o = [], r.o
    for t, s in zip(type_of, sizes):
        blocks.append((t, buf[o:o + s]))
        o += s
    return blocks, strings


def object_net(r):
    """Name, extra data and controller refs."""
    r.take('i')
    n = r.take('I')
    r.o += 4 * n
    r.take('i')


def av_object(r):
    """NiAVObject fields after the name: returns (translation, rotation rows, scale)."""
    n = r.take('I')
    r.o += 4 * n
    r.take('i')
    r.take('I')
    t = r.take('3f')
    rot = [r.take('3f') for _ in range(3)]
    s = r.take('f')
    r.take('I')
    return t, rot, s


def node(data):
    r = R(data)
    name = r.take('i')
    tr = av_object(r)
    children = [r.take('i') for _ in range(r.take('I'))]
    return name, tr, children


def tri_shape(data):
    r = R(data)
    name = r.take('i')
    tr = av_object(r)
    data_ref, skin = r.take('ii')
    r.take('I')
    r.take('B')
    props = r.take('2i')
    return name, tr, data_ref, props


def tri_data(data):
    r = R(data)
    r.take('i')
    n = r.take('H')
    r.take('BB')
    verts = [r.take('3f') for _ in range(n)] if r.take('B') else []
    flags = r.take('H')
    r.take('I')
    normals = [r.take('3f') for _ in range(n)] if r.take('B') else []
    if normals and flags & TANGENTS:
        r.o += n * 24
    r.take('4f')
    colors = [r.take('4f') for _ in range(n)] if r.take('B') else []
    uvs = [r.take('2f') for _ in range(n)] if flags & TEXTURED else []
    r.take('H')
    r.take('i')
    ntri = r.take('H')
    r.take('I')
    tris = [r.take('3H') for _ in range(ntri)] if r.take('B') else []
    return verts, normals, uvs, colors, tris


def shader_textures(blocks, props):
    """Diffuse texture path of the BSLightingShaderProperty or BSEffectShaderProperty among `props`."""
    for p in props:
        if p < 0:
            continue
        t, data = blocks[p]
        if t == 'BSLightingShaderProperty':
            r = R(data)
            r.take('I')
            object_net(r)
            r.take('II')
            r.take('4f')
            ts = r.take('i')
            emissive = r.take('3f')
            emissive_mult = r.take('f')
            if ts >= 0:
                rr = R(blocks[ts][1])
                paths = [rr.sized() for _ in range(rr.take('I'))]
                return dict(kind='lit', texture=paths[0] if paths else '', glow=paths[2] if len(paths) > 2 else '',
                            emissive=emissive, emissive_mult=emissive_mult)
        if t == 'BSEffectShaderProperty':
            r = R(data)
            object_net(r)
            r.take('II')
            r.take('4f')
            source = r.sized()
            r.take('I')
            r.take('4f')
            colour = r.take('4f')
            mult = r.take('f')
            r.take('f')
            return dict(kind='effect', texture=source, emissive=colour[:3], emissive_mult=mult, alpha=colour[3],
                        greyscale=r.sized())
    return {}


def meshes(buf):
    """Every tri-shape in world space: (vertices, uvs, triangles, shader info), following the node hierarchy."""
    blocks, _ = parse(buf)
    out = []

    def apply(tr, v):
        t, rot, s = tr
        return tuple(t[i] + s * sum(rot[i][j] * v[j] for j in range(3)) for i in range(3))

    def visit(i, chain):
        t, data = blocks[i]
        if t in ('NiNode', 'BSFadeNode', 'BSLeafAnimNode', 'BSOrderedNode', 'BSValueNode', 'BSMultiBoundNode', 'NiBillboardNode'):
            _, tr, children = node(data)
            for c in children:
                if c >= 0:
                    visit(c, chain + [tr])
        elif t in ('NiTriShape', 'NiTriStrips', 'BSLODTriShape'):
            _, tr, dref, props = tri_shape(data)
            if dref < 0 or blocks[dref][0] != 'NiTriShapeData':
                return
            verts, normals, uvs, colors, tris = tri_data(blocks[dref][1])
            world = []
            for v in verts:
                for tf in reversed(chain + [tr]):
                    v = apply(tf, v)
                world.append(v)
            out.append(dict(verts=world, uvs=uvs, tris=tris, colors=colors, shader=shader_textures(blocks, props)))

    visit(0, [])
    return out
