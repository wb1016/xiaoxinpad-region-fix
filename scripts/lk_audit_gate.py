#!/usr/bin/env python3
"""Audit BEFORE building a two-gate LK patch.

1. edge audit: which instructions branch INTO the two fatal blocks / the gate?
2. what does read_region_state_from_rpmb (0xa820) actually validate?
   (if it only checks magic/checksum, clean_update_flag's extra
    [0x408]==0 / [0x40c]==1 test could still fail -> new failure mode 1447)
3. what does the magic check at 0xa224 do?
4. dump write_product_region_to_rpmb (0xa088) result handling.
Skew: file = T+0x200 if (adrp&0xFFF)>=0x200 else T-0xE00
"""
import re, struct, sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

P = sys.argv[1] if len(sys.argv) > 1 else r"image/lk.img"
d = open(P, "rb").read()
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
TEXT_A, TEXT_B = 0x230, 0x9A168

STR = {}
for m in re.finditer(rb"[\x20-\x7e]{4,}", d):
    STR[m.start()] = m.group().decode("latin1")

def dec(a):
    for x in md.disasm(d[a:a + 4], a):
        return x
    return None

def imm(t):
    return int(t.strip().lstrip("#"), 0)

def xref(a):
    i = dec(a)
    if i is None or i.mnemonic != "adrp":
        return None
    rd = i.op_str.split(",")[0].strip()
    page = imm(i.op_str.split(", ")[1])
    addend = 0
    n = dec(a + 4)
    if n and n.mnemonic == "add":
        p = [x.strip() for x in n.op_str.split(",")]
        if p[0] == rd and p[1] == rd:
            addend = imm(p[2])
    t = page + addend
    f = t + 0x200 if (a & 0xFFF) >= 0x200 else t - 0xE00
    return (f, STR.get(f) or STR.get(f - 1))

def dump(title, lo, hi):
    print("=" * 96)
    print(title)
    print("=" * 96)
    for a in range(lo, hi, 4):
        i = dec(a)
        t = ("%s %s" % (i.mnemonic, i.op_str)) if i else "??"
        note = ""
        r = xref(a)
        if r and r[1]:
            note = "   ; str@%#x %r" % (r[0], r[1][:88])
        if i and i.mnemonic == "mov" and ", #" in i.op_str:
            v = imm(i.op_str.split(", ")[1])
            if 0x100 <= v <= 0x800:
                note += "   ; possible line/tag %d" % v
        print("  %#010x  %-32s%s" % (a, t, note))
        if i and i.mnemonic == "ret":
            break

# ---- 1. branch edges -------------------------------------------------------
print("=" * 96)
print("1) branch edges into the gate / fatal blocks (BL/B.cond/CBZ/TBZ over .text)")
print("=" * 96)
WANT = {0xaf0c: "flag load (gate entry)", 0xaf14: "1427 gate b.ne",
        0xaf18: "post-gate (flag==1 path)", 0xaf80: "1437 fatal block",
        0xaf9c: "1427 fatal block", 0xafb8: "success write path",
        0xaec8: "success free/ret", 0xaeec: "strict-check entry"}
edges = {k: [] for k in WANT}
stats = {"B": 0, "BL": 0, "B.cond": 0, "CBZ": 0, "TBZ": 0}
for a in range(TEXT_A, TEXT_B, 4):
    w = struct.unpack_from("<I", d, a)[0]
    tgt = None
    if (w & 0xFC000000) == 0x14000000:                      # B
        off = (w & 0x3FFFFFF) << 2
        if off & (1 << 27):
            off -= 1 << 28
        tgt, stats["B"] = a + off, stats["B"] + 1
    elif (w & 0xFC000000) == 0x94000000:                    # BL
        off = (w & 0x3FFFFFF) << 2
        if off & (1 << 27):
            off -= 1 << 28
        tgt, stats["BL"] = a + off, stats["BL"] + 1
    elif (w & 0xFF000010) == 0x54000000:                    # B.cond / BC.cond
        off = ((w >> 5) & 0x7FFFF) << 2
        if off & (1 << 20):
            off -= 1 << 21
        tgt, stats["B.cond"] = a + off, stats["B.cond"] + 1
    elif (w & 0x7E000000) == 0x34000000:                    # CBZ/CBNZ
        off = ((w >> 5) & 0x7FFFF) << 2
        if off & (1 << 20):
            off -= 1 << 21
        tgt, stats["CBZ"] = a + off, stats["CBZ"] + 1
    elif (w & 0x7E000000) == 0x36000000:                    # TBZ/TBNZ
        off = ((w >> 5) & 0x3FFFF) << 2
        if off & (1 << 19):
            off -= 1 << 20
        tgt, stats["TBZ"] = a + off, stats["TBZ"] + 1
    if tgt in edges and a != tgt:
        edges[tgt].append(a)
print("scan covered .text %#x..%#x: %s" % (TEXT_A, TEXT_B, stats))
for k, label in WANT.items():
    src = ", ".join("%#x" % s for s in edges[k]) or "NONE"
    print("  %#08x %-26s <- %s" % (k, label, src))

# ---- 2/3/4. helper dumps ---------------------------------------------------
dump("2) read_region_state_from_rpmb  @0xa820", 0xa820, 0xa930)
dump("3) magic check  @0xa224", 0xa224, 0xa2c8)
dump("4) write_product_region_to_rpmb @0xa088 (result checked?)", 0xa088, 0xa1a8)

# ---- constants behind the magic compares -----------------------------------
print("=" * 96)
print("magic constants compared by 0x643f8 (memcmp) in clean_update_flag")
print("=" * 96)
for pc, add in ((0xab14, 0xaff34), (0xab30, 0x9fc11)):
    f = add + 0x200 if (pc & 0xFFF) >= 0x200 else add - 0xE00
    print("  @%#x -> file %#x : %s" % (pc, f, d[f:f + 16].hex(" ")))