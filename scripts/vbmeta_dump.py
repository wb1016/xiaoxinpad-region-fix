#!/usr/bin/env python3
"""Dump vbmeta strings + dtbo product_region/country/city property values."""
import re, struct, os

print("=" * 70, "\nVBmeta strings\n", "=" * 70)
for p in [r"vbmeta.img",
          r"vbmeta_system.img",
          r"vbmeta_vendor.img"]:
    d = open(p, "rb").read()
    print("\n--", os.path.basename(p), len(d))
    for m in re.finditer(rb"[\x20-\x7e]{4,}", d):
        print("   %#06x %s" % (m.start(), m.group().decode()))

print("\n" + "=" * 70, "\ndtbo property context\n", "=" * 70)
d = open(r"dtbo.img", "rb").read()
for nd in (b"product_region", b"country", b"city", b"hardware", b"CNXX", b"ROW", b"PRC"):
    st, hits = 0, 0
    while hits < 12:
        k = d.find(nd, st)
        if k < 0:
            break
        st = k + 1
        hits += 1
        ctx = d[max(0, k - 96):k + 128]
        print("  %r @%#x:\n     %s\n     %s" % (
            nd, k,
            bytes(c if 32 <= c < 127 else 46 for c in ctx[:96]).decode(),
            bytes(c if 32 <= c < 127 else 46 for c in ctx[96:]).decode()))

print("\n" + "=" * 70, "\nproinfo header\n", "=" * 70)
d = open(r"id_proinfo.bin", "rb").read()
for i in range(0, 0x400, 16):
    row = d[i:i + 16]
    if all(b == 0 for b in row):
        continue
    print("%06x  %-48s %s" % (i, row.hex(" "),
          "".join(chr(c) if 32 <= c < 127 else "." for c in row)))