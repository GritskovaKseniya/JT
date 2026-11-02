"""Pallini dei passi con antialiasing: Graphics/step_<n>_<stato>[_<px>].png, uno per scala dello schermo.

Serve Pillow (non fa parte dell'app):  uv pip install pillow   poi:  python tools/make_step_badges.py"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Graphics')
S = 8                                  # supersampling
SIZES = (24, 30, 36, 48)               # 100%, 125%, 150%, 200%
COLORS = {'current': '#0b5cab', 'done': '#14703a', 'todo': '#e3e8f0'}


def badge(number, state, size):
    unit = size / 24                   # il disegno e' pensato su 24 px
    big = size * S
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((unit * S, unit * S, big - unit * S, big - unit * S), fill=COLORS[state])
    if state == 'done':
        points = [(7.2 * S * unit, 12.6 * S * unit), (10.4 * S * unit, 15.8 * S * unit), (16.8 * S * unit, 8.6 * S * unit)]
        draw.line(points, fill='white', width=int(2.4 * S * unit), joint='curve')
        radius = 1.2 * S * unit
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill='white')
    else:
        font = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', int(13 * S * unit))
        color = 'white' if state == 'current' else '#4b5563'
        left, top, right, bottom = draw.textbbox((0, 0), str(number), font=font)
        draw.text(((big - (right - left)) / 2 - left, (big - (bottom - top)) / 2 - top), str(number), font=font, fill=color)
    return img.resize((size, size), Image.LANCZOS)


for old in [f for f in os.listdir(OUT) if f.startswith('step_')]:
    os.remove(os.path.join(OUT, old))
for number, state in ((1, 'current'), (1, 'done'), (2, 'todo'), (2, 'current')):      # solo quelli che compaiono
    for size in SIZES:
        suffix = '' if size == 24 else f'_{size}'
        badge(number, state, size).save(os.path.join(OUT, f'step_{number}_{state}{suffix}.png'))
print(len([f for f in os.listdir(OUT) if f.startswith('step_')]), 'file')
