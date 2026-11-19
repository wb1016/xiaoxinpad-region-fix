#!/usr/bin/env python3
"""Parse AVB vbmeta images: header, algorithm, flags, and every descriptor
(partition names covered by hash/hashtree/chain descriptors).

Purpose: determine whether the `dtbo` partition is AVB-protected (decides if
flashing a foreign dtbo -- e.g. LPMBox's PRC dtbo_a -- would break AVB).
python avb_desc.py [vbmeta.img ...]"""
import struct, sys, os

FILES = sys.argv[1:] or [
    r"vbmeta.img",
    r"vbmeta_system.img",
    r"vbmeta_vendor.img",
]

ALG = {0: "NONE", 1: "SHA256_RSA2048", 2: "SHA256_RSA4096", 3: "SHA256_RSA8192",
       4: "SHA512_RSA2048", 5: "SHA512_RSA4096", 6: "SHA512_RSA8192"}
DT = {0: "Property", 1: "Hashtree", 2: "Hash", 3: "HashtreePartition",
      4: "HashPartition", 5: "KernelCmdline", 6: "ChainPartition",
      7: "Footer"}   # note: AVB descriptor types are 1-based in the spec

def cstr(b, o):
    e = b.find(b"\x00", o)
    return b[o:e].decode("latin1", "replace") if e >= 0 else ""

for path in FILES:
    if not os.path.isfile(path):
        print("missing", path)
        continue
    d = open(path, "rb").read()
    print("=" * 90)
    print("%s  (%d bytes)" % (path, len(d)))
    if d[:4] != b"AVB0":
        print("  NOT an AVB vbmeta (magic %r)" % d[:4])
        continue
    fmt = ">4s" + "I" * 15 + "Q" + "I" + "I"
    (magic, req_maj, req_min, auth_sz, aux_sz, alg, hash_off, hash_sz,
     sig_off, sig_sz, pk_off, pk_sz, pkmd_off, pkmd_sz, desc_off, desc_sz,
     roll, flags, roll_loc) = struct.unpack_from(fmt, d, 0)
    roll_max = 0
    print("  required_lib %d.%d  auth_block=%d aux_block=%d" % (req_maj, req_min, auth_sz, aux_sz))
    print("  algorithm=%s  hash=%d B  sig=%d B  pubkey=%d B" %
          (ALG.get(alg, alg), hash_sz, sig_sz, pk_sz))
    print("  rollback_index=%d  flags=%#x (%s)  rollback_loc=%d max=%d" %
          (roll, flags,
           "VERIFICATION DISABLED" if flags & 1 else ("hashtree disabled" if flags & 2 else "normal"),
           roll_loc, roll_max))
    print("  descriptors: offset=%#x size=%d" % (desc_off, desc_sz))
    base = 4096 + auth_sz          # auxiliary data block follows auth block
    # AVB: descriptors live in the auxiliary data block
    pos = base + desc_off
    end = base + desc_sz
    if desc_sz == 0:
        print("  (no descriptors)")
    while pos + 8 <= end and pos + 8 <= len(d):
        t, n = struct.unpack_from(">II", d, pos)
        if n < 8 or pos + n > len(d):
            print("  [stop] type=%d size=%d at %#x" % (t, n, pos))
            break
        body = d[pos + 8:pos + n]
        label = ""
        if t == 1 and len(body) >= 8:            # property
            klen, vlen = struct.unpack_from(">II", body, 0)
            k = cstr(body, 8)
            label = "key=%r value_len=%d" % (k, vlen)
        elif t == 5 and len(body) >= 16:         # hash partition
            pn, salt, digest, rsrv = struct.unpack_from(">IIII", body, 0)
            name = cstr(body, 16)
            label = "partition=%r salt=%d digest=%d B" % (name, salt, digest)
        elif t == 4 and len(body) >= 16:         # hashtree partition
            pn, salt, digest, rsrv = struct.unpack_from(">IIII", body, 0)
            name = cstr(body, 16)
            label = "partition=%r (hashtree) salt=%d digest=%d B" % (name, salt, digest)
        elif t == 6 and len(body) >= 8:          # chain partition
            pn, rsrv, sub = struct.unpack_from(">III", body, 0)
            name = cstr(body, 12)
            label = "partition=%r -> vbmeta_sub_index=%d" % (name, sub)
        elif t == 2 and len(body) >= 4:          # kernel cmdline
            label = "cmdline_len=%d" % struct.unpack_from(">I", body, 0)[0]
        print("    type=%-2d %-18s %s" % (t, DT.get(t, "?"), label))
        pos += n