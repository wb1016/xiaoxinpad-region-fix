#!/usr/bin/env python3
"""Locate every FDT blob (by magic 0xd00dfeed) inside a dtbo image and print
region-related properties.  Robust against header-layout guesswork:
python dtbo_regions.py <dtbo file>"""
import sys, struct

P = sys.argv[1]
d = open(P, "rb").read()
print("IMAGE %s  %d bytes" % (P, len(d)))

FDT_MAGIC = bytes.fromhex("d00dfeed")
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9
KEYS = ("country", "province", "city", "product_region", "hardware", "region",
        "boardid", "hwboardid", "sku", "component")

def parse_fdt(base):
    magic, totalsize, off_struct, off_strings, off_rsv, version = \
        struct.unpack_from(">IIIIII", d, base)
    if magic != 0xD00DFEED or totalsize > len(d) - base or off_struct > totalsize:
        return None
    strings = d[base + off_strings: base + totalsize]
    pos = base + off_struct
    end = base + totalsize
    out, path = [], []
    guard = 0
    while pos + 4 <= end and guard < 200000:
        guard += 1
        tok, = struct.unpack_from(">I", d, pos)
        pos += 4
        if tok == FDT_BEGIN_NODE:
            e = d.find(b"\x00", pos)
            if e < 0:
                break
            path.append(d[pos:e].decode("latin1"))
            pos = (e + 4) & ~3
        elif tok == FDT_END_NODE:
            if path:
                path.pop()
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack_from(">II", d, pos)
            pos += 8
            e = strings.find(b"\x00", nameoff)
            nm = strings[nameoff:e].decode("latin1")
            val = d[pos:pos + ln]
            pos = (pos + ln + 3) & ~3
            out.append(("/" + "/".join(p for p in path if p), nm, val))
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            break
        else:
            break
    return out

def show(v):
    if v and b"\x00" in v and all(32 <= c < 127 for c in v.replace(b"\x00", b"")):
        return "str:" + "|".join(p.decode("latin1") for p in v.split(b"\x00") if p)
    if len(v) in (4, 8) and v:
        return "u%d:%#x (%d)" % (len(v) * 8, int.from_bytes(v, "big"), int.from_bytes(v, "big"))
    if v and all(32 <= c < 127 for c in v):
        return "ascii:" + v.decode("latin1")
    return "raw:" + v.hex()

starts = []
i = 0
while True:
    i = d.find(FDT_MAGIC, i)
    if i < 0:
        break
    starts.append(i)
    i += 4
print("FDT magic offsets: %s" % ", ".join(hex(s) for s in starts[:40]),
      "(%d total)" % len(starts))

shown = 0
for s in starts:
    props = parse_fdt(s)
    if not props:
        continue
    hits = [(p, n, v) for (p, n, v) in props if any(k in n.lower() for k in KEYS)]
    if not hits:
        continue
    shown += 1
    print("\n--- FDT @%#x : %d region props ---" % (s, len(hits)))
    for p, n, v in hits[:30]:
        print("    %-50s %-16s = %s" % (p[-50:], n, show(v)[:80]))
if not shown:
    print("NO region properties found in any FDT")