"""Fits each map tab's projection by registering a land mask built from the worldspace's LAND records against the
flattened UESP tile image, then writes tools/maps.json."""
import json, struct, sys
from pathlib import Path
import numpy as np
from PIL import Image
import tes5
from places import TABS

ROOT = Path(__file__).resolve().parent.parent
CELL = 4096.0
SUB = 2  # samples per cell side
TILES = dict(size=256, min=2, max=5)
# Tabs whose UESP render only covers existing cells, against a black void.
VOID = {'soulcairn', 'vale'}

recs = tes5.load('se')
cells = {}
for r in recs.values():
    if r.type == 'CELL':
        _, wrld = r.cell_world()
        xclc = r.sub('XCLC')
        if wrld in TABS and xclc:
            x, y = struct.unpack_from('<2i', xclc)
            xclw = r.sub('XCLW')
            cells[r.fid] = (wrld, x, y, struct.unpack('<f', xclw)[0] if xclw and len(xclw) >= 4 else None)
heights = {}
for r in recs.values():
    if r.type == 'LAND':
        cell, _ = r.cell_world()
        v = r.sub('VHGT')
        if cell in cells and v:
            base = struct.unpack_from('<f', v)[0] * 8
            d = np.frombuffer(v, dtype=np.int8, offset=4, count=33 * 33).reshape(33, 33).astype(np.float32) * 8
            col0 = base + np.cumsum(d[:, 0])
            grid = col0[:, None] + np.cumsum(np.concatenate([np.zeros((33, 1)), d[:, 1:]], axis=1), axis=1)
            heights[cell] = grid


def game_mask(wrld, tab):
    w = recs[wrld]
    dnam = w.sub('DNAM')
    sea = struct.unpack_from('<2f', dnam)[1] if dnam else 0
    pts, vals = [], []
    for cell, (cw, x, y, water) in cells.items():
        if cw != wrld:
            continue
        g = heights.get(cell)
        lvl = sea if water is None or water > 1e30 or water < -1e6 else water
        for i in range(SUB):
            for j in range(SUB):
                gx, gy = (x + (j + .5) / SUB) * CELL, (y + (i + .5) / SUB) * CELL
                if tab in VOID:
                    land = g is not None
                else:
                    h = g[int((i + .5) / SUB * 32), int((j + .5) / SUB * 32)] if g is not None else -1e9
                    land = h > lvl
                pts.append((gx, gy))
                vals.append(land)
    return np.array(pts), np.array(vals)


def image_mask(path, modes=1):
    """True where the render shows land: far from its `modes` most common colours (background, then open water)."""
    im = np.asarray(Image.open(path).convert('RGB')).astype(np.int32)
    q = (im // 16).reshape(-1, 3)
    keys, counts = np.unique(q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2], return_counts=True)
    land = np.ones(im.shape[:2], bool)
    for mode in keys[np.argsort(-counts)[:modes]]:
        rgb = np.array([mode // 256, (mode // 16) % 16, mode % 16]) * 16 + 8
        land &= np.abs(im - rgb).sum(axis=2) > 60
    return land


def score(mask, pts, vals, sx, sy, ox, oy):
    px = ((pts[:, 0] - ox) / sx).astype(int)
    py = ((oy - pts[:, 1]) / sy).astype(int)
    h, w = mask.shape
    ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    got = np.zeros(len(vals), bool)
    got[ok] = mask[py[ok], px[ok]]
    return (got == vals).mean()


def refine(mask, pts, vals, start, steps):
    """Coordinate descent over (sx, sy, ox, oy); UESP's renders are not square in game units."""
    best = (score(mask, pts, vals, *start), *start)
    span = start[0] * mask.shape[1]
    for step in steps:
        improved = True
        while improved:
            improved = False
            for k in range(4):
                for d in (-1, 1):
                    c = list(best[1:])
                    c[k] = c[k] * (1 + d * step) if k < 2 else c[k] + d * step * span
                    sc = score(mask, pts, vals, *c)
                    if sc > best[0] + 1e-6:
                        best, improved = (sc, *c), True
    return best


# Skyrim's render starts exactly at Tamriel's NAM0/NAM9 corner; the others are found by search.
CORNER = {'skyrim'}
MODES = {'skyrim': 1, 'solstheim': 2, 'vale': 1, 'soulcairn': 1}
# Cells UESP actually rendered (x0, x1, y0, y1): Solstheim's worldspace also holds mainland LOD terrain.
REGION = {'solstheim': (-6, 30, -6, 34)}
# (units/px at zoom 3, corner cell x, corner cell y) set by hand from control points where masks mislead: the Soul
# Cairn's LAND does not match its render, so its mausoleum platforms were matched to the plazas drawn on it.
FIXED = {'soulcairn': (64.0, -11, 13)}
GRID = 256


def iou(mask_small, land, s, ox, oy, scale):
    px = ((land[:, 0] - CELL / SUB / 2 - ox) / s / scale).astype(int)
    py = ((oy - land[:, 1] - CELL / SUB / 2) / s / scale).astype(int)
    g = np.zeros((GRID, GRID), bool)
    block = max(1, int(np.ceil(CELL / SUB / s / scale)))
    for ddx in range(block):
        for ddy in range(block):
            qx, qy = px + ddx, py + ddy
            ok = (qx >= 0) & (qx < GRID) & (qy >= 0) & (qy < GRID)
            g[qy[ok], qx[ok]] = True
    return (g & mask_small).sum() / max(1, (g | mask_small).sum())


def fit(tab):
    """UESP rendered one cell per tile at some zoom, so the scale is a power of two and offsets fall on cell edges."""
    wrld = next(k for k, v in TABS.items() if v == tab)
    w = recs[wrld]
    mask = image_mask(ROOT / 'docs' / 'data' / f'{tab}.webp', MODES[tab])
    size = mask.shape[1]
    if tab in FIXED:
        s, cx, cy = FIXED[tab]
        x0, y1 = cx * CELL, cy * CELL
    elif tab in CORNER:
        x0 = struct.unpack_from('<f', w.sub('NAM0'))[0]
        y1 = struct.unpack_from('<f', w.sub('NAM9'), 4)[0]
        s = 256.0
    else:
        pts, vals = game_mask(wrld, tab)
        land = pts[vals]
        if tab in REGION:
            rx0, rx1, ry0, ry1 = REGION[tab]
            land = land[(land[:, 0] >= rx0 * CELL) & (land[:, 0] < rx1 * CELL) & (land[:, 1] >= ry0 * CELL) & (land[:, 1] < ry1 * CELL)]
        scale = size // GRID
        small = mask.reshape(GRID, scale, GRID, scale).mean(axis=(1, 3)) > .5
        ys, xs = np.nonzero(small)
        best = (0,)
        for s_ in [CELL / 2 ** k for k in range(3, 9)]:
            # Line the land's bounding box up with the render's, then search whole cells around it.
            bx = round((land[:, 0].min() - xs.min() * scale * s_) / CELL)
            by = round((land[:, 1].max() + ys.min() * scale * s_) / CELL)
            for dx in range(-16, 17):
                for dy in range(-16, 17):
                    c = (s_, (bx + dx) * CELL, (by + dy) * CELL)
                    sc = iou(small, land, *c, scale)
                    if sc > best[0]:
                        best = (sc, *c)
        sc, s, x0, y1 = best
        print(f'{tab}: IoU {sc:.3f}', end=', ')
    print(f'{tab}: {s:.0f} units/px at zoom 3, corner at cell {x0 / CELL:.0f}, {y1 / CELL:.0f}')
    # What the page shows: the render's content, not the empty square UESP pads it into.
    ys, xs = np.nonzero(image_mask(ROOT / 'docs' / 'data' / f'{tab}.webp', 1))
    pad = 24
    crop = [round(max(0, xs.min() - pad) / size, 4), round(max(0, ys.min() - pad) / size, 4),
            round(min(size, xs.max() + pad) / size, 4), round(min(size, ys.max() + pad) / size, 4)]
    return dict(name=w.full, image=f'data/{tab}.webp', width=size, height=size, crop=crop,
                tiles=dict(path=f'map/{tab}', **TILES),
                proj=dict(x0=x0, x1=x0 + s * size, y0=y1 - s * size, y1=y1))


out = {tab: fit(tab) for tab in (sys.argv[1:] or ['skyrim', 'vale', 'solstheim', 'soulcairn'])}
path = ROOT / 'tools' / 'maps.json'
old = json.loads(path.read_text()) if path.exists() else {}
old.update(out)
path.write_text(json.dumps(old, indent=1))
