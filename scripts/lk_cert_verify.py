#!/usr/bin/env python3
"""Session 5: verify the cert2 digest mechanism revealed by LPMBox's GPL source
(crates/lpmbox-firmware/src/lk_cert_simulator.rs).

Claim:
  header_sha = SHA-256(lk.img[0x000 .. 0x200])          (512-byte MTK section header)
  data_sha   = SHA-256(section payload, zero-padded to 16-byte alignment)
  both digests are embedded in the `cert2` section after
      OID_HEADER = 06 07 60 86 76 93 16 02 04 03 21 00
      OID_DATA   = 06 07 60 86 76 93 16 02 01 03 21 00
  (patched image: 90-byte "Override" prefix a0 58 <the two OID+digest blocks>
   followed by the untouched original 995-byte DER; section size 995 -> 1085.)

If this holds for BOTH images, we can regenerate a valid cert2 for any code patch.
"""
import hashlib, struct, sys

STOCK = sys.argv[1] if len(sys.argv) > 1 else r"image/lk.img"
PATCH = sys.argv[2] if len(sys.argv) > 2 else r"patched/lk_patched_community.img"
LPMBOX_PINNED_STOCK_SHA256 = "d6d4a269d722c1994b4efedad34e1e953273c2a979368d288050bda7b8a3c068"
LPMBOX_PINNED_TRIAL_SHA256 = "61e80798dd4fe8cc490543b43ccc8dd009e4dd5e5ed677eb9cf754e801c2eae8"

OID_HEADER = bytes.fromhex("060760867693160204032100")
OID_DATA   = bytes.fromhex("060760867693160201032100")
MAGIC = bytes.fromhex("88168858")

def sha(b):
    return hashlib.sha256(b).digest()

def parse(raw, label):
    print("=" * 96)
    print("%s   %d bytes   sha256=%s" % (label, len(raw), sha(raw).hex()))
    print("  LPMBox pinned stock? %s   pinned trial? %s" %
          (sha(raw).hex() == LPMBOX_PINNED_STOCK_SHA256,
           sha(raw).hex() == LPMBOX_PINNED_TRIAL_SHA256))
    pos, secs = 0, []
    while pos < len(raw):
        if raw[pos:pos + 4] != MAGIC:
            if all(b == 0 for b in raw[pos:]):
                break
            print("  [!] header missing at %#x" % pos)
            break
        size = struct.unpack_from("<I", raw, pos + 4)[0]
        name = raw[pos + 8:pos + 40].split(b"\0")[0].decode("latin1")
        data = pos + 0x200
        end = data + size
        nxt = (end + 15) & ~15
        secs.append(dict(name=name, off=pos, size=size, data=data, end=end, nxt=nxt))
        pos = nxt
    for s in secs:
        print("   %-10s hdr@%#08x size=%-8d data %#08x..%#08x next=%#x" %
              (s["name"], s["off"], s["size"], s["data"], s["end"], s["nxt"]))
    return secs

def digests_in(buf):
    """(header_digest, data_digest) from the FIRST occurrence of each OID.

    Stock cert2: OIDs occur once (inside the DER).  Patched cert2: the 90-byte
    override prefix carries the *new* hashes first, the original DER (with the
    old hashes) follows at offset 90 -- so first-occurrence is the operative one.
    """
    h = d = None
    i = buf.find(OID_HEADER)
    if i >= 0:
        h = buf[i + 12:i + 44]
    j = buf.find(OID_DATA)
    if j >= 0:
        d = buf[j + 12:j + 44]
    return h, d

def analyze(path, label):
    raw = open(path, "rb").read()
    secs = parse(raw, label)
    out = {}
    # the lk group: first section named lk, then cert1, cert2
    idx = [k for k, s in enumerate(secs) if s["name"] == "lk"][0]
    code, c1, c2 = secs[idx], secs[idx + 1], secs[idx + 2]
    assert c1["name"] == "cert1" and c2["name"] == "cert2", (c1["name"], c2["name"])
    hdr_sha = sha(raw[0:0x200])
    payload = raw[code["data"]:code["end"]]
    pad = payload + b"\x00" * (((len(payload) + 15) & ~15) - len(payload))
    data_sha = sha(pad)
    cert2 = raw[c2["data"]:c2["end"]]
    found_h, found_d = digests_in(cert2)
    print("\n  -- lk section --")
    print("     header sha256[0..0x200]      = %s" % hdr_sha.hex())
    print("     data   sha256(payload pad16) = %s" % data_sha.hex())
    print("     cert2 size = %d, starts %s, first 96B:" % (c2["size"], cert2[:2].hex()))
    print("       %s" % cert2[:96].hex())
    print("     OID_HEADER digest = %s   match_header=%s" %
          (found_h.hex() if found_h else None, found_h == hdr_sha))
    print("     OID_DATA   digest = %s   match_data  =%s" %
          (found_d.hex() if found_d else None, found_d == data_sha))
    out.update(hdr_sha=hdr_sha, data_sha=data_sha, cert2=cert2, secs=secs, raw=raw,
               code=code, c2=c2, found_h=found_h, found_d=found_d)
    return out

print()
A = analyze(STOCK, "STOCK  image/lk.img")
print()
B = analyze(PATCH, "PATCHED patched/lk_patched_community.img")

print("\n" + "=" * 96)
print("structure comparison stock vs patched")
print("=" * 96)
print("  size delta               : %+d" % (len(B["raw"]) - len(A["raw"])))
print("  lk section size delta    : %+d  (code section should be identical in size)" %
      (B["code"]["size"] - A["code"]["size"]))
print("  cert2 size  %d -> %d  (%+d)" % (A["c2"]["size"], B["c2"]["size"],
                                         B["c2"]["size"] - A["c2"]["size"]))
ov = B["cert2"][:90]
rest = B["cert2"][90:]
print("  patched cert2 prefix(2)  = %s (expect a0 58)" % ov[:2].hex())
print("  patched cert2[90:] == stock cert2 ?  %s   (len %d vs %d)"
      % (rest[:A["c2"]["size"]] == A["cert2"], len(rest), A["c2"]["size"]))
print("  trailing pad after DER   : %r" % B["cert2"][90 + A["c2"]["size"]:][:16].hex())
print("  header bytes identical   : %s" % (A["raw"][0:0x200] == B["raw"][0:0x200]))
# everything after the lk-group cert2 should be byte-identical but shifted
shift = B["c2"]["nxt"] - A["c2"]["nxt"]
print("  shift after cert2        : %+d" % shift)
tail_a = A["raw"][A["c2"]["nxt"]:]
tail_b = B["raw"][B["c2"]["nxt"]:]
print("  all later sections identical: %s (%d vs %d bytes)" %
      (tail_a == tail_b, len(tail_a), len(tail_b)))

print("\n" + "=" * 96)
print("VERDICT")
print("=" * 96)
ok_stock = A["found_h"] == A["hdr_sha"] and A["found_d"] == A["data_sha"]
ok_patch = B["found_h"] == B["hdr_sha"] and B["found_d"] == B["data_sha"]
struct_ok = (ov[:2] == bytes.fromhex("a058") and
             rest[:A["c2"]["size"]] == A["cert2"] and
             B["c2"]["size"] - A["c2"]["size"] == 90 and
             A["raw"][0:0x200] == B["raw"][0:0x200] and tail_a == tail_b)
print("  stock   cert2 digests explained  : %s" % ok_stock)
print("  patched cert2 digests explained  : %s" % ok_patch)
print("  patched = 90B override + stock DER + size 995->1085 : %s" % struct_ok)
if ok_stock and ok_patch and struct_ok:
    print("\n  *** MECHANISM CONFIRMED - a valid cert2 can be regenerated for any patch ***")
    sys.exit(0)
else:
    print("\n  *** hypothesis failed - do not hand-patch ***")
    sys.exit(1)