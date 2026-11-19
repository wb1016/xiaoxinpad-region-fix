#!/usr/bin/env python3
"""Minimal EROFS reader: list / search / extract.

Implements enough of the on-disk format (fs/erofs/erofs_fs.h + zmap.c) to read
files out of mkfs.erofs images with LZ4 compression, no big pcluster, no
tailpacking / fragments / metabox (which is what Lenovo's system images use).
"""
import sys, os, struct, mmap

try:                                    # console may be cp949/cp1252 - never crash on output
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

BS = 4096
FT = {1: "reg", 2: "dir", 3: "chr", 4: "blk", 5: "fifo", 6: "sock", 7: "lnk"}

FLAT_PLAIN, COMPRESSED_FULL, FLAT_INLINE, COMPRESSED_COMPACT, CHUNK_BASED = 0, 1, 2, 3, 4
LC_PLAIN, LC_HEAD1, LC_NONHEAD, LC_HEAD2 = 0, 1, 2, 3

ADV_COMPACTED_2B = 0x0001
ADV_EXTENTS = 0x0001
ADV_BIG_PCLUSTER_1 = 0x0002
ADV_BIG_PCLUSTER_2 = 0x0004
ADV_INLINE_PCLUSTER = 0x0008
ADV_INTERLACED = 0x0010
ADV_FRAGMENT = 0x0020
LI_HOLE = 1 << 14
LI_D0_CBLKCNT = 1 << 11


def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]
def u64(b, o): return struct.unpack_from("<Q", b, o)[0]


class Inode(object):
    __slots__ = ("nid", "off", "fmt", "ver", "dl", "icount", "isize", "xasize",
                 "mode", "size", "startblk", "blocks")

    def __repr__(self):
        return "<ino nid=%d dl=%d mode=%o size=%d>" % (self.nid, self.dl, self.mode, self.size)


class ErofsError(Exception):
    pass


class Sliceable(object):
    """Adapt an object exposing read(off, n) to mm[off:n] slicing."""
    __slots__ = ("r",)

    def __init__(self, reader):
        self.r = reader

    def __getitem__(self, sl):
        if not isinstance(sl, slice) or sl.step not in (None, 1):
            raise TypeError("only contiguous slices supported")
        start = sl.start or 0
        stop = start if sl.stop is None else sl.stop
        if stop < start:
            return b""
        return self.r.read(start, stop - start)


class Erofs(object):
    def __init__(self, src):
        """src: a filesystem path, or an object exposing read(off, n)."""
        if isinstance(src, (str, bytes)) or hasattr(src, "__fspath__"):
            self.path = os.fspath(src)
            self.f = open(self.path, "rb")
            self.mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        else:
            self.path = "<stream>"
            self.f = None
            self.mm = Sliceable(src)
        sb = self.mm[1024:1024 + 144]
        if u32(sb, 0) != 0xE0F5E1E2:
            raise ErofsError("not an EROFS image")
        self.blkszbits = sb[12]
        if self.blkszbits != 12:
            raise ErofsError("unsupported block size bits %d" % self.blkszbits)
        self.root_nid = u16(sb, 14)
        self.inos = u64(sb, 16)
        self.blocks = u32(sb, 36)
        self.meta_blkaddr = u32(sb, 40)
        self.feature_incompat = u32(sb, 80)
        self.packed_nid = u64(sb, 96)
        self.dirblkbits = sb[90]
        self.lz4_max_distance = u16(sb, 84)
        if self.feature_incompat & ~0x01:
            raise ErofsError("unsupported incompat features %#x" % self.feature_incompat)
        if self.packed_nid:
            raise ErofsError("packed inode present; unsupported")

    # ---------------- inode ----------------
    def inode(self, nid):
        off = self.meta_blkaddr * BS + nid * 32
        raw = self.mm[off:off + 64]
        if len(raw) < 64:
            raise ErofsError("short inode read")
        i = Inode()
        i.nid, i.off = nid, off
        i.fmt = u16(raw, 0)
        i.ver = i.fmt & 1
        i.dl = (i.fmt >> 1) & 7
        i.icount = u16(raw, 2)
        i.mode = u16(raw, 4)
        if i.ver == 0:
            i.size = u32(raw, 8)
            i.startblk = u32(raw, 16)
            i.isize = 32
        else:
            i.size = u64(raw, 8)
            i.startblk = u32(raw, 16)
            i.isize = 64
        i.xasize = 0 if i.icount == 0 else 12 + 4 * (i.icount - 1)
        i.blocks = None
        return i

    def inode_isize(self, ino):
        return ino.isize + ino.xasize

    # ---------------- plain data ----------------
    def read_plain(self, ino):
        size = ino.size
        if size == 0:
            return b""
        tail = size % BS
        nblk = (size - tail) // BS
        out = bytearray(size)
        if nblk:
            a = ino.startblk * BS
            chunk = self.mm[a:a + nblk * BS]
            if len(chunk) < nblk * BS:
                raise ErofsError("short block read")
            out[:nblk * BS] = chunk
        if tail:
            ioff = ino.off + ino.isize + ino.xasize
            t = self.mm[ioff:ioff + tail]
            if len(t) < tail:
                raise ErofsError("short tail read")
            out[nblk * BS:] = t
        return bytes(out)

    # ---------------- compressed ----------------
    def _map_header(self, ino):
        hpos = (ino.off + ino.isize + ino.xasize + 7) & ~7
        h = self.mm[hpos:hpos + 8]
        if len(h) < 8:
            raise ErofsError("short map header")
        if h[7] & 0x80:
            raise ErofsError("fragment inode unsupported")
        return h

    @staticmethod
    def _decode_compactedbits(lobits, buf, pos_bits):
        byte = pos_bits >> 3
        if byte + 4 > len(buf):
            raise ErofsError("compact index out of range")
        v = u32(buf, byte) >> (pos_bits & 7)
        lo = v & ((1 << lobits) - 1)
        typ = (v >> lobits) & 3
        return lo, typ

    def _load_full(self, ino, lcn, base):
        p = base + lcn * 8
        di = self.mm[p:p + 8]
        if len(di) < 8:
            raise ErofsError("short index")
        advise = u16(di, 0)
        clusterofs = u16(di, 2)
        du = u32(di, 4)
        typ = advise & 3
        if typ == LC_NONHEAD:
            return typ, None, None, du & 0xFFFF, du >> 16, advise
        if advise & LI_HOLE:
            return typ, clusterofs, None, 0, 0, advise
        return typ, clusterofs, du, 0, 0, advise

    def _load_compact(self, ino, lcn, ebase, totalidx, lcbits, advise):
        c4 = ((32 - ebase % 32) // 4) & 7
        c2 = 0
        if (advise & ADV_COMPACTED_2B) and c4 < totalidx:
            c2 = ((totalidx - c4) // 16) * 16
        pos = ebase
        ams = 2
        if lcn >= c4:
            pos += c4 * 4
            lcn -= c4
            if lcn < c2:
                ams = 1
            else:
                pos += c2 * 2
                lcn -= c2
        pos += lcn * (1 << ams)
        if (1 << ams) == 4:
            if lcbits > 14:
                raise ErofsError("bad lcbits")
            vcnt = 2
        else:
            if lcbits > 12:
                raise ErofsError("bad lcbits")
            vcnt = 16
        lobits = max(lcbits, 12)
        packsize = vcnt << ams
        encodebits = ((vcnt << ams) - 4) * 8 // vcnt
        b_off = pos & (packsize - 1)
        inpos = pos - b_off
        i = b_off >> ams
        buf = self.mm[inpos:inpos + packsize]
        if len(buf) < packsize:
            raise ErofsError("short compact pack")
        lo, typ = self._decode_compactedbits(lobits, buf, encodebits * i)
        if typ == LC_NONHEAD:
            clusterofs = 1 << lcbits
            if lo & LI_D0_CBLKCNT:
                raise ErofsError("big pcluster unsupported")
            d0 = lo
            if i + 1 == vcnt:
                # last lcluster in the pack: lo holds delta[1], so recover
                # delta[0] indirectly from the previous entry (kernel does +1)
                lo2, t2 = self._decode_compactedbits(lobits, buf, encodebits * (i - 1))
                if t2 != LC_NONHEAD:
                    lo2 = 0
                elif lo2 & LI_D0_CBLKCNT:
                    lo2 = 1
                d0 = lo2 + 1
            return typ, clusterofs, None, d0, 0, advise
        clusterofs = lo
        nblk = 1
        j = i
        while j > 0:
            j -= 1
            lo2, t2 = self._decode_compactedbits(lobits, buf, encodebits * j)
            if t2 == LC_NONHEAD:
                j -= lo2
            if j >= 0:
                nblk += 1
        baseblk = u32(buf, packsize - 4)
        return typ, clusterofs, baseblk + nblk, 0, 0, advise

    def read_compressed(self, ino):
        h = self._map_header(ino)
        advise = u16(h, 4)
        algotype = h[6]
        lcbits = 12 + (h[7] & 15)
        lcs = 1 << lcbits
        size = ino.size
        nlc = (size + lcs - 1) // lcs
        if nlc == 0:
            return b""
        if advise & ADV_INLINE_PCLUSTER:
            raise ErofsError("inline pcluster unsupported")
        if advise & ADV_FRAGMENT:
            raise ErofsError("fragment pcluster unsupported")
        if advise & (ADV_BIG_PCLUSTER_1 | ADV_BIG_PCLUSTER_2):
            raise ErofsError("big pcluster unsupported")

        if ino.dl == COMPRESSED_FULL:
            base = ((ino.off + ino.isize + ino.xasize + 7) & ~7) + 16
            def load(lcn):
                return self._load_full(ino, lcn, base)
        else:
            ebase = ((ino.off + ino.isize + ino.xasize + 7) & ~7) + 8
            def load(lcn):
                return self._load_compact(ino, lcn, ebase, nlc, lcbits, advise)

        # resolve head for every logical cluster
        heads = [None] * nlc
        for lcn in range(nlc):
            cur = lcn
            guard = 0
            while True:
                typ, cs, pblk, d0, d1, _ = load(cur)
                if typ != LC_NONHEAD:
                    heads[lcn] = (cur, typ, cs, pblk)
                    break
                if not d0 or cur - d0 < 0:
                    raise ErofsError("bad lookback at lcn %d" % lcn)
                cur -= d0
                guard += 1
                if guard > nlc:
                    raise ErofsError("lookback loop")

        out = bytearray(size)
        lcn = 0
        while lcn < nlc:
            h_lcn, typ, hcs, pblk = heads[lcn]
            end_lcn = lcn
            while end_lcn < nlc and heads[end_lcn][0] == h_lcn:
                end_lcn += 1
            start = h_lcn * lcs + (hcs or 0)
            stop = (end_lcn * lcs + (heads[end_lcn][2] or 0)) if end_lcn < nlc else size
            stop = min(stop, size)
            lcn = end_lcn
            if start >= size or stop <= start:
                continue
            ln = stop - start
            if pblk is None:               # hole -> stays zero
                continue
            blk = self.mm[pblk * BS:pblk * BS + BS]
            if len(blk) < BS:
                raise ErofsError("short pcluster read @%d" % pblk)
            if typ == LC_PLAIN:
                data = blk
            else:
                data = self._lz4(blk, ln, lcs)
            chunk = data[:ln]
            if len(chunk) < ln:
                chunk = chunk + b"\0" * (ln - len(chunk))
            out[start:start + ln] = chunk
        return bytes(out)

    @staticmethod
    def _lz4(comp, want, lcs):
        import lz4.block
        base = (want + 4095) // 4096 * 4096
        caps = [want]
        caps += [base + k * 4096 for k in range(0, 48)]

        def attempt(buf):
            if not buf:
                return None
            seen = set()
            for cap in caps:
                if cap <= 0 or cap in seen:
                    continue
                seen.add(cap)
                try:
                    return lz4.block.decompress(buf, uncompressed_size=cap)
                except Exception:
                    continue
            return None

        # A valid LZ4 block can never start with a zero byte: the first sequence
        # must carry at least one literal (token high nibble != 0), otherwise
        # the match offset would point before the start of the output.  Some
        # EROFS pclusters are padded with leading zeros before the payload, so
        # strip them first -- otherwise python-lz4 either fails outright or
        # "succeeds" with garbage and we silently zero-fill the file tail.
        stripped = None
        if comp[:1] == b"\0":
            nz = 0
            limit = min(len(comp), 4096)
            while nz < limit and comp[nz] == 0:
                nz += 1
            if 0 < nz < len(comp):
                stripped = comp[nz:]
        for buf in ((stripped, comp) if stripped else (comp,)):
            r = attempt(buf)
            if r is not None:
                return r
        return _lz4_lenient(comp, want)

    # ---------------- high level ----------------
    def read_file(self, ino):
        if ino.dl in (FLAT_PLAIN, FLAT_INLINE):
            return self.read_plain(ino)
        if ino.dl in (COMPRESSED_FULL, COMPRESSED_COMPACT):
            return self.read_compressed(ino)
        raise ErofsError("unsupported datalayout %d" % ino.dl)

    def read_dir(self, ino):
        data = self.read_plain(ino)
        entries = []
        off = 0
        while off < len(data):
            blen = min(BS, len(data) - off)
            chunk = data[off:off + blen]
            if blen < 12:
                break
            nameoff = u16(chunk, 8)
            if nameoff == 0 or nameoff % 12 or nameoff > blen:
                raise ErofsError("bad dir block at %d (nameoff=%d len=%d)" % (off, nameoff, blen))
            n = nameoff // 12
            for k in range(n):
                p = k * 12
                nid = u64(chunk, p)
                no = u16(chunk, p + 8)
                ftype = chunk[p + 10]
                end = u16(chunk, (k + 1) * 12 + 8) if k + 1 < n else blen
                if end < no:
                    end = blen
                name = chunk[no:end].rstrip(b"\0")
                entries.append((nid, ftype, name))
            off += blen
        return entries

    def walk(self, nid=None, path="/", max_depth=None, depth=0):
        if nid is None:
            nid = self.root_nid
        ino = self.inode(nid)
        if (ino.mode & 0o170000) != 0o040000:
            yield path, ino, None
            return
        if max_depth is not None and depth >= max_depth:
            yield path, ino, None
            return
        try:
            ents = self.read_dir(ino)
        except Exception as e:
            yield path, ino, "DIRERR: %s" % e
            return
        for cnid, ftype, name in ents:
            try:
                nm = name.decode("utf-8", "surrogateescape")
            except Exception:
                nm = repr(name)
            if nm in (".", ".."):
                continue
            cpath = path.rstrip("/") + "/" + nm
            try:
                cino = self.inode(cnid)
            except Exception as e:
                yield cpath, None, "INOERR: %s" % e
                continue
            if ftype == 2:
                for item in self.walk(cnid, cpath, max_depth, depth + 1):
                    yield item
            else:
                yield cpath, cino, None


def _lz4_lenient(comp, want):
    """LZ4 block decode that tolerates zero padding (EROFS LZ4_0PADDING)."""
    out = bytearray()
    i = 0
    n = len(comp)
    try:
        while i < n:
            token = comp[i]
            i += 1
            ll = token >> 4
            if ll == 15:
                while True:
                    b = comp[i]; i += 1
                    ll += b
                    if b != 255:
                        break
            if i + ll > n:
                break
            out += comp[i:i + ll]
            i += ll
            if i + 2 > n:
                break
            off = comp[i] | (comp[i + 1] << 8)
            i += 2
            if off == 0:
                break
            ml = (token & 15) + 4
            if (token & 15) == 15:
                while True:
                    b = comp[i]; i += 1
                    ml += b
                    if b != 255:
                        break
            start = len(out) - off
            if start < 0:
                break
            for _ in range(ml):
                out.append(out[start])
                start += 1
            if len(out) >= want:
                break
    except Exception:
        pass
    if len(out) < want:
        out += b"\0" * (want - len(out))
    return bytes(out)


# ------------------------------------------------------------------ containers
def iter_nested(data):
    """Yield (name, payload) for *compressed* entries inside a zip container
    (apk / apex / jar). Stored entries are skipped: they are already visible in
    the raw bytes of the outer file."""
    if data[:4] != b"PK\x03\x04":
        return
    import io, zipfile
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return
    try:
        for zi in zf.infolist():
            if zi.is_dir() or zi.file_size == 0:
                continue
            if zi.compress_type == zipfile.ZIP_STORED:
                continue
            if zi.file_size > 512 * 1024 * 1024:
                continue
            try:
                yield zi.filename, zf.read(zi)
            except Exception:
                continue
    finally:
        try:
            zf.close()
        except Exception:
            pass


def find_needles(data, needles, path, report):
    """Search raw bytes first, then deflate-compressed zip entries.
    report(label, offset, blob, needle) is called for every hit."""
    hits = 0
    for nd in needles:
        nb = nd if isinstance(nd, bytes) else nd.encode()
        st = 0
        while True:
            k = data.find(nb, st)
            if k < 0:
                break
            hits += 1
            report(path, k, data, nb)
            st = k + 1
    if hits:
        return hits
    for zname, payload in iter_nested(data):
        label = "%s!%s" % (path, zname)
        for nd in needles:
            nb = nd if isinstance(nd, bytes) else nd.encode()
            st = 0
            while True:
                k = payload.find(nb, st)
                if k < 0:
                    break
                hits += 1
                report(label, k, payload, nb)
                st = k + 1
    return hits


_REPORTED = [0]
REPORT_CAP = 400


def default_report(label, k, blob, nd):
    _REPORTED[0] += 1
    if _REPORTED[0] > REPORT_CAP:
        if _REPORTED[0] == REPORT_CAP + 1:
            print("... hit reporting capped at %d (counting continues) ..." % REPORT_CAP)
        return
    lo, hi = max(0, k - 400), min(len(blob), k + len(nd) + 400)
    ctx = blob[lo:hi].decode("utf-8", "replace").replace("\n", "\\n")
    print("HIT %s  off=%d  needle=%r" % (label, k, nd))
    print("    ...%s..." % ctx)


# ------------------------------------------------------------------ commands
def resolve(fs, path):
    cur = fs.root_nid
    for p in [x for x in path.split("/") if x]:
        ino = fs.inode(cur)
        found = None
        for nid, ftype, name in fs.read_dir(ino):
            if name.decode("utf-8", "replace") == p:
                found = nid
                break
        if found is None:
            raise SystemExit("no such path: %s" % path)
        cur = found
    return cur


def cmd_list(img, root="/", depth=None):
    fs = Erofs(img)
    print("EROFS blocks=%d inos=%d root_nid=%d incompat=%#x" %
          (fs.blocks, fs.inos, fs.root_nid, fs.feature_incompat))
    count = 0
    start = resolve(fs, root) if root != "/" else fs.root_nid
    for path, ino, err in fs.walk(start, path=root, max_depth=depth):
        count += 1
        if err:
            print("%-70s  ERR %s" % (path, err))
        elif count <= 400:
            print("%-70s  %s mode=%o size=%d dl=%d" %
                  (path, FT.get((ino.mode >> 12) & 15, "?"), ino.mode, ino.size, ino.dl))
    print("total entries:", count)


def search_fs(fs, needles, report=default_report, log_every=400):
    """Walk every regular file, search raw bytes then nested zip payloads."""
    hits = scanned = readfail = skipped = 0
    for path, ino, err in fs.walk():
        if err or ino is None:
            skipped += 1
            print("SKIP %-56s %s" % (path, err))
            continue
        if ((ino.mode >> 12) & 15) != 8:      # regular files only
            continue
        if ino.dl == CHUNK_BASED:
            skipped += 1
            print("SKIP %-56s chunk-based datalayout" % path)
            continue
        try:
            data = fs.read_file(ino)
        except Exception as e:
            readfail += 1
            print("READFAIL %-56s %s" % (path, e))
            continue
        scanned += 1
        hits += find_needles(data, needles, path, report)
        if log_every and scanned % log_every == 0:
            print("  ...scanned %d files (%d skipped, %d readfail)..." %
                  (scanned, skipped, readfail), file=sys.stderr)
    print("scanned %d regular files, %d hits, %d read failures, %d skipped" %
          (scanned, hits, readfail, skipped))
    return hits


def cmd_search(img, needles):
    fs = Erofs(img)
    return search_fs(fs, needles)


def cmd_extract(img, member, outpath):
    fs = Erofs(img)
    cur = fs.root_nid
    parts = [p for p in member.split("/") if p]
    for p in parts:
        ino = fs.inode(cur)
        found = None
        for nid, ftype, name in fs.read_dir(ino):
            if name.decode("utf-8", "replace") == p:
                found = nid
                break
        if found is None:
            raise SystemExit("not found: %s" % member)
        cur = found
    data = fs.read_file(fs.inode(cur))
    os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)
    with open(outpath, "wb") as f:
        f.write(data)
    print("wrote", outpath, len(data))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "/",
                 int(sys.argv[4]) if len(sys.argv) > 4 else None)
    elif cmd == "search":
        cmd_search(sys.argv[2], sys.argv[3:])
    elif cmd == "extract":
        cmd_extract(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        raise SystemExit("usage: erofs.py list|search|extract")