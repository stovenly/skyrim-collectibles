"""Skyrim BSA reader: LE archives (v104, zlib) and SE/VR archives (v105, LZ4 frames)."""
import struct, sys, zlib
from pathlib import Path
import lz4.frame
import tes5

EMBED_NAMES = 0x100
COMPRESSED = 0x4


def entries(path):
    with open(path, 'rb') as f:
        magic, ver, off, aflags, nfold, nfile, _, fnl_files, _ = struct.unpack('<4s8I', f.read(36))
        assert ver in (104, 105), f'{path.name}: BSA v{ver}'
        folders = [f.read(16 if ver == 104 else 24) for _ in range(nfold)]
        counts = [struct.unpack_from('<QI', b)[1] for b in folders]
        recs = []
        for cnt in counts:
            dname = f.read(f.read(1)[0])[:-1].decode('latin1')
            for _ in range(cnt):
                _, size, foff = struct.unpack('<QII', f.read(16))
                recs.append((dname, size, foff))
        names = f.read(fnl_files).split(b'\0')
        for (dname, size, foff), n in zip(recs, names):
            compressed = bool(aflags & COMPRESSED) != bool(size & 0x40000000)
            yield f'{dname}\\{n.decode("latin1")}', size & 0x3FFFFFFF, foff, compressed, bool(aflags & EMBED_NAMES), ver


def read(path, size, foff, compressed, embedded, ver):
    with open(path, 'rb') as f:
        f.seek(foff)
        blob = f.read(size)
    if embedded:
        blob = blob[1 + blob[0]:]
    if not compressed:
        return blob
    return zlib.decompress(blob[4:]) if ver == 104 else lz4.frame.decompress(blob[4:])


_index = {}


def index(edition):
    if edition not in _index:
        out = {}
        for p in sorted(Path(tes5.DATA[edition]).glob('*.bsa')):
            for name, *rest in entries(p):
                out.setdefault(name.lower(), (p, *rest))
        _index[edition] = out
    return _index[edition]


def extract(edition, name):
    hit = index(edition).get(name.lower().replace('/', '\\'))
    return read(*hit) if hit else None


if __name__ == '__main__':
    ed = sys.argv[2]
    if sys.argv[1] == 'ls':
        for name, (p, *_) in index(ed).items():
            if all(k in name for k in sys.argv[3].lower().split()):
                print(p.name, name)
    elif sys.argv[1] == 'x':
        b = extract(ed, sys.argv[3])
        Path(sys.argv[4]).write_bytes(b)
        print(len(b))
