#!/usr/bin/env python3
r"""Build a TWO-GATE patched LK (reference build: TB336FU, ZUI 17.5.10.321).

**Portability note:** every offset and byte pattern below is specific to the
reference build. The script *proves* applicability before patching: it refuses
to run unless the stock bytes at each site match the expected ones. For any
other build, re-derive the two gates first (docs/07-lk-patching.md).

Why: the community/LPMBox image flips ONLY the 1437 gate at 0xaf7c, but a
device that has never been region-changed dies at the 1427 gate at 0xaf14
(update_flag != 1), which is UPSTREAM of it.  Static CFG (lk_region_cfg.py)
proves 0xaf14/0xaf9c have no other in-edges.

Patches (stock image, this build):
  0xaf14  41 04 00 54   b.ne #0xaf9c   ->  29 00 00 14   b   #0xafb8
  0xaf7c  e8 01 00 b4   cbz  x8,#0xafb8 ->  0f 00 00 14  b   #0xafb8   (community byte)

Both fatal blocks become unreachable; every path converges on 0xafb8:
  write_product_region_to_rpmb(build region) -> clean_update_flag -> return OK.

cert2 regeneration (mechanism verified by lk_cert_verify.py against BOTH the
stock and the community-patched image, source: LPMBox lk_cert_simulator.rs):
  header_sha = SHA-256(img[0x0000..0x0200])
  data_sha   = SHA-256(lk payload 0x200..0xe4370, zero-padded to 16B)
  cert2      = a0 58 | OID_HEADER | header_sha | OID_DATA | data_sha   (90 B)
             + original 995 B DER, section size 995 -> 1085, pad to 1088.

Output: patched/lk_patched_dual.img  (reference build: 2,909,184 B)
Fully verified below before it is written. Flashing stays a separate step.
"""
import hashlib, struct, sys, os
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

STOCK = r"image/lk.img"
COMMUNITY = r"patched/lk_patched_community.img"
OUT = r"patched/lk_patched_dual.img"

# Reference build identity (informational -- only warns, the per-site byte check
# below is the real applicability gate):
STOCK_SHA256 = "d6d4a269d722c1994b4efedad34e1e953273c2a979368d288050bda7b8a3c068"
STOCK_SIZE = 2_909_104
OID_HEADER = bytes.fromhex("060760867693160204032100")
OID_DATA = bytes.fromhex("060760867693160201032100")
MAGIC = bytes.fromhex("88168858")

PATCHES = {
    0xAF14: (bytes.fromhex("41040054"), bytes.fromhex("29000014")),  # b.ne -> b
    0xAF7C: (bytes.fromhex("e80100b4"), bytes.fromhex("0f000014")),  # cbz  -> b
}
DATA_SHA_OFFSET_IN_CERT2 = 2 + 12 + 32 + 12          # = 58 (a0 58 + OID_H + H + OID_D)

errors = []

def sha(b):
    return hashlib.sha256(b).digest()

def parse(raw):
    pos, secs = 0, []
    while pos < len(raw):
        if raw[pos:pos + 4] != MAGIC:
            if all(b == 0 for b in raw[pos:]):
                break
            errors.append("section header missing at %#x" % pos)
            break
        size = struct.unpack_from("<I", raw, pos + 4)[0]
        name = raw[pos + 8:pos + 40].split(b"\0")[0].decode("latin1")
        data = pos + 0x200
        end = data + size
        secs.append(dict(name=name, off=pos, size=size, data=data, end=end,
                         nxt=(end + 15) & ~15))
        pos = (end + 15) & ~15
    return secs

def pad16(b):
    return b + b"\x00" * (((len(b) + 15) & ~15) - len(b))

# ---------------- 1. stock checks ------------------------------------------
raw = open(STOCK, "rb").read()
print("STOCK   %d B  sha256=%s" % (len(raw), sha(raw).hex()))
if len(raw) != STOCK_SIZE or sha(raw).hex() != STOCK_SHA256:
    print("  [WARN] stock differs from the reference build "
          "(expected %d B / %s). The per-site byte check below decides "
          "whether this script's offsets apply." % (STOCK_SIZE, STOCK_SHA256))
secs = parse(raw)
if errors:
    print("\n".join(errors)); sys.exit(1)
lk = secs[0]
assert lk["name"] == "lk" and secs[1]["name"] == "cert1" and secs[2]["name"] == "cert2"
cert2_off, cert2_size = secs[2]["off"], secs[2]["size"]
cert2_data = secs[2]["data"]
print("  lk      payload %#x..%#x (%d)" % (lk["data"], lk["end"], lk["size"]))
print("  cert1   @%#x  %d B" % (secs[1]["off"], secs[1]["size"]))
print("  cert2   @%#x  %d B  data@%#x" % (cert2_off, cert2_size, cert2_data))
stock_der = raw[cert2_data:cert2_data + cert2_size]
assert stock_der[:2] in (b"\x30\x80", b"\x30\x81", b"\x30\x82", b"\x30\x83"), "not a DER SEQUENCE"

# ---------------- 2. apply code patches ------------------------------------
out = bytearray(raw)
for off in sorted(PATCHES):
    want, new = PATCHES[off]
    got = bytes(out[off:off + 4])
    if got != want:
        errors.append("stock bytes at %#x = %s, expected %s" % (off, got.hex(), want))
    out[off:off + 4] = new
if errors:
    print("\n".join(errors)); sys.exit(1)

# ---------------- 3. regenerate cert2 --------------------------------------
hdr_sha = sha(raw[0:0x200])
payload = bytes(out[lk["data"]:lk["end"]])
data_sha = sha(pad16(payload))
override = b"\xa0\x58" + OID_HEADER + hdr_sha + OID_DATA + data_sha
assert len(override) == 90, len(override)
new_cert2 = override + stock_der                      # 90 + original DER
padded = pad16(new_cert2)
print("  cert2   %d -> %d B (padded to %d)" %
      (cert2_size, len(new_cert2), len(padded)))

tail_off = cert2_off + 0x200 + ((cert2_size + 15) & ~15)
resized = bytearray()
resized += out[:cert2_off]                            # PATCHED code + cert1 ... up to cert2 header
resized += MAGIC                                      # cert2 header magic
resized += struct.pack("<I", len(new_cert2))          # size 995 -> 1085
resized += raw[cert2_off + 8:cert2_data]              # name + header pad (unchanged)
resized += padded                                     # new cert2 content
resized += raw[tail_off:]                             # everything after cert2 (unchanged)
out = bytes(resized)
print("\nBUILT   %d B  sha256=%s" % (len(out), sha(out).hex()))

# ---------------- 4. verify -------------------------------------------------
print("\n" + "=" * 96)
print("VERIFICATION")
print("=" * 96)
def check(label, cond, detail=""):
    print("  [%s] %s%s" % ("OK " if cond else "FAIL", label,
                           ("  -- " + detail) if detail else ""))
    if not cond:
        errors.append(label)

check("built size == stock + %d (the cert2 override)" % (len(out) - len(raw)),
      len(out) == len(raw) + (len(padded) - ((cert2_size + 15) & ~15)),
      "%d vs stock %d" % (len(out), len(raw)))

osecs = parse(out)
check("section names/order identical to stock",
      [s["name"] for s in osecs] == [s["name"] for s in secs])
HAVE_COMMUNITY = os.path.isfile(COMMUNITY)
if HAVE_COMMUNITY:
    check("section offsets/sizes identical to community layout",
          [(s["off"], s["size"], s["name"]) for s in osecs] ==
          [(s["off"], s["size"], s["name"]) for s in parse(open(COMMUNITY, "rb").read())])
else:
    print("  [skip] community image %s not present -- layout cross-check skipped" % COMMUNITY)

check("lk code section size unchanged", osecs[0]["size"] == lk["size"])
check("cert2 size %d -> %d" % (cert2_size, osecs[2]["size"]),
      osecs[2]["size"] == len(new_cert2), str(osecs[2]["size"]))
check("cert1 byte-identical", out[osecs[1]["data"]:osecs[1]["end"]] ==
      raw[secs[1]["data"]:secs[1]["end"]])
check("cert2 = 90B override + original DER",
      out[osecs[2]["data"]:osecs[2]["data"] + 90] == override and
      out[osecs[2]["data"] + 90:osecs[2]["data"] + 90 + len(stock_der)] == stock_der)
check("override starts a0 58", out[osecs[2]["data"]:osecs[2]["data"] + 2] == b"\xa0\x58")
check("header sha embedded correctly",
      out[osecs[2]["data"] + 2 + 12:osecs[2]["data"] + 2 + 44] == hdr_sha)
check("data sha embedded correctly (= SHA256 of NEW payload)",
      out[osecs[2]["data"] + 2 + 44 + 12:osecs[2]["data"] + 2 + 44 + 44] == data_sha)
check("recomputed data sha matches what we embedded",
      sha(pad16(out[osecs[0]["data"]:osecs[0]["end"]])) ==
      out[osecs[2]["data"] + 58:osecs[2]["data"] + 90])
check("lk header (0..0x200) untouched", out[0:0x200] == raw[0:0x200])

after_shift = osecs[2]["nxt"] - secs[2]["nxt"]
check("all sections after cert2 identical (shifted +%d)" % after_shift,
      out[osecs[2]["nxt"]:] == raw[secs[2]["nxt"]:])

# word-granularity diff inside the code payload (a 4-byte insn may share bytes)
code_word_diffs = [i for i in range(0, lk["end"], 4) if raw[i:i + 4] != out[i:i + 4]]
check("code diff sites exactly {0xaf14, 0xaf7c}",
      set(code_word_diffs) == {0xAF14, 0xAF7C},
      "diff words=%s" % [hex(i) for i in code_word_diffs])

# disassemble the two sites in the OUTPUT
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
print("\n  patched sites (disassembly of the built image):")
for a in sorted(PATCHES):
    ins = next(iter(md.disasm(out[a:a + 4], a)), None)
    print("    %#010x  %-16s %s" % (a, ins.mnemonic, ins.op_str))
    if ins.mnemonic != "b":
        errors.append("site %#x is not an unconditional b" % a)
    else:
        t = int(ins.op_str.strip("#"), 0)
        if t != 0xAFB8:
            errors.append("site %#x targets %#x, expected 0xafb8" % (a, t))

# community image comparison (optional -- needs the third-party image present)
com = open(COMMUNITY, "rb").read() if HAVE_COMMUNITY else None
if com is None:
    print("\n  [skip] community image not present -- byte-level diff skipped")
else:
    d2 = [i for i in range(min(len(out), len(com))) if out[i] != com[i]]
    print("\n  vs community image: %d differing bytes" % len(d2))
    # group into ranges
    ranges = []
    i = 0
    while i < len(d2):
        j = i
        while j + 1 < len(d2) and d2[j + 1] == d2[j] + 1:
            j += 1
        ranges.append((d2[i], d2[j] + 1))
        i = j + 1
    for lo, hi in ranges:
        print("    %#08x..%#08x (%d B)  ours=%s  community=%s"
              % (lo, hi, hi - lo, out[lo:hi].hex(" "), com[lo:hi].hex(" ")))
    digest_off = osecs[2]["data"] + DATA_SHA_OFFSET_IN_CERT2
    in_site = lambda lo, hi: (0xAF14 <= lo and hi <= 0xAF18) or \
                             (digest_off <= lo and hi <= digest_off + 32)
    check("only 0xaf14 and the 32B data-digest differ from the community image",
          all(in_site(lo, hi) for lo, hi in ranges) and
          any(lo == 0xAF14 for lo, hi in ranges) and
          any(lo == digest_off for lo, hi in ranges),
          "ranges=%s" % [(hex(a), hex(b)) for a, b in ranges])

print("\n" + "=" * 96)
if errors:
    print("FAILED (%d):" % len(errors))
    for e in errors:
        print("   - " + e)
    sys.exit(1)
print("ALL CHECKS PASSED -> writing %s" % OUT)
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
open(OUT, "wb").write(out)
import hashlib as _h
print("  md5    %s" % _h.md5(out).hexdigest().upper())
print("  sha256 %s" % sha(out).hex())
print("  %d bytes" % len(out))
print("""
Next (docs/05-flashing.md: start SP Flash Tool FIRST, then press Power):
  1. python prep_lk_patch.py --dual --apply --expect-sha256 <sha256 printed above>
  2. python preflight_dual.py --image image/lk_patched_dual.img \\
        --expect-sha256 <sha256 printed above>
  3. SPFlashToolV6.exe -c download -f image/download_agent/flash.xml -a da.auth
Rollback: python prep_lk_patch.py --stock --apply (points at image/lk.img, the
stock image of YOUR build -- always read your own lk_a back up first).""")