#!/usr/bin/env python3
"""Render decoded logo screens with the correct BGRA channel order."""
import zlib, sys
from PIL import Image

P = sys.argv[1] if len(sys.argv) > 1 else r"logo.img"
OUT = r"_logo_dec"
d = open(P, "rb").read()

for off in (0x369ebb, 0x15ca3a, 0x3765da, 0x5ab982, 0x111fd, 0x3ec, 0x25d854):
    o = zlib.decompressobj()
    raw = o.decompress(d[off:], 40 << 20)
    if len(raw) != 16384000:
        print("%#x unexpected %d" % (off, len(raw)))
        continue
    for label, (w, h) in (("port", (1280, 3200)), ("land", (3200, 1280))):
        im = Image.frombytes("RGBA", (w, h), raw).transpose(Image.FLIP_LEFT_RIGHT)
        # BGRA -> RGBA
        b, g, r, a = im.split()
        im = Image.merge("RGBA", (r, g, b, a))
        prev = im.copy()
        prev.thumbnail((1000, 1000))
        prev.save("%s\\bgra_%06x_%s.png" % (OUT, off, label))
        # also a zoomed crop of the busiest band
        px = im.convert("RGB")
        print("saved %#x %s" % (off, label))
    sys.stdout.flush()

# detailed: the white screen, text band, zoomed
o = zlib.decompressobj()
raw = o.decompress(d[0x369ebb:], 40 << 20)
for label, (w, h) in (("port", (1280, 3200)), ("land", (3200, 1280))):
    im = Image.frombytes("RGBA", (w, h), raw).transpose(Image.FLIP_LEFT_RIGHT)
    b, g, r, a = im.split()
    im = Image.merge("RGBA", (r, g, b, a)).convert("RGB")
    p = im.load()
    minx, miny, maxx, maxy = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            rr, gg, bb = p[x, y]
            if rr > 200 and gg < 120 and bb < 120:   # red text
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    print("%s red bbox=(%d,%d)-(%d,%d)" % (label, minx, miny, maxx, maxy))
    if maxx > minx:
        pad = 40
        crop = im.crop((max(0, minx - pad), max(0, miny - pad),
                        min(w, maxx + pad), min(h, maxy + pad)))
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        crop.save("%s\\WHITESCREEN_%s.png" % (OUT, label))
        print("   saved WHITESCREEN_%s.png %s" % (label, crop.size))