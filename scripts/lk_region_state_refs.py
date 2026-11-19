#!/usr/bin/env python3
"""Part 2:
  a) every load/store of region_state + 0x410 (the `update_flag` that gates line 1427)
  b) every BL caller of the region helpers (correct AArch64 imm26 sign handling)
  c) string xrefs for the unlock-region / region_state strings
Skew: file = T+0x200 if (adrp&0xFFF)>=0x200 else T-0xE00  (docs/07-lk-patching.md)
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

def dec(addr):
    for x in md.disasm(d[addr:addr + 4], addr):
        return x
    return None

def imm(tok):
    return int(tok.strip().lstrip("#"), 0)

def adrp_target(addr):
    i = dec(addr)
    if i is None or i.mnemonic != "adrp":
        return None
    rd = i.op_str.split(",")[0].strip()
    page = imm(i.op_str.split(", ")[1])
    addend = 0
    nxt = dec(addr + 4)
    if nxt and nxt.mnemonic == "add":
        p = [x.strip() for x in nxt.op_str.split(",")]
        if p[1] == rd and p[0] == rd:
            addend = imm(p[2])
    T = page + addend
    return T + 0x200 if (addr & 0xFFF) >= 0x200 else T - 0xE00

def func_start(addr):
    """walk back to the stp x29,x30 prologue"""
    for a in range(addr, max(TEXT_A, addr - 0x4000), -4):
        i = dec(a)
        if i and i.mnemonic == "stp" and i.op_str.startswith("x29, x30"):
            return a
    return None

# ---------- a) #0x410 accesses ---------------------------------------------
print("=" * 96)
print("A) every .text access to [reg, #0x410]  (region_state.update_flag)")
print("=" * 96)
for addr in range(TEXT_A, TEXT_B, 4):
    i = dec(addr)
    if i is None:
        continue
    if "#0x410]" in i.op_str:
        fs = func_start(addr)
        note = ""
        r = adrp_target(addr - 8) if dec(addr - 8) and dec(addr - 8).mnemonic == "adrp" else None
        print("  %#010x  %-30s   func@%s" % (addr, "%s %s" % (i.mnemonic, i.op_str),
                                              hex(fs) if fs else "?"))

# ---------- b) BL callers ---------------------------------------------------
print("\n" + "=" * 96)
print("B) BL callers of the region helpers")
print("=" * 96)

def bl_callers(target):
    hits = []
    for addr in range(TEXT_A, TEXT_B, 4):
        w = struct.unpack_from("<I", d, addr)[0]
        if (w & 0xFC000000) != 0x94000000:      # BL
            continue
        off = (w & 0x3FFFFFF) << 2
        if off & (1 << 27):
            off -= 1 << 28
        if addr + off == target:
            hits.append(addr)
    return hits

for t, name in ((0xa6d8, "read_new_region_for_unlock?"),
                (0xaa78, "clean_update_flag_set"),
                (0xa088, "write_product_region_to_rpmb"),
                (0x9fc8, "write_region_state_to_rpmb"),
                (0xa820, "read_region_state_from_rpmb"),
                (0xa930, "region_compare"),
                (0x9f24, "region_state_checksum"),
                (0xa590, "read_product_region_from_rpmb"),
                (0xa464, "read_build_region_from_vbmeta"),
                (0xa394, "read_boot_history_after_flush_lenovo_from_rpmb"),
                (0xa2c4, "read_unlock_op_history_from_rpmb"),
                (0x3a2e0, "rpmb_read(id,len?)"),
                (0x77644, "DRAW_ERROR_BITMAP")):
    hits = bl_callers(t)
    print("  %#08x %-46s <- %s" % (t, name, ", ".join("%#x(h=%s)" % (h, hex(func_start(h)) if func_start(h) else "?") for h in hits) or "NONE"))

# ---------- c) string xrefs -------------------------------------------------
print("\n" + "=" * 96)
print("C) xrefs to region/unlock strings (corrected skew)")
print("=" * 96)
NEEDLES = [
    b"oem unlock-region",
    b"[unlock_region] chage region fail",
    b"change region success",
    b"write_region_data_for_unlock",
    b"write_new_product_region_to_rpmb_for_unlock",
    b"region_state hash does not match",
    b"region_state hash is match",
    b"region is not update flag",
    b"new region is not same",
    b"region is not update",
    b"read_unlock_op_history",
    b"ldc region_msg is",
    b"Bootloader_SN not matched",
    b"MAGIC_NUM1 same",
    b"version does not match",
    b"sign verify fail",
    b"digest verify fail",
    b"wrong region length",
]
# pre-compute adrp targets for all of .text
adrp_map = {}
for addr in range(TEXT_A, TEXT_B, 4):
    i = dec(addr)
    if i and i.mnemonic == "adrp":
        t = adrp_target(addr)
        if t is not None:
            adrp_map.setdefault(t, []).append(addr)

for nd in NEEDLES:
    offs = [m.start() for m in re.finditer(re.escape(nd), d)]
    if not offs:
        print("  %-42s  NOT FOUND" % nd.decode())
        continue
    for off in offs:
        refs = adrp_map.get(off, []) + adrp_map.get(off - 1, [])
        loc = "; ".join("%#x(h=%s)" % (r, hex(func_start(r)) if func_start(r) else "?") for r in sorted(set(refs)))
        print("  @%#08x %-42s xref: %s" % (off, nd.decode()[:42], loc or "no adrp+add xref"))