"""Builds docs/data/collectibles.json from Skyrim SE's masters, tools/notes.json and the fitted map projections.

python build_data.py [edition] [output path]: verify_editions.py builds LE and VR copies to compare."""
import json, re, struct, sys
from collections import Counter
from pathlib import Path
import tes5
from places import Places, TABS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'data'
NOTES = json.loads((ROOT / 'tools' / 'notes.json').read_text(encoding='utf-8'))
MAPS = json.loads((ROOT / 'tools' / 'maps.json').read_text(encoding='utf-8'))

EDITION = sys.argv[1] if len(sys.argv) > 1 else 'se'
recs = tes5.load(EDITION)
by_edid = {}
for r in recs.values():
    if r.type not in ('REFR', 'ACHR', 'NAVM', 'LAND', 'INFO') and r.edid:
        by_edid.setdefault(r.edid, r)
places = Places(recs)
PLAYER = 0x14


def F(x):
    """Plugin key and local ID of a normalised form ID, as the page resolves it."""
    return [tes5.KEYS[x >> 24], x & 0xFFFFFF]


def E(edid):
    return by_edid[edid].fid


def dlc_of(fid):
    return {tes5.DAWNGUARD: 'dawnguard', tes5.DRAGONBORN: 'dragonborn', tes5.SAINTS: 'saints'}.get(fid >> 24, 'base')


# ---------- quest aliases ----------

def aliases(q):
    """Alias index -> dict(name, forced ref, unique actor, created object, created-in alias)."""
    out, cur = {}, None
    for k, v in q.subs():
        if k in ('ALST', 'ALLS'):
            cur = out.setdefault(tes5.u32(v), {})
        elif cur is None:
            continue
        elif k == 'ALID':
            cur['name'] = v.split(b'\0')[0].decode('latin1')
        elif k == 'ALFR':
            cur['forced'] = q.plugin.norm(tes5.u32(v))
        elif k == 'ALUA':
            cur['unique'] = q.plugin.norm(tes5.u32(v))
        elif k == 'ALCO':
            cur['create'] = q.plugin.norm(tes5.u32(v))
        elif k == 'ALCA':
            cur['createIn'] = struct.unpack_from('<h', v)[0]
    return out


def alias_ref(al):
    if 'forced' in al:
        return al['forced']
    if 'unique' in al:
        return places.placed.get(al['unique'], [None])[0]


created = {}
for q in recs.values():
    if q.type != 'QUST':
        continue
    als = aliases(q)
    for al in als.values():
        if 'create' in al:
            holder = alias_ref(als.get(al.get('createIn'), {}))
            created.setdefault(al['create'], []).append(dict(quest=q.fid, holder=holder, alias=al.get('name')))


def npc_name(npc):
    """An NPC's display name, following its templates: leveled giants and guards take theirs from one."""
    for _ in range(8):
        if npc.full:
            return npc.full
        tpl = recs.get(npc.ref('TPLT'))
        if tpl is None or tpl.type != 'NPC_':
            break
        npc = tpl
    return npc.edid


def outfit_holders(base):
    out = []
    for o in recs.values():
        if o.type == 'OTFT' and o.sub('INAM'):
            items = [o.plugin.norm(tes5.u32(o.sub('INAM')[i:i + 4])) for i in range(0, len(o.sub('INAM')), 4)]
            if base in items:
                for n in recs.values():
                    if n.type == 'NPC_' and n.ref('DOFT') == o.fid:
                        out += places.placed.get(n.fid, [])
    return out


def real_refs(base):
    """Placed refs of `base` outside developer and holding cells."""
    out = []
    for fid in places.placed.get(base, []):
        cell = recs[places.refs[fid][0]]
        if re.search(r'aaaMarkers|HoldingCell|Test|QA|Warehouse|E3demo|Prefab', cell.edid, re.I):
            continue
        out.append(fid)
    return out


def real_refs_of(fids):
    return [f for f in fids if not re.search(r'Test|QA|Warehouse|E3demo|Prefab', recs[places.refs[f][0]].edid, re.I)]


# ---------- quests ----------

def finishing_stages(q):
    """Stages whose log entry completes or fails the quest."""
    out, stage = set(), None
    for k, v in q.subs():
        if k == 'INDX':
            stage = struct.unpack_from('<H', v)[0]
        elif k == 'QSDT' and stage is not None and v[0] & 0x3:
            out.add(stage)
    return out


items = []


def add(kind, prefix, name, at, rule, **extra):
    it = dict(id='', kind=kind, dlc=extra.pop('dlc', None) or dlc_of(at if isinstance(at, int) else 0), name=name)
    if isinstance(at, int):
        it.update(places.locate(at))
    elif isinstance(at, str):
        tab, x, y = places.marker(at)
        it.update(area=at, map=dict(world=tab, x=round(x), y=round(y)), near=places.nearest(tab, x, y), viaDoor=False)
    it['rule'] = rule
    it.update(extra)
    it['_prefix'] = prefix
    items.append(it)
    return it


def lost_fail(it):
    if it.get('lostAfter'):
        it['fail'] = dict(quest=F(it.pop('lostAfter')), reason=f'{it["oneTime"]} can no longer be reached.')


# ---------- Dragon Priest Masks ----------

PRIEST_MASKS = ['Bronze', 'Corondrum', 'Ebony', 'Iron', 'Marble', 'Moonstone', 'Orichalum', 'Steel']
shrine = {}
for r in recs.values():
    if r.type == 'REFR' and recs.get(r.ref('NAME')) and recs[r.ref('NAME')].edid.startswith('DragonPriestMask') and recs[r.ref('NAME')].edid.endswith('01'):
        shrine[recs[r.ref('NAME')].edid[len('DragonPriestMask'):-2]] = r.fid
for m in PRIEST_MASKS + ['Wood', 'Ultra']:
    base = E(f'ArmorDragonPriestMask{m}Helmet')
    holders = outfit_holders(base) + [c['holder'] for c in created.get(base, []) if c['holder']]
    rule = [dict(held=[F(base)], exclude=[F(h) for h in holders])]
    rule += [dict(lost=F(h), item=[F(base)]) for h in holders]
    rule += [dict(ref=F(f), how='taken') for f in real_refs(base)]
    if m in shrine:
        rule.append(dict(ref=F(shrine[m]), how='shown' if m != 'Ultra' else 'taken'))
    at = (holders or real_refs(base) or [shrine.get(m)])[0]
    it = add('mask', 'DM', recs[base].full, at, rule)
    if holders:
        it['holder'] = npc_name(recs[recs[holders[0]].ref('NAME')])
    lost_fail(it)
for edid in ('DLC2ArmorAcolyteMaskFire', 'DLC2ArmorAcolyteMaskFrost', 'DLC2ArmorAcolyteMaskShock'):
    base = E(edid)
    holders = outfit_holders(base)
    it = add('mask', 'DM', recs[base].full, holders[0],
             [dict(held=[F(base)], exclude=[F(h) for h in holders])] + [dict(lost=F(h), item=[F(base)]) for h in holders])
    it['holder'] = npc_name(recs[recs[holders[0]].ref('NAME')])
miraak = [E(f'DLC2MKMiraakMask{n}{w}') for n in '123' for w in 'HL'] + [E('DLC2MiraakMaskNew')]
it = add('mask', 'DM', 'Miraak', 'Summit of Apocrypha' if any(m['name'] == 'Summit of Apocrypha' for m in places.markers) else 'Temple of Miraak',
         [dict(held=[F(x) for x in miraak], exclude=[F(h) for h in outfit_holders(E('DLC2MiraakMaskNew'))])], dlc='dragonborn')

# ---------- Stones of Barenziah ----------

for f in real_refs(E('TGCrownGemActivator')):
    add('stone', 'SB', 'Stone of Barenziah', f, [dict(ref=F(f), how='disabled')])

# ---------- Dragon Claws ----------

CLAWS = ['E3GoldenClaw', 'dunYngolBarrowCoralClaw', 'dunSkuldafnDiamondClaw', 'dunKorvanjundEbonyDragonClaw',
         'dunReachwaterRockEmeraldDragonClaw', 'dunForelhostGlassClaw', 'dunValthumeIronClaw',
         'dunFolgunthurIvoryDragonClaw', 'dunDeadMensRubyDragonClaw', 'FFI01Claw']
GOLDEN = [E('E3GoldenClaw'), E('MS13GoldenClaw')]
# The door a claw opens is in the dungeon it comes from: the location of last resort for claws created on random actors.
keyholes = {}
for r in recs.values():
    if r.type == 'REFR' and r.sub('VMAD') and r.fid in places.refs:
        for s_, p_ in tes5.vmad(r.sub('VMAD')):
            if 'keyhole' in s_.lower() and isinstance(p_.get('myMiscObject'), int):
                keyholes.setdefault(r.plugin.norm(p_['myMiscObject']), []).append(r.fid)
for edid in CLAWS:
    base = E(edid)
    bases = GOLDEN if base in GOLDEN else [base]
    holders = [c['holder'] for b in bases for c in created.get(b, []) if c['holder']]
    refs = [f for b in bases for f in real_refs(b)]
    rule = [dict(held=[F(b) for b in bases], exclude=[F(h) for h in holders])]
    rule += [dict(ref=F(f), how='taken' if not (recs[f].flags & 0x800) else 'shown') for f in refs]
    at = ([f for f in refs if not recs[f].flags & 0x800] or holders or real_refs_of(keyholes.get(base, [])))[0]
    it = add('claw', 'DC', recs[bases[-1]].full, at, rule)
    lost_fail(it)
halves = [E('DLC2SV01HalfClawLeft'), E('DLC2SV01HalfClawRight')]
sv01 = recs[E('DLC2SV01')]
hold = [c['holder'] for b in halves for c in created.get(b, []) if c['holder']]
add('claw', 'DC', 'Amethyst Claw', (hold or real_refs_of(keyholes[halves[0]]))[0],
    [dict(all=[dict(held=[F(b)], exclude=[F(h) for h in hold]) for b in halves]),
     dict(stage=F(sv01.fid), stages=sorted(finishing_stages(sv01)))],
    halves=[F(b) for b in halves], halvesExclude=[F(h) for h in hold])

# ---------- Black Books ----------

for n in range(1, 8):
    base = E(f'DLC2BlackBook{n:02d}')
    refs = real_refs(base)
    add('blackbook', 'BB', recs[base].full.replace('Black Book: ', ''), refs[0],
        [dict(held=[F(base)])] + [dict(ref=F(f), how='taken') for f in refs])

# ---------- Shouts ----------

PLAYER_SHOUTS = ['UnrelentingForceShout', 'FireBreathShout', 'FrostBreathShout', 'WhirlwindSprintShout',
                 'BecomeEtherealShout', 'ElementalFuryShout', 'Dismay', 'ClearSkiesShout', 'SlowTimeShout',
                 'DragonrendShout', 'CallDragonShout', 'CallofValorShout', 'AuraWhisperShout', 'MarkedforDeathShout',
                 'StormCallShout', 'KynesPeaceShout', 'ThrowVoiceShout', 'animalAllegianceShout', 'IceFormShout',
                 'DisarmShout', 'DLC1DrainVitalityShout', 'DLC1SoulTearShout', 'DLC1SummonDragonShout',
                 'DLC2BendWillShout', 'DLC2DragonAspectShout', 'DLC2CycloneShout', 'DLC2BattleFuryShout']
shout_of_word, shouts = {}, []
for edid in PLAYER_SHOUTS:
    s = by_edid[edid]
    words = [s.plugin.norm(tes5.u32(v)) for v in s.all('SNAM')]
    shouts.append(dict(id=edid, name=s.full, dlc=dlc_of(s.fid), words=[F(w) for w in words]))
    for w in words:
        shout_of_word[w] = s

# Word names are spelled for the in-game dragon font, where digits stand for long vowels.
DRAGON_FONT = {'1': 'aa', '2': 'ei', '3': 'ii', '4': 'ah', '5': 'uu', '6': 'ur', '7': 'ir', '8': 'oo', '9': 'ey'}


def dovahzul(name):
    s = ''.join(DRAGON_FONT.get(c, c) for c in name.lower())
    return s[:1].upper() + s[1:]


walls = []
for r in recs.values():
    if r.type != 'REFR':
        continue
    base = recs.get(r.ref('NAME'))
    sources = [(r.plugin, tes5.vmad(r.sub('VMAD')) if r.sub('VMAD') else [])]
    if base and base.sub('VMAD'):
        sources.append((base.plugin, tes5.vmad(base.sub('VMAD'))))
    props, script = {}, None
    for plugin, scripts in sources:
        for s_, p_ in scripts:
            if 'wordwall' in s_.lower() and 'trigger' in s_.lower():
                script = script or s_
                for k, v in p_.items():
                    props.setdefault(k.lower(), (v, plugin))
    if not script:
        continue
    word_ids = [plug.norm(v) for k, (v, plug) in sorted(props.items()) if re.fullmatch(r'myword0\d', k) and v]
    word_ids = [w for w in word_ids if w in shout_of_word]
    if not word_ids or r.fid not in places.refs:
        continue
    cell = recs[places.refs[r.fid][0]]
    if re.search(r'Warehouse|E3demo|Prefab|Test', cell.edid, re.I):
        continue
    shout = shout_of_word[word_ids[0]]
    wall = dict(ref=F(r.fid), script=script, shout=shout.edid, words=[F(w) for w in word_ids], dlc=dlc_of(r.fid))
    try:
        wall.update(places.locate(r.fid))
    except LookupError:
        continue
    if wall.get('lostAfter'):
        wall['lostAfter'] = F(wall['lostAfter'])
    walls.append(wall)

shout_by_id = {s['id']: s for s in shouts}
WALL_KEYS = ('ref', 'script', 'shout', 'words', 'dlc')
for wall in walls:
    s = shout_by_id[wall['shout']]
    it = dict(id='', kind='shout', dlc=wall['dlc'], name=s['name'], shout=s['id'], shoutName=s['name'], source='wall',
              **{k: (dict(v) if k == 'map' else v) for k, v in wall.items() if k not in WALL_KEYS and k != 'lostAfter'},
              rule=[dict(wall=wall['ref'], script=wall['script'])], _prefix='WP')
    if wall.get('lostAfter'):
        it['fail'] = dict(quest=wall['lostAfter'], reason=f'{it["oneTime"]} can no longer be reached.')
    items.append(it)

quest_words = NOTES['questWords']
for s in shouts:
    n_walls = sum(w['shout'] == s['id'] for w in walls)
    taught = [n for n in range(len(s['words'])) if f'{s["id"]}:{n + 1}' in quest_words]
    if n_walls + len(taught) != len(s['words']):
        raise SystemExit(f'{s["id"]}: {n_walls} walls and {len(taught)} quest words for {len(s["words"])} words')
    for n in taught:
        w = s['words'][n]
        word = recs[(tes5.KEYS.index(w[0]) << 24) | w[1]]
        note = quest_words[f'{s["id"]}:{n + 1}']
        it = dict(id='', kind='shout', dlc=s['dlc'], name=dovahzul(word.full), translation=word.plugin.text(word.sub('TNAM')),
                  shout=s['id'], shoutName=s['name'], wordIndex=n + 1, source='quest', rule=[dict(word=w)],
                  note=note['note'], _prefix='WP')
        if note.get('stage'):
            quest, stage = note['stage']
            it.update(name='Any one word', translation=None, rule=[dict(stage=F(E(quest)), stages=[stage])])
        if note.get('npc'):
            it.update(places.locate(places.placed[E(note['npc'])][0]))
        elif note.get('marker'):
            tab, x, y = places.marker(note['marker'])
            it.update(area=note['marker'], map=dict(world=tab, x=round(x), y=round(y)), near=places.nearest(tab, x, y), viaDoor=False)
        items.append(it)

# ---------- Paragons, Jiub's Opus, Kagrumez gems, insects ----------

for edid in ('PortalGemWhiteKey', 'PortalGemPurpleKey', 'PortalGemOrangeKey', 'PortalGemGreenKey', 'PortalGemBlueKey'):
    base = E(edid)
    holders = [c['holder'] for c in created.get(base, []) if c['holder']]
    it = add('paragon', 'PG', recs[base].full, holders[0], [dict(held=[F(base)], exclude=[F(h) for h in holders])])
    holder = recs[recs[holders[0]].ref('NAME')]
    if holder.type == 'NPC_':
        it['holder'] = npc_name(holder)

for n in range(1, 11):
    base = E(f'DLC1VQSaintPage{n:02d}')
    refs = real_refs(base)
    add('jiub', 'JO', f'Page {n}', refs[0], [dict(held=[F(base)])] + [dict(ref=F(f), how='taken') for f in refs])

gem = E('DLC2DweKagrumezControlGemInv01')
gem_holders = [c['holder'] for c in created.get(gem, []) if c['holder']]
merchant = [f for f in places.placed.get(E('DLC2SiltStriderMerchant'), [])]
gem_sources = [('ref', f) for f in real_refs(gem)] + [('created', h) for h in gem_holders] + [('merchant', f) for f in merchant]
for kind_, f in gem_sources:
    rule = [dict(ref=F(f), how='taken')] if kind_ == 'ref' else [dict(lost=F(f), item=[F(gem)])] if kind_ == 'merchant' else []
    it = add('kagrumez', 'KG', 'Kagrumez Resonance Gem', f, rule, pool=F(gem))
    if kind_ == 'merchant':
        it['note'] = 'Sold by the silt strider merchant.'
    if kind_ == 'created':
        it['note'] = 'Carried by the leader of the reavers inside Kagrumez.'

for edid in ('dunUniqueBeeInJar', 'dunUniqueButterflyInJar', 'dunUniqueDragonflyInJar', 'dunUniqueMothInJar', 'dunUniqueFireflyInJar'):
    base = E(edid)
    refs = real_refs(base)
    it = add('jar', 'IJ', recs[base].full, refs[0], [dict(held=[F(base)])] + [dict(ref=F(f), how='taken') for f in refs])
    if edid in ('dunUniqueButterflyInJar', 'dunUniqueMothInJar', 'dunUniqueFireflyInJar'):
        it['note'] = NOTES['respawns']
for edid in ('ccBGSSSE025_dunUniqueBlissBugInJar', 'ccBGSSSE025_dunUniquePurpleButterflyInJar', 'ccBGSSSE025_dunUniqueGreenButterflyInJar'):
    if edid in by_edid:
        base = E(edid)
        refs = real_refs(base)
        add('jar', 'IJ', recs[base].full, refs[0], [dict(held=[F(base)])] + [dict(ref=F(f), how='taken') for f in refs])

# ---------- Thieves Guild trophies ----------

larceny = recs[E('TGLarceny')]
pickups = {recs[al['forced']].ref('NAME'): al['forced'] for al in aliases(larceny).values() if 'forced' in al}
mercer = places.placed.get(E('MercerFrey'), [])
for f in range(0xE8EF8, 0xE8EFF):
    base = recs[f].ref('NAME')
    it = add('trophy', 'TG', recs[base].full, pickups[base], [dict(ref=F(f), how='shown')],
             source='The Litany of Larceny',
             pickup=[dict(ref=F(pickups[base]), how='taken'), dict(held=[F(base)], exclude=[F(m) for m in mercer])])
    it['note'] = NOTES['trophies'].get(it['name'])
for f, jobs in ((0xE8EFF, 5), (0xE8F00, 15), (0xE8F05, 25), (0xE8F03, 35), (0xE8F02, 45), (0xE8F01, 55)):
    add('trophy', 'TG', recs[recs[f].ref('NAME')].full, f, [dict(ref=F(f), how='shown')],
        source='Radiant jobs', note=f'Appears on the shelf after {jobs} jobs for Vex and Delvin.')
add('trophy', 'TG', "Barenziah's Crown", 0x6D625, [dict(ref=F(0x6D625), how='shown')],
    source='No Stone Unturned', note='Appears on its stand once you bring Vex all 24 Stones of Barenziah.')

# ---------- Daedric artifacts ----------

for a in NOTES['artifacts']:
    q = by_edid[a['quest']]
    bases = [E(b) for b in a['items']]
    rule = [dict(held=[F(b) for b in bases])]
    if a.get('stages'):
        rule.append(dict(stage=F(q.fid), stages=a['stages']))
    at = a.get('marker') or next(f for f, (c, w, _) in places.refs.items() if recs[c].edid == a['cell'] and w is None)
    it = add('artifact', 'DA', a['name'], at, rule, source=q.full, prince=a['prince'], note=a.get('note'))
    if a.get('stages') and not a.get('neverLost'):
        it['fail'] = dict(quest=F(q.fid), stages=sorted(finishing_stages(q) - set(a['stages'])),
                          reason=a.get('lost', f'{q.full} ended without it.'))

# ---------- ids, map projection, output ----------

for kind, n in Counter(i['kind'] for i in items).items():
    group = [i for i in items if i['kind'] == kind]
    width = len(str(len(group)))
    for k, it in enumerate(group, 1):
        it['id'] = f'{it.pop("_prefix")}{k:0{width}d}'


def project(m):
    p = MAPS[m['world']]['proj']
    m['u'] = round((m['x'] - p['x0']) / (p['x1'] - p['x0']), 5)
    m['v'] = round((p['y1'] - m['y']) / (p['y1'] - p['y0']), 5)


for it in items + walls:
    if it.get('map'):
        project(it['map'])

counters = {k: F(E(v)) for k, v in dict(stone='TGCrownGemsFound', blackbook='DLC2BlackBookCount', kagrumez='DLC2KagrumezGemPlacedCount').items()}
worlds = {k: {kk: vv for kk, vv in v.items() if kk != 'proj'} for k, v in MAPS.items()}
OUT.mkdir(parents=True, exist_ok=True)
(Path(sys.argv[2]) if len(sys.argv) > 2 else OUT / 'collectibles.json').write_text(json.dumps(dict(
    worlds=worlds, counters=counters, achievements=F(E('AchievementsQuest')), shouts=shouts, walls=walls, items=items),
    ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

print(Counter((i['kind'], i['dlc']) for i in items))
print('walls', len(walls), Counter(w['shout'] for w in walls))
print('one-time:', [(i['id'], i['name']) for i in items if i.get('oneTime')])
