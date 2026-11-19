#!/usr/bin/env python3
"""Split lk_boot_log.txt into boot cycles and report per-cycle events."""
import re, sys

P = sys.argv[1] if len(sys.argv) > 1 else r"lk_boot_log.txt"
lines = open(P, encoding="utf-8", errors="replace").read().splitlines()
print("lines:", len(lines))

MARKS = {
    "check_region": re.compile(r"\[Check_Region\]"),
    "vbmeta_key_reject": re.compile(r"Public key used to sign data rejected"),
    "avb_error": re.compile(r"avb_slot_verify.*ERROR"),
    "region_state": re.compile(r"region_state|new region|unlock_region|change region"),
    "notify_boot": re.compile(r"Notify boot linux"),
    "decompress": re.compile(r"decompress kernel image"),
    "red_state": re.compile(r"Device Cannot Boot|Repair Mode"),
    "compat": re.compile(r"not compatible|power off automatically"),
    "arb": re.compile(r"ARB process status"),
    "dtbo_auth": re.compile(r"dtbo.*auth|verify dtbo|dtb.*verif", re.I),
    "unlock": re.compile(r"unlock", re.I),
}

# cycle boundaries: LK restarts, look for a well-known early banner
starts = [i for i, l in enumerate(lines) if re.search(r"welcome to lk|LK ver|mt_boot|\[LK\]", l, re.I)]
print("candidate start markers:", len(starts))

events = {k: [] for k in MARKS}
for i, l in enumerate(lines):
    for k, rx in MARKS.items():
        if rx.search(l):
            events[k].append(i)

for k in MARKS:
    v = events[k]
    print("%-18s %4d  %s" % (k, len(v), [x + 1 for x in v[:25]]))

# correlation: for each vbmeta rejection, nearest notify_boot line after it
nb = events["notify_boot"]
dk = events["decompress"]
vr = events["vbmeta_key_reject"]
print("\n-- per vbmeta rejection --")
for x in vr:
    after = [n for n in nb if n > x]
    before = [n for n in nb if n < x]
    print("  reject@%d  prev_notify=%s  next_notify=%s" %
          (x + 1, (before[-1] + 1) if before else None,
           (after[0] + 1) if after else None))

print("\n-- notify_boot lines (cycle ends?) --", [x + 1 for x in nb])
print("-- decompress lines --", [x + 1 for x in dk])
print("-- Check_Region lines --", [x + 1 for x in events["check_region"]])

# print last 15 lines of file
print("\n-- tail --")
for l in lines[-15:]:
    print("   ", l)