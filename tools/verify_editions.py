"""Fails unless LE and VR place and detect every collectible as SE does (collectibles.json built from each)."""
import json, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ('id', 'kind', 'dlc', 'rule', 'fail', 'pool')


def build(edition, out):
    subprocess.run([sys.executable, str(HERE / 'build_data.py'), edition, str(out)], check=True, capture_output=True)
    return json.loads(out.read_text(encoding='utf-8'))


def close(a, b):
    return a.get('world') == b.get('world') and abs(a['x'] - b['x']) < 70 and abs(a['y'] - b['y']) < 70


with tempfile.TemporaryDirectory() as tmp:
    se = build('se', Path(tmp) / 'se.json')
    bad = 0
    for ed in ('le', 'vr'):
        other = build(ed, Path(tmp) / f'{ed}.json')
        a = {i['id']: i for i in se['items'] if i['dlc'] != 'saints'}
        b = {i['id']: i for i in other['items']}
        if a.keys() != b.keys():
            print(f'{ed}: different items: {sorted(a.keys() ^ b.keys())}')
            bad += 1
        for k in a.keys() & b.keys():
            diffs = [f for f in KEYS if a[k].get(f) != b[k].get(f)]
            if a[k].get('map') and b[k].get('map') and not close(a[k]['map'], b[k]['map']):
                diffs.append('map')
            if diffs:
                print(f'{ed}: {k} {a[k]["name"]} differs in {diffs}')
                bad += 1
        wa = {tuple(w['ref']): w for w in se['walls']}
        wb = {tuple(w['ref']): w for w in other['walls']}
        if wa.keys() != wb.keys():
            print(f'{ed}: different walls: {sorted(wa.keys() ^ wb.keys())}')
            bad += 1
        print(f'{ed}: {len(b)} items, {len(wb)} walls checked against SE')
    sys.exit(1 if bad else 0)
