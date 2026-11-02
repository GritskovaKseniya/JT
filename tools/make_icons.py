"""Genera i tre loghi di JT in Graphics/icons/ (bubbles, pixel_block, pixel_cube).

Serve Pillow (non fa parte dell'app):  uv pip install pillow   poi:  python tools/make_icons.py [--flat-small]

--flat-small: a 16-24 px il logo 'bubbles' usa la tessera piatta con JT invece dei due fumetti

pixel_block  blocco piatto 16x16 stile Minecraft
pixel_cube   cubo isometrico 32x32 stile Minecraft, con una lettera per faccia
bubbles      due fumetti di traduzione, disegno liscio
Nei formati piccoli (16-24 px) B e C usano un disegno semplificato: i dettagli non si leggerebbero.
"""
import os
import random
import struct
import sys
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
OUT = ARGS[0] if ARGS else os.path.join(ROOT, 'Graphics', 'icons')
os.makedirs(OUT, exist_ok=True)
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
FONT_BLACK = 'C:/Windows/Fonts/seguibl.ttf'
FONT_BOLD = 'C:/Windows/Fonts/segoeuib.ttf'


# ------------------------------------------------------------------ A: blocco piatto (attuale)

def option_a():
    palette = {'base': (11, 92, 171), 'light': (42, 123, 208), 'dark': (8, 74, 140), 'edge_light': (94, 164, 234),
               'edge_dark': (6, 44, 84), 'letter': (255, 255, 255), 'shadow': (6, 44, 84)}
    glyph_j = ['...##.', '...##.', '...##.', '...##.', '...##.', '#..##.', '#..##.', '#####.', '.###..']
    glyph_t = ['######', '######', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..']
    rng = random.Random(7)
    img = Image.new('RGBA', (16, 16))
    px = img.load()
    for y in range(16):
        for x in range(16):
            roll = rng.random()
            px[x, y] = (palette['light'] if roll < 0.14 else palette['dark'] if roll < 0.30 else palette['base']) + (255,)
    for i in range(16):
        px[i, 0] = px[0, i] = palette['edge_light'] + (255,)
        px[i, 15] = px[15, i] = palette['edge_dark'] + (255,)
    px[0, 15] = px[15, 0] = palette['base'] + (255,)

    def stamp(glyph, left, top, color):
        for dy, row in enumerate(glyph):
            for dx, cell in enumerate(row):
                if cell == '#':
                    px[left + dx, top + dy] = color + (255,)
    for glyph, left in ((glyph_j, 1), (glyph_t, 8)):
        stamp(glyph, left + 1, 4, palette['shadow'])
    for glyph, left in ((glyph_j, 1), (glyph_t, 8)):
        stamp(glyph, left, 3, palette['letter'])
    return img


# ------------------------------------------------------------- B: cubo isometrico 32x32

def option_b():
    size = 32
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    px = img.load()
    rng = random.Random(11)
    top = [(16, 1), (30, 8), (16, 15), (2, 8)]
    left = [(2, 8), (16, 15), (16, 30), (2, 23)]
    right = [(16, 15), (30, 8), (30, 23), (16, 30)]
    tones = {
        'top': [(122, 186, 243), (94, 164, 234), (146, 202, 250)],
        'left': [(42, 123, 208), (35, 111, 192), (56, 137, 220)],
        'right': [(11, 92, 171), (8, 78, 150), (14, 104, 188)],
    }

    def inside(polygon, x, y):
        inside_flag, n = False, len(polygon)
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside_flag = not inside_flag
            j = i
        return inside_flag

    for name, polygon in (('top', top), ('left', left), ('right', right)):
        for y in range(size):
            for x in range(size):
                if inside(polygon, x + 0.5, y + 0.5):
                    base, shade, light = tones[name]
                    roll = rng.random()
                    px[x, y] = (light if roll < 0.14 else shade if roll < 0.32 else base) + (255,)
    outline = (6, 44, 84, 255)

    def line(a, b, color):                       # linea 1 pixel (Bresenham)
        (x0, y0), (x1, y1) = a, b
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            if 0 <= x0 < size and 0 <= y0 < size:
                px[x0, y0] = color
            if (x0, y0) == (x1, y1):
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    for a, b in ((top[0], top[1]), (top[1], right[2]), (right[2], right[3]), (right[3], left[3]), (left[3], left[0]),
                 (left[0], top[0])):
        line(a, b, outline)
    line(left[1], right[0], (46, 100, 160, 255)) if False else None
    for a, b in ((top[3], top[2]), (top[2], top[1]), (top[2], left[2]), ):      # spigoli interni piu' chiari
        line(a, b, (70, 140, 215, 255) if b == left[2] else (170, 214, 252, 255))
    line(left[1], left[2], (28, 86, 150, 255))
    line(top[3], top[2], (170, 214, 252, 255))
    # lettere sulle facce: J a sinistra, T a destra, su una "targhetta" piatta, in prospettiva isometrica
    glyph_j = ['...##.', '...##.', '...##.', '...##.', '...##.', '#..##.', '#..##.', '#####.', '.###..']
    glyph_t = ['######', '######', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..']

    def face_xy(face, u, v):
        """Pixel della faccia: u va lungo il bordo alto (scalini 2:1), v verso il basso."""
        if face == 'left':
            return 2 + u, 8 + u // 2 + v
        return 16 + u, 15 - (u + 1) // 2 + v

    def put(face, u, v, color):
        x, y = face_xy(face, u, v)
        if 0 <= x < size and 0 <= y < size:
            px[x, y] = color + (255,)

    plates = {'left': (24, 96, 176), 'right': (7, 66, 128)}
    for face, glyph, letter, shadow in (('left', glyph_j, (255, 255, 255), (6, 40, 80)),
                                        ('right', glyph_t, (226, 240, 252), (4, 30, 64))):
        for u in range(2, 12):                       # targhetta liscia dietro la lettera
            for v in range(0, 13):
                put(face, u, v, plates[face])
        for v, row in enumerate(glyph):               # ombra un pixel sotto, poi la lettera
            for u, cell in enumerate(row):
                if cell == '#':
                    put(face, 4 + u - 1, 2 + v + 1, shadow)
        for v, row in enumerate(glyph):
            for u, cell in enumerate(row):
                if cell == '#':
                    put(face, 4 + u - 1, 2 + v, letter)
    # scintille sulla faccia superiore
    for x, y in ((15, 5), (21, 8), (11, 7)):
        px[x, y] = (235, 246, 255, 255)
    return img


# ------------------------------------------------------------ C: due fumetti, disegno liscio

def option_c(size):
    scale = 4
    big = size * scale
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # tessera con sfumatura verticale
    gradient = Image.new('RGBA', (big, big))
    gpx = gradient.load()
    top_c, bottom_c = (36, 124, 218), (7, 70, 134)
    for y in range(big):
        t = y / (big - 1)
        c = tuple(int(top_c[i] + (bottom_c[i] - top_c[i]) * t) for i in range(3)) + (255,)
        for x in range(big):
            gpx[x, y] = c
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((big * 0.03, big * 0.03, big * 0.97, big * 0.97), radius=big * 0.22, fill=255)
    img.paste(gradient, (0, 0), mask)
    # riflesso in alto
    gloss = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse((-big * 0.2, -big * 0.55, big * 1.2, big * 0.42), fill=(255, 255, 255, 38))
    gloss_mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(gloss_mask).rounded_rectangle((big * 0.03, big * 0.03, big * 0.97, big * 0.97), radius=big * 0.22, fill=255)
    img = Image.alpha_composite(img, Image.composite(gloss, Image.new('RGBA', (big, big), (0, 0, 0, 0)), gloss_mask))

    def bubble(box, tail, fill, shadow_alpha=70):
        shadow = Image.new('RGBA', (big, big), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        x0, y0, x1, y1 = box
        off = big * 0.018
        sd.rounded_rectangle((x0 + off, y0 + off, x1 + off, y1 + off), radius=big * 0.1, fill=(0, 20, 50, shadow_alpha))
        sd.polygon([(px_ + off, py_ + off) for px_, py_ in tail], fill=(0, 20, 50, shadow_alpha))
        shadow = shadow.filter(ImageFilter.GaussianBlur(big * 0.012))
        layer = Image.alpha_composite(Image.new('RGBA', (big, big), (0, 0, 0, 0)), shadow)
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle(box, radius=big * 0.1, fill=fill)
        d.polygon(tail, fill=fill)
        return layer

    back = bubble((big * 0.42, big * 0.42, big * 0.90, big * 0.80), [(big * 0.72, big * 0.78), (big * 0.80, big * 0.90), (big * 0.62, big * 0.78)],
                  (70, 190, 255, 255))
    front = bubble((big * 0.10, big * 0.13, big * 0.60, big * 0.55), [(big * 0.22, big * 0.53), (big * 0.16, big * 0.68), (big * 0.36, big * 0.53)],
                   (255, 255, 255, 255))
    img = Image.alpha_composite(Image.alpha_composite(img, back), front)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BLACK, int(big * 0.34))
    draw.text((big * 0.35, big * 0.34), 'J', font=font, fill=(11, 92, 171, 255), anchor='mm')
    draw.text((big * 0.66, big * 0.61), 'T', font=font, fill=(255, 255, 255, 255), anchor='mm')
    return img.resize((size, size), Image.LANCZOS)


def option_c_mini(size):
    """16-24 px: gli stessi due fumetti, ma senza riflesso e ombre e con le lettere grandi (i dettagli non si leggerebbero)."""
    scale = 8
    big = size * scale
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 0.2, fill=(11, 92, 171, 255))
    layer = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((big * 0.40, big * 0.40, big * 0.93, big * 0.85), radius=big * 0.12, fill=(70, 190, 255, 255))
    d.polygon([(big * 0.70, big * 0.83), (big * 0.80, big * 0.96), (big * 0.60, big * 0.83)], fill=(70, 190, 255, 255))
    d.rounded_rectangle((big * 0.07, big * 0.09, big * 0.62, big * 0.60), radius=big * 0.12, fill=(255, 255, 255, 255))
    d.polygon([(big * 0.14, big * 0.58), (big * 0.09, big * 0.76), (big * 0.32, big * 0.58)], fill=(255, 255, 255, 255))
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BLACK, int(big * 0.40))
    d.text((big * 0.345, big * 0.345), 'J', font=font, fill=(11, 92, 171, 255), anchor='mm')
    d.text((big * 0.665, big * 0.645), 'T', font=font, fill=(255, 255, 255, 255), anchor='mm')
    return img.resize((size, size), Image.LANCZOS)


def option_c_small(size):
    """16-24 px: tessera piatta con JT grosse (senza fumetti)."""
    scale = 8
    big = size * scale
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 0.2, fill=(11, 92, 171, 255))
    font = ImageFont.truetype(FONT_BLACK, int(big * 0.62))
    draw.text((big / 2, big / 2 + big * 0.03), 'JT', font=font, fill=(255, 255, 255, 255), anchor='mm')
    return img.resize((size, size), Image.LANCZOS)


# ------------------------------------------------------------------------------ uscita

def png_bytes(image):
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def write_ico(path, images):
    blobs = [png_bytes(img) for img in images]
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b''
    for img, blob in zip(images, blobs):
        size = img.width
        entries += struct.pack('<BBBBHHII', 0 if size >= 256 else size, 0 if size >= 256 else size, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(path, 'wb') as f:
        f.write(header + entries + b''.join(blobs))


art_a, art_b = option_a(), option_b()
sets = {
    'pixel_block': [art_a.resize((s, s), Image.NEAREST) for s in SIZES],
    'pixel_cube': [art_a.resize((s, s), Image.NEAREST) if s < 32 else art_b.resize((s, s), Image.NEAREST) for s in SIZES],
    'bubbles': [(option_c_small(s) if '--flat-small' in sys.argv else option_c_mini(s)) if s < 32 else option_c(s) for s in SIZES],
}
for name, images in sets.items():
    write_ico(os.path.join(OUT, f'{name}.ico'), images)
print(sorted(os.listdir(OUT)))
