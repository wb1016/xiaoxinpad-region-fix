#!/usr/bin/env python3
"""Multi-encoding / multi-needle hunt across a firmware image.

  python hunt.py file  <img>                    # raw EROFS image file
  python hunt.py super <super.img> <part|*>      # logical partition in super
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erofs import Erofs, search_fs, default_report
from super import open_super, get_part, _looks_like_fs

PHRASES = [
    "compatible with the hardware",
    "current system is not",
    "power off automatically",
    "will power off",
    "Enter Repair Mode",
    "Device Cannot Boot",
    "hardware mismatch",
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
        out.append(p.encode("utf-16-be"))
    # de-dup while keeping order
    seen, uniq = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def main():
    mode = sys.argv[1]
    ns = needles()
    total = 0
    if mode == "file":
        fs = Erofs(sys.argv[2])
        total += search_fs(fs, ns)
    elif mode == "super":
        sp, info = open_super(sys.argv[2])
        parts = [p[0] for p in info["partitions"]] if sys.argv[3] == "*" else [sys.argv[3]]
        for name in parts:
            lp = get_part(sp, info, name)
            if lp.size == 0:
                continue
            kind = _looks_like_fs(lp)
            if kind != "EROFS":
                print("skip %s (%r, %d bytes)" % (name, kind, lp.size))
                continue
            print("=== %s (%d bytes)" % (name, lp.size))
            total += search_fs(Erofs(lp), ns)
    print("TOTAL HITS:", total)


if __name__ == "__main__":
    main()