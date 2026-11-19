#!/usr/bin/env python3
"""Decode the MTK logo.img container payload: is it a bitmap carrier?"""
import struct, math, collections, zlib, sys

P = sys.argv[1] if len(sys.argv) > 1 else r"logo.img"
d = open(P, "rb").read()
size = len(d)
mag, total = struct.unpack_from("<II", d, 0)
name = d[8:40].split(b"\x00")[0]
print("outer: magic=%#x total=%#x name=%r filesize=%d  payload_end=%#x" %
      (mag, total, name, size, 8 + total))

# payload starts at 0x30 per container layout guess
start = 0x30
end = 8 + total
print("payload [%#x, %#x) len=%#x  trailer=%d bytes" % (start, end, end - start, size - end))

# find where the 0xff run ends
i = start
while i < end and d[i] == 0xFF:
    i += 1
print("leading 0xFF run: %#x .. %#x (%d bytes)" % (start, i, i - start))

def entropy(b):
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values())

# entropy profile in 4KB steps
print("\n-- entropy profile (4KB) --")
prof = []
for off in range(start, end, 4096):
    blk = d[off:off + 4096]
    prof.append((off, entropy(blk), blk.count(0) / len(blk)))
for off, e, zf in prof[:6] + prof[-6:]:
    print("   %#x  H=%.2f  zeros=%.2f" % (off, e, zf))
print("   H min/max: %.2f / %.2f" % (min(p[1] for p in prof), max(p[1] for p in prof)))

# try zlib at every plausible zlib header offset
print("\n-- zlib attempts --")
found = 0
st = start
while found < 20:
    k = d.find(b"\x78", st)
    if k < 0 or k >= end:
        break
    st = k + 1
    if d[k + 1] not in (0x01, 0x5E, 0x9C, 0xDA):
        continue
    try:
        o = zlib.decompressobj()
        out = o.decompress(d[k:end], 1 << 26)
        if len(out) > 1024:
            found += 1
            print("   zlib @%#x -> %d bytes  H=%.2f  head=%r" %
                  (k, len(out), entropy(out[:65536]), out[:32]))
    except Exception:
        pass

# gzip / lz4 frame / lz4 legacy / zstd / xz markers inside payload
print("\n-- container markers in payload --")
for sig, nm in [(b"\x1f\x8b\x08", "gzip"), (b"\x04\x22\x4d\x18", "lz4frame"),
                (b"\x02\x21\x4c\x18", "lz4legacy"), (b"\xfd7zXZ\x00", "xz"),
                (b"\x28\xb5\x2f\xfd", "zstd"), (b"\x89PNG\r\n\x1a\n", "png"),
                (b"\xff\xd8\xff\xe0", "jpeg"), (b"\xff\xd8\xff\xdb", "jpeg-dqt")]:
    pos, st2 = [], start
    while True:
        k = d.find(sig, st2)
        if k < 0 or k >= end:
            break
        pos.append(k)
        st2 = k + 1
    print("   %-11s %d %s" % (nm, len(pos), [hex(p) for p in pos[:8]]))

# hexdump right after the ff run
print("\n-- around end of ff run --")
for off in range(max(start, i - 16), min(end, i + 96), 16):
    row = d[off:off + 16]
    print("  %#08x  %-48s %s" % (off, row.hex(" "),
          "".join(chr(c) if 32 <= c < 127 else "." for c in row)))

# second container header at 0x30
if d[0x30:0x34] == struct.pack("<I", 0x58891689):
    m2, s2 = struct.unpack_from("<II", d, 0x30)
    print("\ninner hdr: magic=%#x size=%#x  next header? @%#x" % (m2, s2, 0x30 + s2))
    print("bytes @ 0x30+s2:", d[0x30 + s2:0x30 + s2 + 64].hex(" "))