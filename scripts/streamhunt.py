#!/usr/bin/env python3
"""Search arbitrary binary blobs, carving out embedded compressed streams
(gzip / lz4 frame / lz4 legacy / xz / zstd / bzip2) and nested zip entries.

  python streamhunt.py <file> [<file> ...]
"""
import sys, os, io, struct, zipfile, gzip, lzma, bz2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erofs import find_needles, default_report

try:
    import lz4.frame as lz4frame
    import lz4.block as lz4block
except Exception:
    lz4frame = lz4block = None

try:
    import zstandard as zstd
except Exception:
    zstd = None

PHRASES = [
    "compatible with the hardware",
    "power off automatically",
    "will power off",
    "Enter Repair Mode",
    "Device Cannot Boot",
    "current system is not",
    "TB336FU_PRC",
    "hwboardid",
    "component_id",
    "pcba_sku",
]


def needles():
    out = []
    for p in PHRASES:
        out.append(p.encode("utf-8"))
        out.append(p.encode("utf-16-le"))
    seen, uniq = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


SIGS = [
    (b"\x1f\x8b\x08", "gzip"),
    (b"\x04\x22\x4d\x18", "lz4frame"),
    (b"\x02\x21\x4c\x18", "lz4legacy"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"BZh", "bzip2"),
]


def lz4_auto(payload, lo=4096, hi=192 << 20):
    """LZ4 block-decompress when the output size is unknown.

    LZ4_decompress_safe errors when the destination is too small and returns
    the real size when it is big enough, so binary-search the capacity."""
    if lz4block is None or len(payload) < 4:
        return None

    def try_cap(cap):
        try:
            return lz4block.decompress(payload, uncompressed_size=cap)
        except Exception:
            return None

    hi = min(hi, max(lo, len(payload) * 255))
    best = try_cap(hi)
    if best is None:
        return None
    if len(best) <= lo:
        return best
    low, high, answer = lo, hi, best
    while low < high:
        mid = (low + high) // 2
        d = try_cap(mid)
        if d is None:
            low = mid + 1
        else:
            high = mid
            answer = d
    return answer


def lz4_legacy_decompress(data, limit=256 * 1024 * 1024):
    """LZ4 'legacy' ramdisk/kernel container: magic + u32 length + LZ4 block.
    Also tolerates the classic per-block-size legacy framing."""
    if len(data) < 8 or data[:4] != b"\x02\x21\x4c\x18":
        return b""
    n = struct.unpack_from("<I", data, 4)[0]
    # variant A: n == length of one raw LZ4 block that follows the header
    if 8 <= n <= len(data) - 8:
        blob = lz4_auto(data[8:8 + n])
        if blob:
            return blob
    # variant B: n is the max decompressed block size, blocks are length-prefixed
    blockmax = n
    if blockmax <= 0 or blockmax > (1 << 30):
        blockmax = 1 << 20
    pos, out = 8, bytearray()
    while pos + 4 <= len(data):
        sz = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if sz == 0 or sz > len(data):
            break
        chunk = data[pos:pos + sz]
        pos += sz
        if sz & 0x80000000:
            out += chunk
            continue
        if lz4block is None:
            break
        try:
            out += lz4block.decompress(chunk, uncompressed_size=blockmax)
        except Exception:
            d = lz4_auto(chunk)
            if d is None:
                break
            out += d
        if len(out) > limit:
            break
    return bytes(out)


LIMIT = 128 << 20


def _inflate(fn, data):
    """Run a streaming decompressor that stops at end-of-stream."""
    import zlib
    try:
        out = fn(data)
        return out if len(out) > 64 else b""
    except Exception:
        return b""


def _gzip(data):
    import zlib
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    return d.decompress(data, LIMIT)


def _xz(data):
    d = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    return d.decompress(data, LIMIT)


def _bz2(data):
    d = bz2.BZ2Decompressor()
    return d.decompress(data, LIMIT)


def decompress(kind, data):
    if kind == "gzip":
        return _inflate(_gzip, data)
    if kind == "xz":
        return _inflate(_xz, data)
    if kind == "bzip2":
        return _inflate(_bz2, data)
    if kind == "lz4legacy":
        blob = lz4_legacy_decompress(data)
        return blob if len(blob) > 64 else b""
    if kind == "lz4frame" and lz4frame is not None:
        try:
            blob = lz4frame.decompress(data, storage_size=64 << 20)
            return blob if len(blob) > 64 else b""
        except Exception:
            return b""
    if kind == "zstd" and zstd is not None:
        try:
            d = zstd.ZstdDecompressor().decompressobj()
            blob = d.decompress(data, LIMIT)
            return blob if len(blob) > 64 else b""
        except Exception:
            return b""
    return b""


def carve(label, data, ns, hits, depth=0, report=default_report, stats=None):
    hits[0] += find_needles(data, ns, label, report)
    if depth >= 4:
        return
    for sig, kind in SIGS:
        st = 0
        while True:
            k = data.find(sig, st)
            if k < 0:
                break
            st = k + 1
            blob = decompress(kind, data[k:])
            if len(blob) > 64:
                if stats is not None:
                    stats[kind] = stats.get(kind, 0) + 1
                    stats[kind + "_bytes"] = stats.get(kind + "_bytes", 0) + len(blob)
                carve("%s{%s@%d}" % (label, kind, k), blob, ns, hits,
                      depth + 1, report, stats)


def main():
    ns = needles()
    hits = [0]
    for path in sys.argv[1:]:
        with open(path, "rb") as f:
            data = f.read()
        stats = {}
        print("=== %s (%d bytes)" % (os.path.basename(path), len(data)))
        carve(os.path.basename(path), data, ns, hits, stats=stats)
        if stats:
            print("    carved:", {k: v for k, v in sorted(stats.items())})
        sys.stdout.flush()
    print("TOTAL HITS:", hits[0])


if __name__ == "__main__":
    main()