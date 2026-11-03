"""Builds the icons, mark, favicon, page backdrop and link card in docs/img from Skyrim's archives."""
import io, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
import bsa, render

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'img'
FONTS = ROOT / 'research' / 'fonts'
ICON = 64
LOGO = 'meshes/interface/logo/logo.nif'
# Kind -> (mesh, view direction or 'auto', shapes to draw); keys are the page's kind keys and icon file names.
MESHES = {
    'mask': ('meshes/armor/dragonpriesthelms/dragonhelm_bronze_go.nif', (0, 1, 0)),
    'stone': ('meshes/clutter/quest/barenziahscrown.nif', (0, 1, -0.5)),
    'artifact': ('meshes/clutter/daedric/azurastarlite.nif', 'auto'),
    'claw': ('meshes/clutter/ruins/ruinsdragonclaw02.nif', 'auto'),
    'blackbook': ('meshes/dlc02/clutter/dlc2blackbook01.nif', (0.3, 1, -0.6)),
    'paragon': ('meshes/dlc01/clutter/animated/portalgem01/portalgemorange01.nif', (0, 0, -1)),
    'jiub': ('meshes/clutter/books/note02.nif', 'auto'),
    'kagrumez': ('meshes/dlc02/clutter/quest/kagrumezcontrolgeminv01.nif', (1, 1, -0.5)),
    # Shapes 1, 6 and 7 are the jar's black backing and glass, which the rasteriser can only draw opaque.
    'jar': ('meshes/critters/moths/mothmonarchinjar.nif', (1, 0.3, -0.1), [0, 2, 3, 4, 5]),
    'trophy': ('meshes/clutter/quest/tggoldenurnstatic01.nif', (1, 1, -0.2)),
    'dawnguard': ('meshes/dlc01/weapons/crossbow/crossbow.nif', 'auto'),
    'dragonborn': ('meshes/dlc02/clothes/miraakrobes/miraakhelm_gnd.nif', (0, 1, 0)),
}


def centred(im, size=ICON, pad=2):
    im = im.crop(im.getchannel('A').getbbox())
    im.thumbnail((size - 2 * pad,) * 2, Image.LANCZOS)
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    return out


def brighten(im, k):
    alpha = im.getchannel('A')
    im = ImageEnhance.Brightness(im.convert('RGB')).enhance(k).convert('RGBA')
    im.putalpha(alpha)
    return im


def halo(im, colour, radius):
    """Soft light behind the opaque parts of `im`, so a dark object still reads on the black page."""
    h = Image.new('RGBA', im.size, colour)
    h.putalpha(im.getchannel('A').filter(ImageFilter.GaussianBlur(radius)).point(lambda a: min(255, a * 2)))
    return Image.alpha_composite(h, im)


def silver(im):
    """The menu logo's look: the mesh's own detail, lifted to bright brushed metal."""
    alpha = im.getchannel('A')
    grey = ImageOps.autocontrast(im.convert('L'), cutoff=1)
    grey = grey.point(lambda v: int(120 + v * .53))
    out = ImageOps.colorize(grey, (70, 70, 72), (246, 244, 238), (175, 174, 170)).convert('RGBA')
    out.putalpha(alpha)
    return out


def glass(im):
    """A drawn pane of glass behind the moth, standing in for the jar the rasteriser cannot draw."""
    x0, y0, x1, y1 = im.getchannel('A').getbbox()
    pane = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(pane).rounded_rectangle((x0 + 4, y0 + 8, x1 - 4, y1 - 8), radius=(x1 - x0) // 6,
                                           fill=(200, 220, 225, 46), outline=(235, 245, 248, 170), width=5)
    return Image.alpha_composite(pane, im)


def mesh_icon(kind):
    mesh, view, *shapes = MESHES[kind]
    im = render.render(mesh, 512, view=view, ambient=.55, shapes=shapes[0] if shapes else None)
    if kind == 'jar':
        im = glass(im)
    im = brighten(im, 1.35)
    return centred(halo(centred(im, 256, 14), (255, 255, 255, 60), 6))


def anniversary(size=256):
    """Saints & Seducers ships no emblem of its own, so its flag is an AE monogram in the menu silver."""
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c, r = size / 2, size / 2 - 10
    d.polygon([(c, c - r), (c + r, c), (c, c + r), (c - r, c)], outline=(235, 233, 228, 255), width=size // 22)
    font = ImageFont.truetype(str(FONTS / 'BarlowCondensed-Regular.ttf'), int(size * .5))
    d.text((c, c + size * .01), 'AE', font=font, fill=(246, 244, 238, 255), anchor='mm')
    return centred(halo(im, (255, 255, 255, 40), 5))


def mark(size=200):
    return centred(silver(render.render(LOGO, 900, view=(0, 1, 0), ambient=.7)), size, 4)


def backdrop():
    """The night sky behind the skill constellations, blurred and sunk into the page's black."""
    b = bsa.extract('se', 'textures\\interface\\intfullnebulapanarama01.dds')
    sky = Image.open(io.BytesIO(b)).convert('RGBA')
    sky = Image.alpha_composite(Image.new('RGBA', sky.size, (5, 5, 5, 255)), sky).convert('RGB')
    sky = sky.crop((0, 0, sky.width // 3, sky.height)).resize((1920, 1080), Image.LANCZOS)
    sky = ImageEnhance.Color(sky.filter(ImageFilter.GaussianBlur(14)), ).enhance(.35)
    return Image.blend(sky, Image.new('RGB', sky.size, (5, 5, 5)), .55)


def og_card(icons):
    W, H = 1200, 630
    card = backdrop().resize((W, int(W * 1080 / 1920)), Image.LANCZOS).crop((0, 0, W, H))
    card = ImageEnhance.Brightness(card).enhance(1.4)
    d = ImageDraw.Draw(card)
    title = ImageFont.truetype(str(FONTS / 'BarlowCondensed-Light.ttf'), 76)
    sub = ImageFont.truetype(str(FONTS / 'BarlowCondensed-Light.ttf'), 34)

    def line(text, font, y, fill):
        for dy, colour in ((3, (0, 0, 0)), (0, fill)):
            d.text((W / 2, y + dy), text, font=font, fill=colour, anchor='mm')

    m = mark(150)
    card.paste(m, (int(W / 2 - 75), 34), m)
    line('S K Y R I M   C O L L E C T I B L E S', title, 236, (244, 242, 238))
    d.line([(W / 2 - 300, 288), (W / 2 - 12, 288)], fill=(150, 148, 144), width=1)
    d.line([(W / 2 + 12, 288), (W / 2 + 300, 288)], fill=(150, 148, 144), width=1)
    d.polygon([(W / 2, 282), (W / 2 + 6, 288), (W / 2, 294), (W / 2 - 6, 288)], outline=(200, 198, 192))
    line('Drop in a save from Skyrim, Special Edition or VR and see what is left to find', sub, 330, (190, 188, 182))
    size, gap = 72, 22
    x = int((W - (len(icons) * size + (len(icons) - 1) * gap)) / 2)
    for ic in icons:
        ic = ic.resize((size, size), Image.LANCZOS)
        card.paste(ic, (x, 430), ic)
        x += size + gap
    return card


OUT.mkdir(parents=True, exist_ok=True)
mk = mark()
mk.save(OUT / 'mark.png', optimize=True)
icons = {'shout': centred(halo(centred(mark(256), 256, 14), (255, 255, 255, 50), 6)), 'saints': anniversary()}
for kind in (sys.argv[1:] or MESHES):
    try:
        icons[kind] = mesh_icon(kind)
    except Exception as e:
        print(f'{kind}: {e}')
for k, im in icons.items():
    im.save(OUT / f'{k}.png', optimize=True)

ico = Image.new('RGBA', (512, 512), (5, 5, 5, 255))
g = mk.resize((460, 460), Image.LANCZOS)
ico.paste(g, (26, 26), g)
ico.convert('RGB').save(ROOT / 'docs' / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
ico.resize((180, 180), Image.LANCZOS).save(OUT / 'icon-180.png', optimize=True)

backdrop().save(OUT / 'backdrop.jpg', quality=80, optimize=True, progressive=True)
order = ['mask', 'stone', 'artifact', 'claw', 'blackbook', 'shout', 'paragon', 'jiub', 'kagrumez', 'jar', 'trophy']
og_card([icons[k] for k in order if k in icons]).save(OUT / 'og.jpg', quality=88, optimize=True, progressive=True)

for f in sorted(OUT.iterdir()):
    print(f.name, f.stat().st_size)
