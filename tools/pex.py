"""Compiled Papyrus (.pex) disassembler for Skyrim scripts: python pex.py <edition> <script name> [function regex]"""
import re, struct, sys

OPS = {
    0: ('nop', 0), 1: ('iadd', 3), 2: ('fadd', 3), 3: ('isub', 3), 4: ('fsub', 3), 5: ('imul', 3), 6: ('fmul', 3),
    7: ('idiv', 3), 8: ('fdiv', 3), 9: ('imod', 3), 10: ('not', 2), 11: ('ineg', 2), 12: ('fneg', 2), 13: ('assign', 2),
    14: ('cast', 2), 15: ('cmp_eq', 3), 16: ('cmp_lt', 3), 17: ('cmp_le', 3), 18: ('cmp_gt', 3), 19: ('cmp_ge', 3),
    20: ('jmp', 1), 21: ('jmpt', 2), 22: ('jmpf', 2), 23: ('callmethod', 3), 24: ('callparent', 2), 25: ('callstatic', 3),
    26: ('return', 1), 27: ('strcat', 3), 28: ('propget', 3), 29: ('propset', 3), 30: ('array_create', 2),
    31: ('array_length', 2), 32: ('array_getelement', 3), 33: ('array_setelement', 3), 34: ('array_findelement', 4),
    35: ('array_rfindelement', 4),
}
VARARGS = {23, 24, 25}


class Pex:
    def __init__(self, b):
        self.b, self.o = b, 0
        assert self.u32() == 0xFA57C0DE
        self.o += 2 + 2 + 8
        for _ in range(3):
            self.wstr()
        self.strings = [self.wstr() for _ in range(self.u16())]
        if self.u8():
            self.o += 8
            for _ in range(self.u16()):
                self.o += 2 * 3 + 1
                n = self.u16()
                self.o += 2 * n
        for _ in range(self.u16()):
            self.o += 3
        self.objects = [self.obj() for _ in range(self.u16())]

    def u8(self):
        self.o += 1
        return self.b[self.o - 1]

    def u16(self):
        self.o += 2
        return struct.unpack_from('>H', self.b, self.o - 2)[0]

    def u32(self):
        self.o += 4
        return struct.unpack_from('>I', self.b, self.o - 4)[0]

    def wstr(self):
        n = self.u16()
        self.o += n
        return self.b[self.o - n:self.o].decode('cp1252')

    def s(self):
        return self.strings[self.u16()]

    def var(self):
        t = self.u8()
        if t == 0:
            return None
        if t in (1, 2):
            v = self.s()
            return v if t == 1 else repr(v)
        if t == 3:
            self.o += 4
            return struct.unpack_from('>i', self.b, self.o - 4)[0]
        if t == 4:
            self.o += 4
            return round(struct.unpack_from('>f', self.b, self.o - 4)[0], 4)
        if t == 5:
            return bool(self.u8())
        raise ValueError(t)

    def func(self):
        f = dict(ret=self.s(), doc=self.s())
        self.o += 4 + 1
        f['params'] = [(self.s(), self.s()) for _ in range(self.u16())]
        f['locals'] = [(self.s(), self.s()) for _ in range(self.u16())]
        code = []
        for _ in range(self.u16()):
            op = self.u8()
            name, n = OPS[op]
            args = [self.var() for _ in range(n)]
            if op in VARARGS:
                args += [self.var() for _ in range(self.var())]
            code.append((name, args))
        f['code'] = code
        return f

    def obj(self):
        name = self.s()
        self.o += 4
        o = dict(name=name, parent=self.s(), doc=self.s())
        self.o += 4
        o['autostate'] = self.s()
        o['vars'] = []
        for _ in range(self.u16()):
            vn, vt = self.s(), self.s()
            self.o += 4
            o['vars'].append((vn, vt, self.var()))
        o['props'] = []
        for _ in range(self.u16()):
            pn, pt, _ = self.s(), self.s(), self.s()
            self.o += 4
            flags = self.u8()
            if flags & 4:
                self.s()
            else:
                if flags & 1:
                    self.func()
                if flags & 2:
                    self.func()
            o['props'].append((pn, pt))
        o['states'] = {}
        for _ in range(self.u16()):
            st = self.s()
            o['states'][st] = {self.s(): self.func() for _ in range(self.u16())}
        return o


def load(edition, script):
    import bsa
    b = bsa.extract(edition, f'scripts\\{script.lower()}.pex')
    if b is None:
        raise FileNotFoundError(script)
    return Pex(b)


def dump(p, pattern='.'):
    for o in p.objects:
        print(f'scriptname {o["name"]} extends {o["parent"]}')
        for pn, pt in o['props']:
            print(f'  property {pt} {pn}')
        for st, funcs in o['states'].items():
            for fn, f in funcs.items():
                if not re.search(pattern, fn, re.I):
                    continue
                print(f'  [{st or "-"}] {f["ret"]} {fn}({", ".join(f"{t} {n}" for n, t in f["params"])})')
                for i, (op, args) in enumerate(f['code']):
                    print(f'    {i:3} {op} {", ".join(str(a) for a in args)}')


if __name__ == '__main__':
    dump(load(sys.argv[1], sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else '.')
