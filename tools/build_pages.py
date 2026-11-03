"""Builds a tracker page per collectible, and the sitemap, by retargeting docs/index.html."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'
SITE = 'https://stovenly.github.io/skyrim-collectibles/'

# Keys are the page's kind keys; slugs are the links docs/index.html already uses.
PAGES = {
    'mask': dict(
        slug='dragon-priest-masks', name='Dragon Priest Masks', count='14',
        lead='Find the Dragon Priest Masks you are missing',
        what='<p>Eight dragon priests guard their masks in barrows across Skyrim, and a ninth mask of plain wood waits '
             'in Labyrinthian. Set all eight on the shrine in Bromjunaar Sanctuary and the golden Konahrik is yours. '
             'Dragonborn adds four more on Solstheim: Ahzidal, Dukaan, Zahkriisos and Miraak himself.</p>',
        why='<p>Nahkriin and his mask are in Skuldafn, which you can only visit once, during the main quest. Leave '
            'without it and it is gone for good; the tracker marks it lost.</p>',
        extra='<p>A mask counts as collected once it has left its priest, wherever you have put it since: in your '
              'pack, on a mannequin, in a chest at home, or sold.</p>'),
    'stone': dict(
        slug='stones-of-barenziah', name='Stones of Barenziah', count='24',
        lead='Find the Stones of Barenziah you are missing',
        what='<p>The 24 Stones of Barenziah are scattered through palaces, tombs and bandit caves. Bring them all to '
             'Vex in the Ragged Flagon during No Stone Unturned and Barenziah\'s Crown goes back on its stand.</p>',
        why='<p>The quest only starts once you have found the first stone and joined the Thieves Guild, and the game '
            'counts them without ever telling you where the rest are.</p>',
        extra='<p>The tracker checks itself against the game\'s own stone counter and warns you if they disagree.</p>'),
    'artifact': dict(
        slug='daedric-artifacts', name='Daedric Artifacts', count='16',
        lead='Find the Daedric Artifacts you are missing',
        what='<p>Fifteen Daedric Princes hand out artifacts in Skyrim, and Hircine has two to give. The page lists '
             'all of them, which quest each comes from, and whether a choice you made has cost you one.</p>',
        why='<p>Oblivion Walker is earned by the game\'s own count of artifacts handed over, not by what you are '
            'holding. The tracker reads that count straight from your save and explains when it differs: Hircine '
            'can count twice, and on the 2011 edition with Dawnguard the Masque of Clavicus Vile never counts at '
            'all.</p>',
        extra='<p>Artifacts lost to a choice &mdash; the Rueful Axe over the Masque, sparing Silus, refusing Namira, '
              'letting Erandur destroy the Skull &mdash; are marked lost.</p>'),
    'claw': dict(
        slug='dragon-claws', name='Dragon Claws', count='11',
        lead='Find the Dragon Claws you are missing',
        what='<p>Ten Dragon Claws open the great doors of Nordic ruins, from the Golden Claw of Bleak Falls Barrow to '
             'the Diamond Claw of Skuldafn. Dragonborn adds the Amethyst Claw, found in two halves in Lost Legacy.</p>',
        why='<p>The Diamond Claw is in Skuldafn, which closes behind you during the main quest.</p>',
        extra=''),
    'blackbook': dict(
        slug='black-books', name='Black Books', count='7',
        lead='Find the Black Books you are missing',
        what='<p>Seven Black Books lie hidden on Solstheim. Each one opens a realm of Apocrypha and, at its end, '
             'one of Hermaeus Mora\'s secrets.</p>',
        why='<p>They are spread across Dwemer ruins, barrows and a Telvanni tower, and nothing in the game lists '
            'which ones you have read.</p>',
        extra=''),
    'shout': dict(
        slug='words-of-power', name='Words of Power', count='81',
        lead='Find the Words of Power you are missing',
        what='<p>Skyrim has 60 Words of Power across 20 shouts, Dawnguard adds 9 and Dragonborn 12. Most are carved '
             'on word walls; the rest are taught during quests, by the Greybeards, Paarthurnax, Durnehviir or '
             'Hermaeus Mora.</p>',
        why='<p>Every word wall is listed with its own location, and every word taught during a quest with the place '
            'it is taught. A wall teaches the next word of its shout that you do not know. Your save does not always '
            'record which walls you have used, so where it cannot say, the tracker tells you how many of the shout\'s '
            'words you have learned from walls.</p>',
        extra=''),
    'paragon': dict(
        slug='paragons', name='Paragons', count='5',
        lead='Find the Paragons you are missing',
        what='<p>Five Paragons open the portals of the Forgotten Vale in Dawnguard. Most are guarded by Falmer and '
             'frost giants in the Vale and Darkfall Cave.</p>',
        why='<p>Each one sits on a different creature or chest, and once one is in a socket it no longer shows in '
            'your inventory.</p>',
        extra=''),
    'jiub': dict(
        slug='jiubs-opus', name="Jiub's Opus", count='10',
        lead="Find the pages of Jiub's Opus you are missing",
        what="<p>Jiub has lost the ten pages of his opus across the Soul Cairn. Return them to him for Impatience "
             "of a Saint and a reward from the old saint himself.</p>",
        why='<p>The Soul Cairn is vast and featureless, and you will not see Jiub again once you leave it with '
            'pages still missing.</p>',
        extra=''),
    'kagrumez': dict(
        slug='kagrumez-resonance-gems', name='Kagrumez Resonance Gems', count='5',
        lead='Find the Kagrumez Resonance Gems you are missing',
        what='<p>The Dwemer arena of Kagrumez on Solstheim needs Resonance Gems to open its three doors. Five can be '
             'found: in Fahlbtharz, in Nchardak, two on the reaver leader inside '
             'Kagrumez, and one sold by the silt strider merchant.</p>',
        why='<p>All five look the same in your pack, so the tracker counts what you hold and what you have set in '
            'the pedestal.</p>',
        extra=''),
    'jar': dict(
        slug='insects-in-jars', name='Insects in Jars', count='8',
        lead='Find the Insects in Jars you are missing',
        what='<p>Five live insects in jars are hidden around Skyrim: a bee, a butterfly, a dragonfly, a moth and a '
             'torchbug, each with an inscription inside the lid. Saints &amp; Seducers, which every copy of Skyrim '
             'Special Edition has carried since the Anniversary update, adds three more: a bliss bug and a purple and '
             'a green butterfly. Those three show only for saves that have it.</p>',
        why='<p>They serve no quest and no reward, which is exactly why they are easy to forget.</p>',
        extra=''),
    'trophy': dict(
        slug='thieves-guild-trophies', name='Thieves Guild Trophies', count='14',
        lead='Fill the Thieves Guild trophy shelves',
        what='<p>Fourteen trophies can appear in the Cistern: the seven treasures of the Litany of Larceny, six '
             'more after 5, 15, 25, 35, 45 and 55 jobs for Vex and Delvin, and Barenziah\'s Crown.</p>',
        why='<p>The Litany treasures are scattered across the guild\'s quests, from Goldenglow Estate to Irkngthand, '
            'and Delvin only puts one on the shelf once you sell it to him. The map shows where each one is picked up, '
            'and the list tells you when you are carrying one he has not bought yet.</p>',
        extra=''),
}


def about(spec):
    extra = spec['extra'] + '\n' if spec['extra'] else ''
    return f'''  <section id="about" class="about panel">
    <h2>{spec['lead']}</h2>
{spec['what']}
{spec['why']}

    <h2>What this page does</h2>
    <p>Drop your save in above, from Skyrim, Skyrim Special Edition or Skyrim VR, and it works out which of the
      {spec['name']} you already have. Whatever is left is listed with its location and pinned on the map.</p>
    <p>The save is read in your browser. Nothing is uploaded, and there is nothing to install.</p>
{extra}    <p>If you would rather see everything at once, the <a href="../">full tracker</a> covers every kind of
      collectible together.</p>
  </section>
'''


def retarget(src, kind, spec):
    name, slug = spec['name'], spec['slug']
    title = f'Skyrim {name} Tracker — see which of the {spec["count"]} you are missing'
    desc = (f'Drop a Skyrim, Skyrim Special Edition or Skyrim VR save on the page and see which {name} you have not '
            f'collected yet, listed with their locations and pinned on the map.')
    s = src
    s = re.sub(r'<title>.*?</title>', f'<title>{title}</title>', s, count=1)
    s = re.sub(r'<meta name="description" content=".*?">', f'<meta name="description" content="{desc}">', s, count=1)
    s = s.replace(f'<link rel="canonical" href="{SITE}">', f'<link rel="canonical" href="{SITE}{slug}/">')
    s = s.replace('<meta property="og:title" content="Skyrim Collectibles Tracker">', f'<meta property="og:title" content="{title}">')
    s = s.replace('<meta name="twitter:title" content="Skyrim Collectibles Tracker">', f'<meta name="twitter:title" content="{title}">')
    s = re.sub(r'<meta property="og:description" content=".*?">', f'<meta property="og:description" content="{desc}">', s, count=1)
    s = re.sub(r'<meta name="twitter:description" content=".*?">', f'<meta name="twitter:description" content="{desc}">', s, count=1)
    s = s.replace(f'<meta property="og:url" content="{SITE}">', f'<meta property="og:url" content="{SITE}{slug}/">')
    s = re.sub(r'<script type="application/ld\+json">.*?</script>', f'''<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "WebApplication",
  "name": "Skyrim {name} Tracker",
  "url": "{SITE}{slug}/",
  "applicationCategory": "GameApplication",
  "operatingSystem": "Any browser",
  "browserRequirements": "Requires JavaScript",
  "offers": {{ "@type": "Offer", "price": "0", "priceCurrency": "USD" }},
  "description": "{desc}",
  "screenshot": "{SITE}img/og.jpg",
  "about": {{ "@type": "VideoGame", "name": "The Elder Scrolls V: Skyrim", "publisher": {{ "@type": "Organization", "name": "Bethesda Softworks" }} }}
}}
</script>''', s, count=1, flags=re.S)

    for attr in ('href', 'src'):
        for d in ('img/', 'css/', 'js/', 'data/'):
            s = s.replace(f'{attr}="{d}', f'{attr}="../{d}')
    s = s.replace('href="favicon.ico"', 'href="../favicon.ico"')
    for page in PAGES.values():
        s = s.replace(f'href="{page["slug"]}/"', f'href="../{page["slug"]}/"')

    s = s.replace('<body>', f'<body data-kind="{kind}">', 1)
    s = s.replace('<h1>Skyrim Collectibles Tracker</h1>', f'<h1>Skyrim {name}</h1>', 1)
    s = s.replace('<main class="wrap">',
                  '<main class="wrap">\n  <nav class="crumbs"><a href="../">Skyrim Collectibles Tracker</a> '
                  f'&rsaquo; {name}</nav>\n', 1)

    start = s.index('  <section id="about"')
    end = s.index('</section>', start) + len('</section>\n')
    return s[:start] + about(spec) + s[end:]


src = (DOCS / 'index.html').read_text(encoding='utf-8')
for kind, spec in PAGES.items():
    d = DOCS / spec['slug']
    d.mkdir(parents=True, exist_ok=True)
    (d / 'index.html').write_text(retarget(src, kind, spec), encoding='utf-8')
    print(spec['slug'], spec['name'])

urls = [SITE] + [SITE + s['slug'] + '/' for s in PAGES.values()]
(DOCS / 'sitemap.xml').write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + ''.join(f'  <url>\n    <loc>{u}</loc>\n    <changefreq>monthly</changefreq>\n'
              f'    <priority>{"1.0" if u == SITE else "0.8"}</priority>\n  </url>\n' for u in urls)
    + '</urlset>\n', encoding='utf-8')
(DOCS / 'robots.txt').write_text(f'User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n', encoding='utf-8')
print('sitemap', len(urls), 'urls')
