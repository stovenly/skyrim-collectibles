"""Renders game meshes to transparent PNG icons: orthographic, z-buffered, textured, with simple diffuse light."""
import io
import numpy as np
from PIL import Image
import bsa, nif

# The renderer reads LE NIF 20.2.0.7 tri-shapes; SE meshes use a different layout.
EDITION = "le"


def texture(path):
    if not path:
        return None
    p = path.lower().replace('/', '\\')
    if not p.startswith('textures\\'):
        p = 'textures\\' + p
    b = bsa.extract(EDITION, p)
    return np.asarray(Image.open(io.BytesIO(b)).convert('RGBA'), dtype=np.float32) / 255 if b else None


def view_basis(points, view):
    """Right, up and toward-viewer axes. `view` is 'auto' (look along the flattest axis) or an explicit forward vector."""
    if view == 'auto':
        c = points - points.mean(0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        fwd, right = vt[2], vt[0]
        up = np.cross(fwd, right)
        return right, up, fwd
    fwd = np.asarray(view, dtype=float)
    fwd /= np.linalg.norm(fwd)
    up0 = np.array([0, 0, 1.0]) if abs(fwd[2]) < .9 else np.array([0, 1.0, 0])
    right = np.cross(up0, fwd)
    right /= np.linalg.norm(right)
    return right, np.cross(fwd, right), fwd


def render(mesh_path, size=512, view='auto', light=(0.4, 0.5, 0.75), shapes=None, flip=False, spin=0.0, ambient=.45, emissive=None, effect_gain=1.0):
    parts = nif.meshes(bsa.extract(EDITION, mesh_path))
    if shapes is not None:
        parts = [parts[i] for i in shapes]
    allv = np.array([v for p in parts for v in p['verts']])
    right, up, fwd = view_basis(allv, view)
    if flip:
        fwd, right = -fwd, -right
    a = np.radians(spin)
    right, up = np.cos(a) * right + np.sin(a) * up, -np.sin(a) * right + np.cos(a) * up
    proj = np.stack([allv @ right, allv @ up], 1)
    lo, hi = proj.min(0), proj.max(0)
    scale = (size * .94) / (hi - lo).max()
    off = (size - (hi - lo) * scale) / 2
    colour = np.zeros((size, size, 4), np.float32)
    zbuf = np.full((size, size), -np.inf, np.float32)
    L = np.asarray(light, float)
    L /= np.linalg.norm(L)
    for p in parts:
        tex = texture(p['shader'].get('texture'))
        palette = texture(p['shader'].get('greyscale'))
        glow = texture(p['shader'].get('glow')) if emissive else None
        glow_colour = np.asarray(p['shader'].get('emissive', (0, 0, 0)), np.float32) * p['shader'].get('emissive_mult', 1) * (emissive or 0)
        V = np.array(p['verts'])
        UV = np.array(p['uvs']) if p['uvs'] else np.zeros((len(V), 2))
        sx = (V @ right - lo[0]) * scale + off[0]
        sy = size - ((V @ up - lo[1]) * scale + off[1])
        sz = V @ fwd
        for t in p['tris']:
            i0, i1, i2 = t
            x = np.array([sx[i0], sx[i1], sx[i2]])
            y = np.array([sy[i0], sy[i1], sy[i2]])
            n = np.cross(V[i1] - V[i0], V[i2] - V[i0])
            nn = np.linalg.norm(n)
            if nn == 0:
                continue
            n /= nn
            facing = n @ fwd
            shade = ambient + (1 - ambient) * abs(n @ L)
            x0, x1 = int(max(0, np.floor(x.min()))), int(min(size - 1, np.ceil(x.max())))
            y0, y1 = int(max(0, np.floor(y.min()))), int(min(size - 1, np.ceil(y.max())))
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
            d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
            if abs(d) < 1e-9:
                continue
            w0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
            w1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            z = w0 * sz[i0] + w1 * sz[i1] + w2 * sz[i2]
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            win = inside & (z > sub)
            if not win.any():
                continue
            if tex is not None:
                u = w0 * UV[i0, 0] + w1 * UV[i1, 0] + w2 * UV[i2, 0]
                v = w0 * UV[i0, 1] + w1 * UV[i1, 1] + w2 * UV[i2, 1]
                th, tw = tex.shape[:2]
                tx = np.mod(np.floor(u * tw).astype(int), tw)
                ty = np.mod(np.floor(v * th).astype(int), th)
                c = tex[ty, tx].copy()
                if glow is not None:
                    gh, gw = glow.shape[:2]
                    g = glow[np.mod(np.floor(v * gh).astype(int), gh), np.mod(np.floor(u * gw).astype(int), gw)]
                    c[..., :3] = c[..., :3] * shade + g[..., :3] * glow_colour
                else:
                    c[..., :3] *= shade
            else:
                c = np.ones(gx.shape + (4,), np.float32) * np.array([.8, .8, .8, 1]) * np.array([shade, shade, shade, 1])
            region = colour[y0:y1 + 1, x0:x1 + 1]
            if p['shader'].get('kind') == 'effect':
                # Additive glow: texture brightness looked up in the greyscale palette, never writing depth.
                lum = c[..., :3].mean(-1) / max(shade, 1e-3) * c[..., 3]
                if palette is not None:
                    idx = np.clip((lum * (palette.shape[1] - 1)).astype(int), 0, palette.shape[1] - 1)
                    rgb = palette[palette.shape[0] // 2, idx, :3]
                else:
                    rgb = np.asarray(p['shader'].get('emissive', (1, 1, 1)), np.float32) * lum[..., None]
                a = lum * p['shader'].get('alpha', 1) * effect_gain
                add = np.zeros_like(c)
                add[..., :3] = rgb * a[..., None]
                add[..., 3] = a
                inside_only = inside
                region[inside_only] += add[inside_only]
                continue
            c[..., 3] = 1
            region[win] = c[win]
            sub[win] = z[win]
    img = Image.fromarray((np.clip(colour, 0, 1) * 255).astype(np.uint8), 'RGBA')
    return img
