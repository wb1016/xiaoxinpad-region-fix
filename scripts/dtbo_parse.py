#!/usr/bin/env python3
"""Parse Android dtbo.img (dt_table_header + FDT blobs) and dump properties
whose value or name relates to region/country/board."""
import struct, sys

P = sys.argv[1] if len(sys.argv) > 1 else r"dtbo.img"
d = open(P, "rb").read()

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9

def parse_fdt(d, base, limit=None):
    magic, totalsize, off_dt_struct, off_dt_strings, off_mem_rsvmap, version = \
        struct.unpack_from(">IIIIII", d, base)
    if magic != FDT_MAGIC:
        return None
    strings = d[base + off_dt_strings: base + totalsize]
    pos = base + off_dt_struct
    end = base + totalsize
    out = []
    path = []
    depth = 0
    while pos + 4 <= end:
        tok, = struct.unpack_from(">I", d, pos)
        pos += 4
        if tok == FDT_BEGIN_NODE:
            e = d.find(b"\x00", pos)
            name = d[pos:e].decode("latin1")
            pos = (e + 4) & ~3
            path.append(name)
            depth += 1
        elif tok == FDT_END_NODE:
            if path:
                path.pop()
            depth -= 1
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack_from(">II", d, pos)
            pos += 8
            nm = strings[nameoff:strings.find(b"\x00", nameoff)].decode("latin1")
            val = d[pos:pos + ln]
            pos = (pos + ln + 3) & ~3
            out.append(("/" + "/".join(p for p in path if p), nm, ln, val))
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            break
        else:
            break
        if limit and len(out) >= limit:
            break
    return out

# dtbo.img: dt_table_header
magic, totalsize, header_size, dt_entry_size, dt_entry_count, dt_entries_offset, page_size, version = \
    struct.unpack_from(">IIIIIIII", d, 0)
print("dt_table: magic=%#x total=%d hdr=%d ent_sz=%d count=%d off=%d page=%d ver=%d" %
      (magic, totalsize, header_size, dt_entry_size, dt_entry_count, dt_entries_offset, page_size, version))

KW = (b"ROW", b"CN", b"PRC", b"region", b"country", b"city", b"province",
      b"hardware", b"board", b"sku", b"sycamore", b"TB336", b"MT8755")

for i in range(dt_entry_count):
    off = dt_entries_offset + i * dt_entry_size
    idv, rev, custom0, custom1, custom2, custom3, offset, size = struct.unpack_from(">IIIIIIII", d, off)
    print("\n== entry %d: id=%#x rev=%#x custom=(%#x,%#x,%#x,%#x) off=%#x size=%#d" %
          (i, idv, rev, custom0, custom1, custom2, custom3, offset, size))
    props = parse_fdt(d, offset)
    if props is None:
        print("   (not an FDT)")
        continue
    print("   props:", len(props))
    for path, nm, ln, val in props:
        try:
            s = val.rstrip(b"\x00").decode("ascii")
        except Exception:
            s = None
        interesting = (s is not None and s and all(32 <= c < 127 for c in val.rstrip(b"\x00"))) and ln < 64
        kwhit = any(k.lower() in nm.lower().encode() or (s and k.lower() in s.lower().encode()) for k in KW)
        if interesting and (kwhit or ln <= 16):
            print("     %-58s = %r" % (path + "  [" + nm + "]", s))
    sys.stdout.flush()