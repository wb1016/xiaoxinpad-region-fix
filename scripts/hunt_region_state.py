#!/usr/bin/env python3
"""Hunt for LK's region_state block (magic '1a2b3c4d' / reversed '4d3c2b1a')
across every device dump and firmware image we hold.

LK builds it as:  [x22+0x000] = "1a2b3c4d"   [x22+0x47c] = "4d3c2b1a"
                  [x22+0x408] = 0x100000000   [x22+0x410] = update flag
                  [x22+0x418] = 1             checksum over 0x484 bytes
"""
import os, glob, sys, struct

MAGIC = b"1a2b3c4d"
RMAGIC = b"4d3c2b1a"

# Default search set = every dump/image in the work dir (see scripts/README.md).
# Pass your own globs on the command line to override, e.g.
#   python hunt_region_state.py 'dumps/*.bin' 'fw/*.img'
PATTERNS = sys.argv[1:] or [r"*.bin", r"*.img", r"*.xml", r"image/*.img", r"patched/*.img"]
FILES = []
for pat in PATTERNS:
    FILES += glob.glob(pat)
FILES = sorted(set(FILES))

print("scanning %d files" % len(FILES))
hits_total = 0
for p in FILES:
    try:
        sz = os.path.getsize(p)
        if sz > 4 * 1024 * 1024 * 1024:
            print("  skip huge %s (%d)" % (os.path.basename(p), sz))
            continue
        with open(p, "rb") as f:
            data = f.read()
    except Exception as e:
        print("  ERR", p, e)
        continue
    for needle, tag in ((MAGIC, "MAGIC"), (RMAGIC, "RMAGIC")):
        st = 0
        while True:
            k = data.find(needle, st)
            if k < 0:
                break
            st = k + 1
            hits_total += 1
            ctx = data[max(0, k - 32):k + 64]
            print("  HIT %-7s %-28s @%#x  %s" % (
                tag, os.path.basename(p), k,
                bytes(c if 32 <= c < 127 else 46 for c in ctx).decode()))
            # if this looks like a region_state, dump the interesting fields
            if tag == "MAGIC" and k + 0x484 <= len(data):
                blk = data[k:k + 0x484]
                tail = blk[0x47c:0x484]
                if tail == RMAGIC:
                    flag = struct.unpack_from("<I", blk, 0x410)[0]
                    v418 = struct.unpack_from("<I", blk, 0x418)[0]
                    v408 = struct.unpack_from("<Q", blk, 0x408)[0]
                    print("      * FULL region_state! flag@0x410=%#x  v@0x418=%#x  v@0x408=%#x"
                          % (flag, v418, v408))
                    # printable region fields (country@0, province@0x40, city@0x80)
                    for off, nm in ((0, "country"), (0x40, "province"), (0x80, "city")):
                        s = blk[off:off + 0x40]
                        s = s.split(b"\x00")[0]
                        print("        %-9s @+%#x = %r" % (nm, off, s))
                    # any other printable strings inside the block
                    import re
                    for m in re.finditer(rb"[\x20-\x7e]{3,}", blk):
                        print("        str +%#x: %r" % (m.start(), m.group()))
    sys.stdout.flush()

print("TOTAL HITS:", hits_total)
