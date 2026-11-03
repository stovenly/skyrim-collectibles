"""Mirrors UESP's Skyrim map tiles into docs/map/<tab> as WebP, and flattens one zoom per tab into docs/data/<tab>.webp."""
import io, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = 'https://maps.uesp.net/srmap/{world}/leaflet/day/zoom{z}/{world}-{x}-{y}.jpg'
UA = 'skyrim-collectibles/1.0 (one-off mirror of the UESP Skyrim maps for stovenly.github.io/skyrim-collectibles)'
# Map tab -> UESP world name and the zooms worth keeping; zoom z is a 2**z grid of 256px tiles.
WORLDS = {'skyrim': ('skyrim', range(2, 6)), 'solstheim': ('solstheim', range(2, 6)),
          'soulcairn': ('soulcairn', range(2, 6)), 'vale': ('forgottenvale', range(2, 6))}
FLAT = 3


def fetch(tab, world, z, x, y):
    dest = ROOT / 'docs' / 'map' / tab / str(z) / str(x) / f'{y}.webp'
    if dest.exists():
        return dest.stat().st_size
    req = urllib.request.Request(SRC.format(world=world, z=z, x=x, y=y), headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        return 0 if e.code == 404 else -1
    except Exception as e:
        print(f'  {tab} {z}/{x}/{y}: {e}', file=sys.stderr)
        return -1
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, format='WEBP', quality=84, method=6)
    return dest.stat().st_size


for tab, (world, zooms) in WORLDS.items():
    for z in zooms:
        n = 2 ** z
        jobs = [(tab, world, z, x, y) for x in range(n) for y in range(n)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            sizes = list(pool.map(lambda a: fetch(*a), jobs))
        got = [s for s in sizes if s > 0]
        print(f'{tab} zoom {z}: {len(got)} of {n * n} tiles, {sum(got) / 1048576:.1f} MB'
              f'{", " + str(sizes.count(-1)) + " failed" if -1 in sizes else ""}', flush=True)
    out = ROOT / 'docs' / 'map' / tab / str(FLAT)
    flat = Image.new('RGB', (256 * 2 ** FLAT,) * 2)
    for p in out.rglob('*.webp'):
        flat.paste(Image.open(p), (int(p.parent.name) * 256, int(p.stem) * 256))
    dest = ROOT / 'docs' / 'data' / f'{tab}.webp'
    flat.save(dest, quality=90, method=6)
    print(f'{dest.name}: {dest.stat().st_size / 1048576:.1f} MB')
