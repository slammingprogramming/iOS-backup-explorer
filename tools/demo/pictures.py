# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Pictures drawn by the program (landscapes made of gradients and
shapes), used as the photos of the demo backup. Needs Pillow."""

import io
import math
import random

SCENES = ("sunset", "forest", "beach", "city", "mountains", "flowers",
          "night", "lake")


def _gradient(draw, size, top, bottom, until=None):
    width, height = size
    until = until or height
    for y in range(until):
        t = y / max(1, until - 1)
        colour = tuple(int(top[i] + (bottom[i] - top[i]) * t)
                       for i in range(3))
        draw.line([(0, y), (width, y)], fill=colour)


def _hills(draw, size, base, colour, amplitude, seed, step=8):
    rng = random.Random(seed)
    width, height = size
    phase = rng.random() * 6.28
    wobble = rng.random() * 2 + 1
    points = [(0, height)]
    for x in range(0, width + step, step):
        y = base + amplitude * math.sin(x / width * wobble * 6.28 + phase)
        points.append((x, y))
    points.append((width, height))
    draw.polygon(points, fill=colour)


def scene(kind, size=(640, 480), seed=1):
    """A picture of *kind* (one of :data:`SCENES`) as a PIL image."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    width, height = size
    rng = random.Random(seed)
    if kind == "sunset":
        _gradient(draw, size, (40, 30, 90), (250, 150, 70), int(height * .7))
        sun = (width * (.3 + rng.random() * .4), height * .55)
        draw.ellipse([sun[0] - 50, sun[1] - 50, sun[0] + 50, sun[1] + 50],
                     fill=(255, 220, 140))
        _hills(draw, size, height * .72, (45, 30, 60), 18, seed)
        _hills(draw, size, height * .84, (25, 18, 40), 12, seed + 5)
    elif kind == "forest":
        _gradient(draw, size, (150, 200, 230), (225, 240, 235))
        _hills(draw, size, height * .55, (70, 120, 90), 25, seed)
        for layer, colour in enumerate(((40, 100, 60), (25, 80, 50),
                                        (15, 60, 40))):
            for _ in range(14):
                x = rng.randrange(width)
                top = height * (.35 + .12 * layer) + rng.randrange(40)
                span = 28 + layer * 8
                draw.polygon([(x, top), (x - span, top + span * 2.4),
                              (x + span, top + span * 2.4)], fill=colour)
        draw.rectangle([0, height * .92, width, height], fill=(30, 55, 35))
    elif kind == "beach":
        _gradient(draw, size, (110, 190, 240), (210, 235, 250),
                  int(height * .5))
        draw.rectangle([0, height * .5, width, height * .72],
                       fill=(40, 130, 190))
        for row in range(5):
            y = height * (.52 + row * .04)
            for x in range(-20, width, 60):
                draw.arc([x, y, x + 60, y + 14], 200, 340,
                         fill=(210, 240, 250), width=2)
        draw.rectangle([0, height * .72, width, height], fill=(235, 215, 165))
        draw.ellipse([width * .8, height * .08, width * .8 + 70,
                      height * .08 + 70], fill=(255, 245, 190))
    elif kind == "city":
        _gradient(draw, size, (20, 25, 60), (230, 140, 120), int(height * .8))
        x = 0
        while x < width:
            w = rng.randrange(30, 70)
            h = rng.randrange(int(height * .25), int(height * .7))
            shade = rng.randrange(25, 60)
            draw.rectangle([x, height - h, x + w, height],
                           fill=(shade, shade, shade + 15))
            for wy in range(height - h + 8, height - 8, 16):
                for wx in range(x + 6, x + w - 6, 12):
                    if rng.random() < .45:
                        draw.rectangle([wx, wy, wx + 5, wy + 8],
                                       fill=(250, 220, 120))
            x += w + 3
    elif kind == "mountains":
        _gradient(draw, size, (90, 140, 210), (200, 225, 245))
        for layer, colour in enumerate(((150, 165, 190), (110, 125, 155),
                                        (70, 85, 115))):
            base = height * (.5 + layer * .12)
            points = [(0, height)]
            for x in range(0, width + 40, 40):
                points.append((x, base - rng.randrange(20, 120)
                               + layer * 20))
            points.append((width, height))
            draw.polygon(points, fill=colour)
        draw.rectangle([0, height * .88, width, height], fill=(235, 240, 245))
    elif kind == "flowers":
        _gradient(draw, size, (160, 210, 150), (90, 160, 90))
        palette = ((235, 90, 120), (250, 200, 60), (250, 250, 250),
                   (160, 110, 220), (240, 140, 60))
        for _ in range(45):
            cx, cy = rng.randrange(width), rng.randrange(int(height * .3),
                                                         height)
            r = rng.randrange(10, 26)
            colour = palette[rng.randrange(len(palette))]
            for petal in range(6):
                angle = petal * math.pi / 3
                px, py = cx + math.cos(angle) * r, cy + math.sin(angle) * r
                draw.ellipse([px - r * .6, py - r * .6, px + r * .6,
                              py + r * .6], fill=colour)
            draw.ellipse([cx - r * .45, cy - r * .45, cx + r * .45,
                          cy + r * .45], fill=(250, 220, 90))
    elif kind == "night":
        _gradient(draw, size, (5, 8, 30), (30, 40, 90))
        for _ in range(120):
            sx, sy = rng.randrange(width), rng.randrange(int(height * .8))
            draw.point((sx, sy), fill=(255, 255, 255))
        draw.ellipse([width * .7, height * .12, width * .7 + 60,
                      height * .12 + 60], fill=(245, 245, 220))
        _hills(draw, size, height * .85, (8, 10, 20), 14, seed)
    else:                                            # lake
        _gradient(draw, size, (140, 190, 235), (235, 225, 210),
                  int(height * .5))
        _hills(draw, size, height * .46, (80, 110, 100), 20, seed)
        draw.rectangle([0, height * .5, width, height], fill=(70, 120, 160))
        for row in range(14):
            y = height * .52 + row * 14
            draw.line([(rng.randrange(width // 2), y),
                       (rng.randrange(width // 2, width), y)],
                      fill=(110, 160, 195), width=2)
    return image


def jpeg(kind, size=(640, 480), seed=1, quality=82):
    """The bytes of a JPEG picture of *kind*."""
    buffer = io.BytesIO()
    scene(kind, size, seed).save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def png(kind, size=(480, 320), seed=1):
    buffer = io.BytesIO()
    scene(kind, size, seed).save(buffer, "PNG")
    return buffer.getvalue()
