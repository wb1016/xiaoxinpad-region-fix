#!/usr/bin/env python3
"""Session-5: compare the two expdb-derived LK logs and classify the NEWEST cycle.

  python s5_log_report.py lk_boot_log_s5.txt [lk_boot_log.txt]

Answers:
  * which log holds more/what changed (fresh expdb vs session-2 expdb)
  * is the LAST recorded cycle an AVB-assert death, a [Check_Region] 1427/1437
    death, or a boot that reached Linux?
"""
import re, sys

FILES = sys.argv[1:] or [r"lk_boot_log_s5.txt",
                         r"lk_boot_log.txt"]

MARKS = [
    ("region 1427",       r"\[Check_Region\]\s+1427"),
    ("region 1437",       r"\[Check_Region\]\s+1437"),
    ("region other",      r"\[Check_Region\](?!\s+(1427|1437))"),
    ("avb key rejected",  r"Public key used to sign data rejected"),
    ("avb invalid pubk",  r"\[AVB\] invalid pubk size"),
    ("ASSERT/HALT",       r"ASSERT FAILED|HALT:"),
    ("dtbo auth pass",    r"image dtbo auth pass"),
    ("notify_boot_linux", r"Notify boot linux"),
    ("decompress kernel", r"decompress kernel image"),
    ("red state",         r"Device Cannot Boot|Repair Mode"),
    ("region_state",      r"region_state|unlock_region|change region"),
    ("power-off msg",     r"power off automatically|not compatible with"),
]
RX = [(n, re.compile(p)) for n, p in MARKS]

for path in FILES:
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    print("=" * 100)
    print("%s  (%d lines)" % (path, len(lines)))
    print("=" * 100)
    hits = {}
    for name, rx in RX:
        idx = [i + 1 for i, l in enumerate(lines) if rx.search(l)]
        hits[name] = idx
        if idx:
            print("  %-19s n=%-4d first=#%-7d last=#%-7d" % (name, len(idx), idx[0], idx[-1]))
        else:
            print("  %-19s n=0" % name)

    # ---- classify the newest cycle -------------------------------------
    # The log is chronological.  Everything after the LAST AVB-death marker
    # (or from the start if none) is the newest population.
    last_avb = max([hits["avb key rejected"][-1] if hits["avb key rejected"] else 0,
                    hits["ASSERT/HALT"][-1] if hits["ASSERT/HALT"] else 0])
    tail = last_avb + 1
    print("\n  -- newest segment = lines after #%d (last AVB/HALT marker) --" % tail)
    seg = lines[tail:]
    if not seg:
        print("     (log ends at the AVB/HALT marker)")
        continue
    for name, _ in RX:
        n = sum(1 for l in seg if dict(RX)[name].search(l))
        if n:
            print("     %-19s in newest segment: %d" % (name, n))
    # first/last meaningful lines of the newest segment
    print("     segment length: %d lines" % len(seg))
    # find where the newest [Check_Region] sits
    r1427 = [tail + i + 1 for i, l in enumerate(seg) if re.search(r"\[Check_Region\]\s+1427", l)]
    r1437 = [tail + i + 1 for i, l in enumerate(seg) if re.search(r"\[Check_Region\]\s+1437", l)]
    print("     newest 1427 at line %s ; newest 1437 at %s" %
          (r1427[-1] if r1427 else "-", r1437[-1] if r1437 else "-"))
    print()
