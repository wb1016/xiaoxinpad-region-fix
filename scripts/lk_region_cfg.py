#!/usr/bin/env python3
"""Full annotated CFG of region_check_main (0xac5c..0xafd4, reference build).

Answers the central open question *statically*:
  does the community 2-byte patch at 0xaf7c also bypass the 1427
  ("region is not update flag") fatal branch, or only 1437?

String xref correction (docs/07-lk-patching.md): payload runtime addr = file offset - 0x200,
so an adrp+add target T computed by capstone (which uses file-offset PCs) maps back
to a file offset as:
    file = T + 0x200   if (adrp_addr & 0xFFF) >= 0x200
    file = T - 0xE00   otherwise
Verified against known strings: 0xa8dc8 / 0x9c938.
"""
import re, sys, struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

STOCK = sys.argv[1] if len(sys.argv) > 1 else r"image/lk.img"
PATCH = sys.argv[2] if len(sys.argv) > 2 else r"patched/lk_patched_community.img"

a = open(STOCK, "rb").read()
b = open(PATCH, "rb").read()
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)

STR = {}
for m in re.finditer(rb"[\x20-\x7e]{4,}", a):
    STR[m.start()] = m.group().decode("latin1")

def dec(dat, addr):
    for x in md.disasm(dat[addr:addr + 4], addr):
        return x
    return None

def imm(tok):
    return int(tok.strip().lstrip("#"), 0)

def xref_str(dat, addr):
    """resolve adrp(+add) at addr -> (file_offset, string)"""
    i = dec(dat, addr)
    if i is None or i.mnemonic != "adrp":
        return None
    rd = i.op_str.split(",")[0].strip()
    page = imm(i.op_str.split(", ")[1])
    delta = page - addr                      # page - pc  (capstone space)
    addend = 0
    nxt = dec(dat, addr + 4)
    if nxt and nxt.mnemonic == "add":
        p = [x.strip() for x in nxt.op_str.split(",")]
        if p[1] == rd and p[0] == rd:
            addend = imm(p[2])
    T = page + addend
    file_off = T + 0x200 if (addr & 0xFFF) >= 0x200 else T - 0xE00
    s = STR.get(file_off) or STR.get(file_off - 1)
    return (file_off, s)

# ---- known addresses -------------------------------------------------------
KNOWN = {
    0xa464: "read_build_region_from_vbmeta (DT /product_region -> buf: country/city/province)",
    0xa590: "read_product_region_from_rpmb(x19)",
    0xa6d8: "?helper(x21) called only on the update-flag==1 path",
    0xa820: "read_region_state_from_rpmb(x22)",
    0xa930: "region_compare(x19 stored, x20 dt) -> w0 bit0",
    0xa088: "write_product_region_to_rpmb(x20)",
    0xaa78: "clean_update_flag / set-update-done",
    0x9f24: "region_state checksum build",
    0x9fc8: "write_region_state_to_rpmb(x22)",
    0x3c9a0: "pre-screen clear",
    0x77644: "*** DRAW WHITE/RED ERROR BITMAP ***",
    0x3cd10: "backlight MMIO 0xffff1c007008 <- 0x1971",
    0x6189c: "delay_us",
    0x1bba0: "power off",
    0x63390: "log_print(fmt, line, ...)",
    0x61f2c: "free",
    0x61dfc: "malloc(0x200)",
    0x61e80: "calloc(1,0x4a4)",
    0xad7c:  "log-and-cleanup tail (w1=source line, w2=ret)",
    0xad80:  "cleanup tail (free x19,x21,x20,x22 -> epilogue)",
    0xada0:  "*** FATAL TAIL: backlight on -> delay 10s -> backlight off -> power off ***",
    0xaec8:  "SUCCESS: free all -> ret",
    0xaf9c:  "*** FATAL 1427 (update flag != 1) ***",
    0xaf80:  "*** FATAL 1437 (new region != build region) ***",
    0xafb8:  "SUCCESS after region write: write_product_region + clean_update_flag",
}

LO, HI = 0xac40, 0xb000

def dump(title, dat, lo, hi, patch_site=None):
    print("=" * 100)
    print(title)
    print("=" * 100)
    for addr in range(lo, hi, 4):
        i = dec(dat, addr)
        txt = ("%s %s" % (i.mnemonic, i.op_str)) if i else "?? " + dat[addr:addr+4].hex()
        note = ""
        r = xref_str(dat, addr)
        if r and r[1]:
            note += "   ; str@%#x %r" % (r[0], r[1][:90])
        if i and i.mnemonic in ("b", "bl", "b.eq", "b.ne", "b.hi", "cbz", "cbnz", "tbz", "tbnz"):
            t = imm(i.op_str.split(",")[-1])
            if t in KNOWN:
                note += "   ; " + KNOWN[t]
        if i and i.mnemonic == "mov" and ", #" in i.op_str:
            v = imm(i.op_str.split(", ")[1])
            if v in (0x547, 0x551, 0x558, 0x56d, 0x57f, 0x584, 0x58e, 0x593, 0x59d, 0x5a7):
                note += "   ; [Check_Region] line %d" % v
        mark = " "
        if patch_site and addr == patch_site:
            mark = "*"
        print(" %s %#010x  %-34s %#010x%s" % (mark, addr, txt, int.from_bytes(dat[addr:addr+4], "little"), note))

print("### stock lk.img  md5-check bytes @0xaf78..0xaf84: %s" % a[0xaf78:0xaf88].hex(" "))
print("### patched       md5-check bytes @0xaf78..0xaf84: %s" % b[0xaf78:0xaf88].hex(" "))
print()
dump("region_check_main  (STOCK)", a, LO, HI, patch_site=0xaf7c)
print()
dump("region_check_main  (PATCHED) -- only 0xaf7c differs", b, LO, HI, patch_site=0xaf7c)

# ---- caller scan of the error-screen renderer ------------------------------
print("\n" + "=" * 100)
print("callers of 0x77644 (error bitmap) across .text")
print("=" * 100)
TEXT_A, TEXT_B = 0x230, 0x9a168
for addr in range(TEXT_A, TEXT_B, 4):
    w = struct.unpack_from("<I", a, addr)[0]
    if (w & 0xFC000000) != 0x94000000:      # bl imm26
        continue
    off = ((w & 0x3FFFFFF) << 2)
    if off & 0x8000000:
        off -= 0x100000000
    if addr + off == 0x77644:
        print("  bl 0x77644 from %#x" % addr)

# ---- helper functions that decide the path --------------------------------
print("\n" + "=" * 100)
print("helper: region_compare @0xa930  (which log line / strings does it use?)")
print("=" * 100)
for addr in range(0xa930, 0xaa80, 4):
    i = dec(a, addr)
    txt = ("%s %s" % (i.mnemonic, i.op_str)) if i else "??"
    note = ""
    r = xref_str(a, addr)
    if r and r[1]:
        note += "   ; str@%#x %r" % (r[0], r[1][:90])
    if i and i.mnemonic == "ret":
        print("  %#010x  ret" % addr)
        break
    print("  %#010x  %-32s%s" % (addr, txt, note))

print("\n" + "=" * 100)
print("helper: 0xa6d8 (called only when update_flag == 1)")
print("=" * 100)
for addr in range(0xa6d8, 0xa830, 4):
    i = dec(a, addr)
    txt = ("%s %s" % (i.mnemonic, i.op_str)) if i else "??"
    note = ""
    r = xref_str(a, addr)
    if r and r[1]:
        note += "   ; str@%#x %r" % (r[0], r[1][:90])
    if i and i.mnemonic == "ret":
        print("  %#010x  ret" % addr)
        break
    print("  %#010x  %-32s%s" % (addr, txt, note))

print("\n" + "=" * 100)
print("helper: 0xaa78 (clean_update_flag?)")
print("=" * 100)
for addr in range(0xaa78, 0xac5c, 4):
    i = dec(a, addr)
    txt = ("%s %s" % (i.mnemonic, i.op_str)) if i else "??"
    note = ""
    r = xref_str(a, addr)
    if r and r[1]:
        note += "   ; str@%#x %r" % (r[0], r[1][:90])
    if i and i.mnemonic == "ret":
        print("  %#010x  ret" % addr)
        break
    print("  %#010x  %-32s%s" % (addr, txt, note))

# ---- who calls 0xa6d8 / 0xa930 (is there an unlock-region path?) ----------
print("\n" + "=" * 100)
print("callers of 0xa6d8 / 0xaa78 / 0xa088 / 0x9fc8  (region write paths)")
print("=" * 100)
for target in (0xa6d8, 0xaa78, 0xa088, 0x9fc8, 0xa930):
    hits = []
    for addr in range(TEXT_A, TEXT_B, 4):
        w = struct.unpack_from("<I", a, addr)[0]
        if (w & 0xFC000000) != 0x94000000:
            continue
        off = (w & 0x3FFFFFF) << 2
        if off & 0x8000000:
            off -= 0x100000000
        if addr + off == target:
            hits.append(addr)
    print("  %#x <- %s" % (target, ", ".join("%#x" % h for h in hits) or "NONE"))