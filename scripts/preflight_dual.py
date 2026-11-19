#!/usr/bin/env python3
"""Final pre-flight: everything the download agent (DA) will see before a write.

Run it from your work directory (see scripts/README.md) immediately before:

    SPFlashToolV6.exe -c download -f image/download_agent/flash.xml -a da.auth

Usage
-----
  python preflight_dual.py                       # defaults, no hash pinning
  python preflight_dual.py --image image/lk_patched_dual.img
  python preflight_dual.py --expect-sha256 <hex> # pin the exact image you built
  python preflight_dual.py --scatter <path>      # extra scatter copies to compare
  python preflight_dual.py --rollback <file>     # your own original lk dump

What it asserts (any FAIL => do not flash):
  * the staged image exists, and matches --expect-sha256 if given
  * EVERY copy of the scatter the DA could resolve is byte-identical, and ticks
    exactly {lk_a, lk_b} -> the staged image
  * no encrypted .x/.t scatter sits next to the plaintext one
  * image <= partition size for lk_a and lk_b
  * protected partitions (preloader, efuse, misc, para, userdata, proinfo,
    dtbo, super, vbmeta, boot) are all is_download=false
  * a rollback source is present
"""
import re, hashlib, os, sys

IMG = r"image/lk_patched_dual.img"
EXPECT_SHA256 = None
EXTRA = []
ROLLBACK = [r"image/lk.img", "lk_backup.bin"]

argv = sys.argv[1:]
while argv:
    a = argv.pop(0)
    if a == "--image" and argv:
        IMG = argv.pop(0)
    elif a == "--expect-sha256" and argv:
        EXPECT_SHA256 = argv.pop(0).lower()
    elif a == "--rollback" and argv:
        ROLLBACK = [argv.pop(0)]
    elif a == "--scatter" and argv:
        EXTRA.append(argv.pop(0))
    else:
        print("unknown argument:", a)
        sys.exit(2)

ok = True
def chk(label, cond, detail=""):
    global ok
    print("  [%s] %s%s" % ("OK " if cond else "FAIL", label,
                           ("  -- " + detail) if detail else ""))
    if not cond:
        ok = False

def note(label, detail=""):
    print("  [WARN] %s%s" % (label, ("  -- " + detail) if detail else ""))

# ---------- 1. staged image --------------------------------------------------
if not os.path.isfile(IMG):
    chk("staged image present: %s" % IMG, False, "MISSING")
    sys.exit(1)

b = open(IMG, "rb").read()
md5 = hashlib.md5(b).hexdigest().upper()
sha = hashlib.sha256(b).hexdigest()
print("  staged image  %s" % IMG)
print("                %d bytes  md5=%s" % (len(b), md5))
print("                sha256=%s" % sha)
if EXPECT_SHA256:
    chk("image sha256 matches --expect-sha256", sha == EXPECT_SHA256,
        "%s != %s" % (sha, EXPECT_SHA256))
else:
    note("no --expect-sha256 given", "cannot prove this is the image you built")

# ---------- 2. scatter copies ------------------------------------------------
paths = [r"image/MT6835_Android_scatter.xml",
         r"MT6835_Android_scatter.xml"] + EXTRA
paths = [p for p in dict.fromkeys(paths) if os.path.isfile(p)]
if not paths:
    chk("a scatter file was found", False, "looked in " + ", ".join(paths))
    sys.exit(1)

want_file = os.path.basename(IMG)
mds = []
for p in paths:
    d = open(p, encoding="utf-8").read()
    mds.append(hashlib.md5(d.encode()).hexdigest().upper())
    tick = set(re.findall(r"<partition_name>([^<]+)</partition_name>\s*"
                          r"<file_name>([^<]*)</file_name>\s*"
                          r"<is_download>true</is_download>", d))
    chk("%s ticks exactly lk_a+lk_b -> %s" % (p, want_file),
        tick == {("lk_a", want_file), ("lk_b", want_file)},
        "ticked=%s" % sorted(tick))
chk("all %d scatter copies byte-identical" % len(mds), len(set(mds)) == 1,
    " ".join(x[:8] for x in mds))

imgdir = os.path.dirname(paths[0]) or "."
bad = [f for f in os.listdir(imgdir) if re.search(r"\.(x|t)$", f, re.I)]
chk("no encrypted .x/.t scatter in %s/" % imgdir, not bad, str(bad))

# ---------- 3. partition entries --------------------------------------------
d = open(paths[0], encoding="utf-8").read()

def blocks(text):
    """yield (partition_name, block_body) -- note <partition_index name=..> holds a
    generic id (SYS0/SYS30/...); the real name is <partition_name> inside the block."""
    for m in re.finditer(r'<partition_index name="[^"]*">(.*?)</partition_index>', text, re.S):
        nm = re.search(r"<partition_name>([^<]+)</partition_name>", m.group(1))
        if nm:
            yield nm.group(1), m.group(1)

BLK = dict(blocks(d))
chk("scatter contains lk_a + lk_b entries", {"lk_a", "lk_b"} <= set(BLK),
    "found %d partition blocks" % len(BLK))

for name in ("lk_a", "lk_b"):
    body = BLK.get(name)
    if body is None:
        chk("%s entry present" % name, False)
        continue
    sz = int(re.search(r"<partition_size>(0x[0-9a-fA-F]+)</partition_size>", body).group(1), 16)
    dl = re.search(r"<is_download>(true|false)</is_download>", body).group(1)
    fn = re.search(r"<file_name>([^<]*)</file_name>", body).group(1)
    chk("%s: is_download=true, file=%s, image <= partition" % (name, want_file),
        dl == "true" and fn == want_file and sz >= len(b),
        "size=0x%x (%d MB) file=%s dl=%s" % (sz, sz >> 20, fn, dl))

# ---------- 4. protected partitions stay off --------------------------------
for name in ("preloader", "efuse", "misc", "para", "boot_para", "userdata", "proinfo",
             "dtbo_a", "dtbo_b", "super", "vbmeta", "vbmeta_system", "boot_a", "boot_b",
             "init_boot_a", "init_boot_b", "metadata", "lk3"):
    body = BLK.get(name)
    if body is None:
        continue
    dl = re.search(r"<is_download>(true|false)</is_download>", body).group(1)
    chk("%s stays is_download=false" % name, dl == "false", dl)

ticked = {nm for nm, body in BLK.items()
          if re.search(r"<is_download>true</is_download>", body)}
chk("exactly {lk_a,lk_b} ticked overall", ticked == {"lk_a", "lk_b"}, str(sorted(ticked)))

# ---------- 5. rollback source ----------------------------------------------
found_rb = None
for rb in ROLLBACK:
    if os.path.isfile(rb):
        found_rb = rb
        break
chk("rollback source present (%s)" % " | ".join(ROLLBACK), found_rb is not None,
    found_rb or "MISSING - read your own lk_a back before writing anything")

print()
print("ALL GREEN - ready to flash" if ok else "FAILURES PRESENT - do NOT flash")
sys.exit(0 if ok else 1)
