#!/usr/bin/env python3
"""Who sets region_state.update_flag = 1 (0x9e04 str w8,[x21,#0x410])?
That is the ONLY writer of 1 in .text -> the official region-change flow.
Dump the function, resolve strings, and find its callers."""
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

# find prologue: walk back from 0x9e04
start = None
for a in range(0x9e04, 0x9e04 - 0x800, -4):
    i = dec(a)
    if i and i.mnemonic == "stp" and i.op_str.startswith("x29, x30"):
        start = a
        break
print("function start: %s" % (hex(start) if start else "?"))

for a in range(start, start + 0x400, 4):
    i = dec(a)
    t = ("%s %s" % (i.mnemonic, i.op_str)) if i else "??"
    note = ""
    r = xref(a)
    if r and r[1]:
        note = "   ; str@%#x %r" % (r[0], r[1][:95])
    if i and i.mnemonic == "mov" and ", #" in i.op_str:
        v = imm(i.op_str.split(", ")[1])
        if 0x100 <= v <= 0x800:
            note += "   ; line %d" % v
    if a == 0x9E04:
        note = "   ; >>> SETS update_flag = " + (t.split(",")[-1].strip() if "," in t else "?")
    print("  %#010x  %-34s%s" % (a, t, note))
    if i and i.mnemonic == "ret" and a > start + 0x40:
        break

# callers of the function
def bl_callers(target):
    hits = []
    for a in range(TEXT_A, TEXT_B, 4):
        w = struct.unpack_from("<I", d, a)[0]
        if (w & 0xFC000000) != 0x94000000:
            continue
        off = (w & 0x3FFFFFF) << 2
        if off & (1 << 27):
            off -= 1 << 28
        if a + off == target:
            hits.append(a)
    return hits

print("\ncallers of %#x:" % start)
for h in bl_callers(start):
    print("  %#x" % h)

# also: who writes the flag=1 elsewhere (0x80a7c was a different struct)
print("\nall .text stores to [reg,#0x410] (re-check):")
for a in range(TEXT_A, TEXT_B, 4):
    i = dec(a)
    if i and i.mnemonic.startswith("str") and "#0x410]" in i.op_str:
        print("  %#010x  %s %s" % (a, i.mnemonic, i.op_str))