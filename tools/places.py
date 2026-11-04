"""Where a reference is: which map tab, at what game coordinates, near which map marker, and how to describe it."""
import math, struct
from collections import deque
import tes5

MAP_MARKER = 0x10
UNITS_PER_M = 70.0
USE_MAP_DATA = 0x4
DIRS = ['E', 'NE', 'N', 'NW', 'W', 'SW', 'S', 'SE']

# Map tab of each worldspace drawn in its own coordinates; contract with fit_maps.py and the page's world keys.
TABS = {0x0000003C: 'skyrim', 0x02000BB5: 'vale', 0x02001408: 'soulcairn', 0x04000800: 'solstheim'}
# Realms with no load door out and no place on any map: pinned at the named marker on a tab, and flagged.
REALMS = {
    'DLC2ApocryphaWorld': dict(marker='Temple of Miraak', name='Apocrypha',
                               note=None),
    'Sovngarde': dict(marker='Skuldafn Temple', name='Sovngarde',
                      note='Only obtainable during the main quest.'),
}
# Interiors entered by script rather than a load door, pinned at a map marker.
MARKER_PINS = {'LabyrinthianPriestSanctuary': 'Labyrinthian'}
# Worldspaces whose ONAM claims Tamriel's map though they are only reached through doors elsewhere.
DOOR_ONLY = {'DLC01Boneyard'}
# Places a player can only visit once; anything left there is lost when the gating quest completes.
ONE_TIME = {
    'SkuldafnWorld': dict(name='Skuldafn', quest=0x00046EF0,
                          note="Only obtainable during the main quest The World-Eater's Eyrie."),
}


class Places:
    def __init__(self, recs):
        self.recs = recs
        self.refs, self.doors, self.cells_by_world, self.markers = {}, {}, {}, []
        self.world_edid = {r.fid: r.edid for r in recs.values() if r.type == 'WRLD'}
        for r in recs.values():
            if r.type not in ('REFR', 'ACHR') or not r.sub('DATA'):
                continue
            cell, wrld = r.cell_world()
            pos = struct.unpack('<3f', r.sub('DATA')[:12])
            self.refs[r.fid] = (cell, wrld, pos)
            if wrld is not None:
                self.cells_by_world.setdefault(wrld, set()).add(cell)
            if r.sub('XTEL'):
                self.doors.setdefault(cell, []).append(r.ref('XTEL'))
            if r.ref('NAME') == MAP_MARKER and r.full and wrld is not None:
                self.markers.append(dict(name=r.full, wrld=wrld, x=pos[0], y=pos[1]))
        self.placed = {}
        for fid, r in ((f, recs[f]) for f in self.refs):
            self.placed.setdefault(r.ref('NAME'), []).append(fid)
        for m in self.markers:
            m['tab'], m['tx'], m['ty'] = self.to_tab(m['wrld'], m['x'], m['y']) or (None, 0, 0)

    def to_tab(self, wrld, x, y):
        """(tab, x, y) for a point in a worldspace the maps can show directly, else None."""
        if wrld in TABS:
            return TABS[wrld], x, y
        w = self.recs.get(wrld)
        if w is None or w.edid in DOOR_ONLY:
            return None
        parent = w.ref('WNAM')
        pnam, onam = w.sub('PNAM'), w.sub('ONAM')
        if parent in TABS and pnam and pnam[0] & USE_MAP_DATA and onam:
            scale, ox, oy, _ = struct.unpack('<4f', onam)
            if abs(scale - 1) < 1e-6 or 0 < scale < 0.01:
                return TABS[parent], x * scale + ox, y * scale + oy

    def exit_to_tab(self, seeds, home):
        """Walk load doors outward until one opens onto a mapped worldspace."""
        seen, q = set(seeds), deque(seeds)
        while q:
            c = q.popleft()
            for dest in self.doors.get(c, []):
                if dest not in self.refs:
                    continue
                dcell, dwrld, dpos = self.refs[dest]
                if dwrld is not None and dwrld != home:
                    hit = self.to_tab(dwrld, dpos[0], dpos[1])
                    if hit:
                        return hit
                nxt = self.cells_by_world.get(dwrld, ()) if dwrld is not None and dwrld != home else (dcell,)
                for n in nxt:
                    if n not in seen:
                        seen.add(n)
                        q.append(n)

    def marker(self, name):
        m = next((m for m in self.markers if m['name'] == name and m['tab']), None)
        assert m, f'no map marker named {name!r}'
        return m['tab'], m['tx'], m['ty']

    def nearest(self, tab, x, y):
        cands = [m for m in self.markers if m['tab'] == tab]
        if not cands:
            return None
        m = min(cands, key=lambda m: math.hypot(x - m['tx'], y - m['ty']))
        d = math.hypot(x - m['tx'], y - m['ty'])
        ang = math.degrees(math.atan2(y - m['ty'], x - m['tx'])) % 360
        return dict(name=m['name'], metres=round(d / UNITS_PER_M), dir=DIRS[int((ang + 22.5) // 45) % 8])

    def locate(self, fid):
        """Location fields for the placed reference `fid`: area, interior, map, near, viaDoor, realm/oneTime notes."""
        cell, wrld, pos = self.refs[fid]
        c = self.recs[cell]
        w = self.recs.get(wrld) if wrld is not None else None
        out = dict(interior=wrld is None)
        if wrld is None:
            out['area'] = c.full or c.edid
            out['cell'] = c.edid
        elif wrld not in TABS:
            out['area'] = (w.full or w.edid) if not c.full else c.full
        elif c.full:
            out['area'] = c.full
        wedid = w.edid if w else None
        if wedid in REALMS:
            realm = REALMS[wedid]
            tab, x, y = self.marker(realm['marker'])
            out.update(realm=realm['name'], missable=realm['note'], area=out.get('area') or realm['name'])
            out['map'] = dict(world=tab, x=round(x), y=round(y), realm=realm['name'])
            return out
        once = ONE_TIME.get(wedid) or self._one_time_interior(cell)
        if once:
            out.update(oneTime=once['name'], missable=once['note'], lostAfter=once['quest'])
        direct = self.to_tab(wrld, pos[0], pos[1]) if wrld is not None else None
        if direct:
            tab, x, y = direct
            via = False
        elif c.edid in MARKER_PINS:
            tab, x, y = self.marker(MARKER_PINS[c.edid])
            via = True
        else:
            seeds = list(self.cells_by_world.get(wrld, ())) if wrld is not None else [cell]
            hit = self.exit_to_tab(seeds, wrld)
            if not hit:
                raise LookupError(f'no way out to a map from {c.edid or wedid}')
            tab, x, y = hit
            via = True
        out['map'] = dict(world=tab, x=round(x), y=round(y))
        out['near'] = self.nearest(tab, x, y)
        out['viaDoor'] = via
        return out

    def _one_time_interior(self, cell):
        """Interiors whose only way in is through a one-time worldspace."""
        for dest in self.doors.get(cell, []):
            if dest in self.refs:
                dwrld = self.refs[dest][1]
                if dwrld is not None and self.world_edid.get(dwrld) in ONE_TIME:
                    return ONE_TIME[self.world_edid[dwrld]]
