#!/usr/bin/env python3
"""Proper structural dump of MTK logo.img (W) to find any *bitmap* that could
carry the 'not compatible' screen, plus robust JPEG extraction."""
import struct, sys, os, collections

P = sys.argv[1] if len(sys.argv) > 1 else r"logo.img"
d = open(P, "rb").read()
print("size", len(d))

print("\n-- header 0..0x200 --")
for i in range(0, 0x200, 16):
    row = d[i:i + 16]
    print("%06x  %-48s %s" % (i, row.hex(" "),
          "".join(chr(c) if 32 <= c < 127 else "." for c in row)))

print("\n-- tail 0x%x..end --" % (len(d) - 0x200))
for i in range(len(d) - 0x200, len(d), 16):
    row = d[i:i + 16]
    print("%06x  %-48s %s" % (i, row.hex(" "),
          "".join(chr(c) if 32 <= c < 127 else "." for c in row)))

print("\n-- printable strings >= 6 chars --")
cur, start = bytearray(), 0
found = []
for i, b in enumerate(d):
    if 32 <= b < 127:
        if not cur:
            start = i
        cur.append(b)
    else:
        if len(cur) >= 6:
            found.append((start, bytes(cur)))
        cur = bytearray()
for off, s in found:
    print("  %#010x %s" % (off, s.decode()))

print("\n-- JPEG marker positions --")
for sig, name in [(b"\xff\xd8\xff\xe0", "SOI+APP0"), (b"\xff\xd8\xff\xdb", "SOI+DQT"),
                  (b"\xff\xd8\xff\xfe", "SOI+COM"), (b"\xff\xd8\xff\xc0", "SOI+SOF0"),
                  (b"\xff\xd8", "SOI"), (b"\xff\xd9", "EOI"),
                  (b"\x89PNG\r\n\x1a\n", "PNG")]:
    pos, st = [], 0
    while True:
        k = d.find(sig, st)
        if k < 0:
            break
        pos.append(k)
        st = k + 1
        if len(pos) > 40:
            break
    print("  %-10s %d: %s" % (name, len(pos), [hex(p) for p in pos[:20]]))