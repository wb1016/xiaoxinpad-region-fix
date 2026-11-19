#!/usr/bin/env python3
"""Hunt for the region/countrycode evidence: vbmeta, dtbo, proinfo, lk."""
import re, sys, struct, os

def strings(data, n=4):
    return [(m.start(), m.group()) for m in re.finditer(rb"[\x20-\x7e]{%d,}" % n, data)]

KW = [b"region", b"country", b"CNXX", b"ROW", b"PRC", b"city", b"product_region",
      b"locale", b"operator", b"ro.product", b"hardware", b"board", b"sku", b"model"]

FILES = [
    r"vbmeta.img",
    r"vbmeta_system.img",
    r"vbmeta_vendor.img",
    r"dtbo.img",
    r"id_proinfo.bin",
    r"image/lk.img",
]

for p in FILES:
    if not os.path.exists(p):
        print("MISSING", p)
        continue
    d = open(p, "rb").read()
    print("=" * 72)
    print(os.path.basename(p), len(d))
    ss = strings(d, 4)
    print("  strings:", len(ss))
    hits = 0
    for off, s in ss:
        low = s.lower()
        if any(k.lower() in low for k in KW):
            print("   %#010x %s" % (off, s.decode()))
            hits += 1
        if hits > 400:
            print("   ...truncated")
            break
    sys.stdout.flush()

# proinfo: dump around CNXX occurrences
d = open(r"id_proinfo.bin", "rb").read()
print("=" * 72)
print("proinfo CNXX / countrycode context")
for nd in (b"CNXX", b"countrycode", b"COUNTRY", b"country", b"PRC", b"ROW"):
    st = 0
    while True:
        k = d.find(nd, st)
        if k < 0:
            break
        st = k + 1
        ctx = d[max(0, k - 64):k + 96]
        print("  %r @%#x: %r" % (nd, k, bytes(c if 32 <= c < 127 else 46 for c in ctx)))