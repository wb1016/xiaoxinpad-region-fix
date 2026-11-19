#!/usr/bin/env python3
"""Map lk.img container structure: segment headers, ELF, entry points."""
import struct, re, sys

P = sys.argv[1] if len(sys.argv) > 1 else r"image/lk.img"
d = open(P, "rb").read()
print("size", len(d))

print("\n-- container headers (magic 0x58881688/0x58891689) --")
for off in range(0, len(d) - 8, 4):
    mag, = struct.unpack_from("<I", d, off)
    if mag in (0x58881688, 0x58891689):
        size, = struct.unpack_from("<I", d, off + 4)
        name = d[off + 8:off + 40].split(b"\x00")[0]
        printable = all(32 <= c < 127 for c in name) if name else False
        print("  @%#08x magic=%#010x size=%#010x name=%r%s" %
              (off, mag, size, name, "" if printable else "   (not a name)"))

print("\n-- ELF signatures --")
st = 0
while True:
    k = d.find(b"\x7fELF", st)
    if k < 0:
        break
    st = k + 1
    print("  ELF @%#x  header=%s" % (k, d[k:k + 20].hex(" ")))

print("\n-- first bytes at 0x30 / 0x430 / 0x230 --")
for off in (0x30, 0x230, 0x430, 0xe4170, 0xe4178, 0xe41a0):
    if off < len(d):
        row = d[off:off + 48]
        print("  %#08x %s  %s" % (off, row.hex(" "),
              "".join(chr(c) if 32 <= c < 127 else "." for c in row)))

# where do readable strings first appear / is payload raw?
print("\n-- string density per 64KB --")
for base in range(0, len(d), 0x10000):
    blk = d[base:base + 0x10000]
    n = len(re.findall(rb"[\x20-\x7e]{8,}", blk))
    if n:
        print("   %#08x  %5d strings" % (base, n))

# index table at 0x230?
print("\n-- u32 table @0x230 (first 40) --")
vals = struct.unpack_from("<40I", d, 0x230)
print("   ", [hex(v) for v in vals])