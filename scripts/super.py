#!/usr/bin/env python3
"""Android sparse image + liblp (dynamic partitions) reader.

  python super.py parts  <super.img>
  python super.py list   <super.img> <partition> [path] [depth]
  python super.py search <super.img> <partition|*> <needle> [<needle> ...]
  python super.py extract <super.img> <partition> <member> <outfile>
"""
import sys, os, struct, bisect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erofs import Erofs, resolve, FT, search_fs

CHUNK_RAW, CHUNK_FILL, CHUNK_DONT, CHUNK_CRC = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4
LP_GEOM_MAGIC = 0x616C4467
LP_METADATA_MAGIC = 0x414C5030
LP_RESERVED = 4096
GEOM_SIZE = 4096


class Sparse(object):
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        hdr = self.f.read(28)
        magic, major, minor, fh, ch, blk, total_blks, total_chunks, csum = \
            struct.unpack("<IHHHHIIII", hdr)
        if magic != 0xED26FF3A:
            raise SystemExit("%s: not an Android sparse image" % path)
        self.blk = blk
        self.hdr_sz = fh
        self.chdr_sz = ch
        self.size = total_blks * blk
        self.chunks = []            # (out_off, kind, in_off, len, fill)
        outb = 0
        pos = fh
        for _ in range(total_chunks):
            self.f.seek(pos)
            c = self.f.read(ch)
            ctype, _res, csz, total = struct.unpack("<HHII", c)
            data = pos + ch
            nbytes = csz * blk
            if ctype == CHUNK_RAW:
                self.chunks.append([outb * blk, "raw", data, nbytes, None])
                outb += csz
            elif ctype == CHUNK_FILL:
                self.f.seek(data)
                fill = self.f.read(4)
                self.chunks.append([outb * blk, "fill", None, nbytes, fill])
                outb += csz
            elif ctype == CHUNK_DONT:
                self.chunks.append([outb * blk, "zero", None, nbytes, None])
                outb += csz
            elif ctype == CHUNK_CRC:
                pass
            else:
                raise SystemExit("unknown sparse chunk type %#x" % ctype)
            pos += total
        self.starts = [c[0] for c in self.chunks]

    def read(self, off, n):
        if n <= 0 or off >= self.size:
            return b"\0" * max(0, n)
        n = min(n, self.size - off)
        out = bytearray(n)
        cur = off
        end = off + n
        i = max(0, bisect.bisect_right(self.starts, cur) - 1)
        while i < len(self.chunks) and cur < end:
            start, kind, in_off, clen, fill = self.chunks[i]
            cend = start + clen
            if cend <= cur:
                i += 1
                continue
            s = max(cur, start)
            e = min(end, cend)
            dst = s - off
            ln = e - s
            if kind == "raw":
                self.f.seek(in_off + (s - start))
                out[dst:dst + ln] = self.f.read(ln)
            elif kind == "fill":
                rep = fill * ((ln + 3) // 4)
                out[dst:dst + ln] = rep[:ln]
            cur = e
            i += 1
        return bytes(out)


class LogicalPart(object):
    """A liblp logical partition viewed as a flat byte range.

    This image uses a non-canonical LpMetadataExtent layout, so the byte
    offset of target_data inside an extent entry is probed rather than
    assumed (see probe_part)."""

    def __init__(self, sparse, raw_extents, name="", data_off=12):
        self.sparse = sparse
        self.name = name
        self.extents = []
        lo = 0
        for e in raw_extents:
            num_sectors = struct.unpack_from("<I", e, 0)[0]
            ttype = struct.unpack_from("<I", e, 8)[0] or struct.unpack_from("<I", e, 4)[0]
            ln = num_sectors * 512
            if ttype == 0 and len(e) >= data_off + 8:
                target_data = struct.unpack_from("<Q", e, data_off)[0]
                self.extents.append((lo, target_data * 512, ln))
            lo += ln
        self.size = lo
        self.starts = [e[0] for e in self.extents]

    def read(self, off, n):
        if n <= 0 or off >= self.size:
            return b"\0" * max(0, n)
        n = min(n, self.size - off)
        out = bytearray(n)
        cur = off
        end = off + n
        i = max(0, bisect.bisect_right(self.starts, cur) - 1)
        while i < len(self.extents) and cur < end:
            lo, po, ln = self.extents[i]
            hi = lo + ln
            if hi <= cur:
                i += 1
                continue
            s = max(cur, lo)
            e = min(end, hi)
            out[s - off:e - off] = self.sparse.read(po + (s - lo), e - s)
            cur = e
            i += 1
        return bytes(out)


def parse_geometry(sp):
    for off in (LP_RESERVED, LP_RESERVED + GEOM_SIZE):
        g = sp.read(off, GEOM_SIZE)
        magic, struct_size = struct.unpack_from("<II", g, 0)
        if magic == LP_GEOM_MAGIC:
            max_size, slots, lbs = struct.unpack_from("<III", g, 40)
            return off, max_size, slots, lbs
    raise SystemExit("no liblp geometry found")


def parse_metadata(buf):
    magic, major, minor, header_size, flags = struct.unpack_from("<IHHII", buf, 0)
    if magic != LP_METADATA_MAGIC:
        raise SystemExit("bad LP metadata magic %#x" % magic)

    def u(o):
        return struct.unpack_from("<I", buf, o)[0]

    # The field table does not sit at the canonical offset 16 on this image,
    # so locate it by requiring the four tables to form a contiguous chain
    # that ends at header_size + total.
    base = None
    for cand in range(16, max(16, header_size - 44), 4):
        po, pn, ps = u(cand), u(cand + 4), u(cand + 8)
        eo, en, es = u(cand + 12), u(cand + 16), u(cand + 20)
        go, gn, gs = u(cand + 24), u(cand + 28), u(cand + 32)
        bo, bn, bs = u(cand + 36), u(cand + 40), u(cand + 44)
        if not (0 < pn <= 8192 and 16 <= ps <= 128):
            continue
        if not (en <= 8192 and 16 <= es <= 128):
            continue
        if not (0 < gn <= 4096 and 16 <= gs <= 128):
            continue
        if not (0 < bn <= 64 and 16 <= bs <= 256):
            continue
        # tables must be non-decreasing and near-contiguous
        if not (po <= eo <= go <= bo):
            continue
        if eo - (po + pn * ps) > 16 or go - (eo + en * es) > 16:
            continue
        if bo - (go + gn * gs) > 16:
            continue
        base = cand
        break
    if base is None:
        raise SystemExit("could not locate LP field table")

    part_off = u(base) + header_size
    part_num, part_sz = u(base + 4), u(base + 8)
    ext_off = u(base + 12) + header_size
    ext_num, ext_sz = u(base + 16), u(base + 20)
    grp_off = u(base + 24) + header_size
    grp_num, grp_sz = u(base + 28), u(base + 32)
    bd_off = u(base + 36) + header_size
    bd_num, bd_sz = u(base + 40), u(base + 44)
    print("  LP header: v%d.%d size=%d flags=%#x table@%#x" %
          (major, minor, header_size, flags, base))
    print("  partitions @%#x n=%d sz=%d | extents @%#x n=%d sz=%d | "
          "groups @%#x n=%d sz=%d | blockdev @%#x n=%d sz=%d" %
          (part_off, part_num, part_sz, ext_off, ext_num, ext_sz,
           grp_off, grp_num, grp_sz, bd_off, bd_num, bd_sz))

    def entries(off, num, sz):
        return [buf[off + i * sz: off + (i + 1) * sz] for i in range(num)]

    extents = entries(ext_off, ext_num, ext_sz)   # raw 24-byte records

    parts = []
    for p in entries(part_off, part_num, part_sz):
        name = p[:36].split(b"\0")[0].decode("ascii", "replace")
        attrs, first_ext, num_ext, group = struct.unpack_from("<4I", p, 36)
        parts.append((name, attrs, extents[first_ext:first_ext + num_ext], group))

    groups = []
    for g in entries(grp_off, grp_num, grp_sz):
        name = g[:36].split(b"\0")[0].decode("ascii", "replace")
        gflags, gmax = struct.unpack_from("<II", g, 36)
        groups.append((name, gflags, gmax))

    blockdevs = []
    for b in entries(bd_off, bd_num, bd_sz):
        first_sector, alignment, align_off = struct.unpack_from("<QII", b, 0)
        size = struct.unpack_from("<Q", b, 16)[0]
        name = b[24:60].split(b"\0")[0].decode("ascii", "replace")
        bflags = struct.unpack_from("<I", b, 60)[0]
        blockdevs.append((name, size, first_sector, alignment, bflags))

    return {"version": (major, minor), "partitions": parts, "groups": groups,
            "block_devices": blockdevs, "block_size": None}


def open_super(path):
    sp = Sparse(path)
    geom_off, max_size, slots, lbs = parse_geometry(sp)
    meta_off = LP_RESERVED + 2 * GEOM_SIZE
    meta = sp.read(meta_off, max_size)
    info = parse_metadata(meta)
    info["block_size"] = lbs
    info["geometry_offset"] = geom_off
    info["metadata_max_size"] = max_size
    info["slots"] = slots
    return sp, info


# ------------------------------------------------------------------ commands
def cmd_parts(path):
    sp, info = open_super(path)
    print("sparse size=%d  logical_block_size=%d  metadata v%s slots=%d" %
          (sp.size, info["block_size"], info["version"], info["slots"]))
    print("block devices:", [(n, s) for n, s, _, _, _ in info["block_devices"]])
    print("groups:", info["groups"])
    total = 0
    for name, attrs, exts, group in info["partitions"]:
        size = sum(struct.unpack_from("<I", e, 0)[0] for e in exts) * 512
        total += size
        print("  %-16s attrs=%#010x group=%d size=%12d extents=%d" %
              (name, attrs, group, size, len(exts)))
    print("total partition bytes: %d" % total)


def _looks_like_fs(lp):
    head = lp.read(1024, 60)
    if len(head) < 60:
        return False
    if struct.unpack_from("<I", head, 0)[0] == 0xE0F5E1E2:
        return "EROFS"
    if struct.unpack_from("<H", head, 56)[0] == 0xEF53:
        return "ext4"
    return False


_PART_CACHE = {}


def get_part(sp, info, name):
    for pname, attrs, exts, group in info["partitions"]:
        if pname != name:
            continue
        key = (id(sp), pname)
        if key in _PART_CACHE:
            return _PART_CACHE[key]
        best, best_kind = None, None
        for data_off in (12, 8, 16, 4):
            lp = LogicalPart(sp, exts, pname, data_off)
            if lp.size == 0:
                best, best_kind = lp, "empty"
                break
            kind = _looks_like_fs(lp)
            if kind:
                best, best_kind = lp, kind
                break
            if best is None:
                best = lp
        _PART_CACHE[key] = best
        return best
    raise SystemExit("no such partition %r (try: %s)" %
                     (name, " ".join(p[0] for p in info["partitions"])))


def list_parts(path):
    sp, info = open_super(path)
    for pname, attrs, exts, group in info["partitions"]:
        lp = get_part(sp, info, pname)
        head = lp.read(0, 64)
        kind = "?"
        if head[:4] == b"\xed\x26\xff":
            kind = "sparse"
        elif _looks_like_fs(lp):
            kind = _looks_like_fs(lp)
        else:
            print("      first32=%s" % head[:32].hex())
        print("  %-16s size=%12d  %s" % (pname, lp.size, kind))


def cmd_search(path, part, needles):
    sp, info = open_super(path)
    names = [p[0] for p in info["partitions"]] if part == "*" else [part]
    total = 0
    for name in names:
        lp = get_part(sp, info, name)
        if _looks_like_fs(lp) != "EROFS":
            print("skip %s (not EROFS: %r)" % (name, _looks_like_fs(lp)))
            continue
        print("=== searching %s (%d bytes)" % (name, lp.size))
        fs = Erofs(lp)
        total += search_fs(fs, needles)
    print("TOTAL HITS:", total)


def cmd_list(path, part, root="/", depth=None):
    sp, info = open_super(path)
    lp = get_part(sp, info, part)
    fs = Erofs(lp)
    print("EROFS blocks=%d inos=%d root_nid=%d incompat=%#x" %
          (fs.blocks, fs.inos, fs.root_nid, fs.feature_incompat))
    start = resolve(fs, root) if root != "/" else fs.root_nid
    n = 0
    for p, ino, err in fs.walk(start, path=root, max_depth=depth):
        n += 1
        if err:
            print("%-70s ERR %s" % (p, err))
        elif n <= 800:
            print("%-70s %s mode=%o size=%d dl=%d" %
                  (p, FT.get((ino.mode >> 12) & 15, "?"), ino.mode, ino.size, ino.dl))
    print("total entries:", n)


def cmd_extract(path, part, member, outfile):
    sp, info = open_super(path)
    lp = get_part(sp, info, part)
    fs = Erofs(lp)
    nid = resolve(fs, member)
    data = fs.read_file(fs.inode(nid))
    os.makedirs(os.path.dirname(outfile) or ".", exist_ok=True)
    with open(outfile, "wb") as f:
        f.write(data)
    print("wrote", outfile, len(data))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "parts":
        cmd_parts(sys.argv[2])
    elif cmd == "listparts":
        list_parts(sys.argv[2])
    elif cmd == "list":
        cmd_list(sys.argv[2], sys.argv[3],
                 sys.argv[4] if len(sys.argv) > 4 else "/",
                 int(sys.argv[5]) if len(sys.argv) > 5 else None)
    elif cmd == "search":
        cmd_search(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif cmd == "extract":
        cmd_extract(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        raise SystemExit(__doc__)