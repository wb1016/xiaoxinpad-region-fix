#!/usr/bin/env python3
"""Prepare (but do NOT execute) a write of a patched LK image to lk_a + lk_b.

Run from your work directory (see scripts/README.md).

  python prep_lk_patch.py                  # dry-run: report + assertions
  python prep_lk_patch.py --apply          # rewrite image/MT6835_Android_scatter.xml
  python prep_lk_patch.py --dual --apply   # stage the dual-gate image
  python prep_lk_patch.py --stock --apply  # ROLLBACK: re-point at stock lk.img
  python prep_lk_patch.py --src <file>     # stage an arbitrary image (your own build)
  python prep_lk_patch.py --expect-sha256 <hex>   # pin the exact bytes
  python prep_lk_patch.py --force          # accept a hash/size that does not match

What it does
------------
1. copies <source image> -> image/<staged name>
2. sets <is_download>true</is_download> for EXACTLY {lk_a, lk_b} and false for
   every other entry (this also clears any stale tick left by an earlier
   attempt -- a scatter still armed for `misc` is the classic foot-gun)
3. points those two entries' <file_name> at the staged image
4. asserts: source hash/size, image <= partition size, no encrypted .x/.t
   scatter next to the plaintext one, ticked set == intended set
5. mirrors the rewritten scatter to every other copy in the work dir so the DA
   cannot resolve a different partition set

Flash afterwards (see docs/05-flashing.md for the full timing procedure):
  SPFlashToolV6.exe -c download -f image/download_agent/flash.xml -a da.auth
"""
import hashlib, os, re, shutil, sys

HERE = os.getcwd()          # everything is relative to the work dir
SCATTER = os.path.join(HERE, "image", "MT6835_Android_scatter.xml")
# Extra copies of the scatter, kept "in case path resolution differs". They go
# stale silently (e.g. still armed for an old `misc` write) -- keep them in
# lockstep so no resolution ambiguity can ever pick a wrong partition set.
MIRRORS = [os.path.join(HERE, "MT6835_Android_scatter.xml")]

# Source selection:
#   default  : community image -- flips ONLY the 1437 gate at 0xaf7c. On a
#              device that dies at the 1427 gate (0xaf14, upstream of it) this
#              alone changes nothing, so only use it when your log says 1437.
#   --dual   : dual-gate image -- flips 0xaf14 AND 0xaf7c; both fatal blocks
#              become unreachable and every path converges on success
#              (built by lk_build_dualpatch.py).
#   --stock  : ROLLBACK -- the untouched stock lk.img from your own firmware.
MODE = "community (1437 only)"
DUAL = "--dual" in sys.argv
STOCK = "--stock" in sys.argv
FORCE = "--force" in sys.argv
APPLY = "--apply" in sys.argv

def argval(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and \
        sys.argv.index(flag) + 1 < len(sys.argv) else default

if STOCK:
    SRC = os.path.join(HERE, "image", "lk.img")
    OUT_NAME = "lk.img"
    MODE = "STOCK lk (rollback)"
elif DUAL:
    SRC = os.path.join(HERE, "patched", "lk_patched_dual.img")
    DST = os.path.join(HERE, "image", "lk_patched_dual.img")
    OUT_NAME = "lk_patched_dual.img"
    MODE = "DUAL-GATE (1427 + 1437)"
else:
    SRC = os.path.join(HERE, "patched", "lk_patched_community.img")
    DST = os.path.join(HERE, "image", "lk_patched.img")
    OUT_NAME = "lk_patched.img"
    MODE = "community (1437 only)"

if STOCK:
    DST = None                                  # stock image already lives in image/

# Optional overrides -- the pinned values below are only REFERENCE hashes for
# the specific build this project was developed against. For any other build,
# pass your own --expect-sha256 (recommended) or --force.
EXPECT_SHA256 = argval("--expect-sha256")
EXPECT_SIZE = int(argval("--expect-size", "0"))
if argval("--src"):
    SRC = argval("--src")
    if not DST:
        DST = os.path.join(HERE, "image", os.path.basename(SRC))
        OUT_NAME = os.path.basename(SRC)

INTENDED = {"lk_a", "lk_b"}

errors, notes, warns = [], [], []

# ---------- 1. image checks -------------------------------------------------
if not os.path.isfile(SRC):
    print("  [FAIL] source image not found: %s" % SRC)
    sys.exit(1)
blob = open(SRC, "rb").read()
md5 = hashlib.md5(blob).hexdigest().upper()
sha256 = hashlib.sha256(blob).hexdigest()
sz = len(blob)
notes.append("mode: %s" % MODE)
notes.append("source: %s  md5=%s  sha256=%s  %d bytes" % (SRC, md5, sha256, sz))

if EXPECT_SHA256 and sha256.lower() != EXPECT_SHA256.lower():
    msg = "source sha256 %s != pinned %s" % (sha256, EXPECT_SHA256)
    (warns if FORCE else errors).append(msg + ("" if FORCE else "  (or pass --force)"))
if EXPECT_SIZE and sz != EXPECT_SIZE:
    msg = "source size %d != pinned %d" % (sz, EXPECT_SIZE)
    (warns if FORCE else errors).append(msg + ("" if FORCE else "  (or pass --force)"))
if not EXPECT_SHA256:
    warns.append("no --expect-sha256 pin: verify yourself that this is the image "
                 "you built (see docs/07-lk-patching.md)")

# ---------- 2. scatter surgery ---------------------------------------------
xml = open(SCATTER, encoding="utf-8").read()

# split into partition_index blocks
blocks = list(re.finditer(r'<partition_index name="([^"]+)">(.*?)</partition_index>',
                          xml, re.S))
if not blocks:
    errors.append("no partition_index blocks found in scatter")

ticked_before, ticked_after = set(), set()
size_by_name = {}
for m in blocks:
    body = m.group(2)
    nm = re.search(r"<partition_name>([^<]+)</partition_name>", body)
    if not nm:
        continue
    name = nm.group(1)
    if "<is_download>true</is_download>" in body:
        ticked_before.add(name)
    ps = re.search(r"<partition_size>(0x[0-9a-fA-F]+)</partition_size>", body)
    if ps:
        size_by_name[name] = int(ps.group(1), 16)

for name in INTENDED:
    if name not in size_by_name:
        errors.append("partition %s missing from scatter" % name)
    elif sz > size_by_name.get(name, 0):
        errors.append("%s: image %d > partition %d" % (name, sz, size_by_name[name]))

# rewrite each partition block
def fix(m):
    body = m.group(2)
    nm = re.search(r"<partition_name>([^<]+)</partition_name>", body)
    name = nm.group(1) if nm else ""
    want = name in INTENDED
    body = re.sub(r"<is_download>(true|false)</is_download>",
                  "<is_download>%s</is_download>" % ("true" if want else "false"),
                  body, count=1)
    if want:
        body = re.sub(r"<file_name>[^<]*</file_name>",
                      "<file_name>%s</file_name>" % OUT_NAME, body, count=1)
        ticked_after.add(name)
    else:
        ticked_after.add(name) if False else None
    return '<partition_index name="%s">%s</partition_index>' % (m.group(1), body)

new_xml = re.sub(r'<partition_index name="([^"]+)">(.*?)</partition_index>',
                 fix, xml, flags=re.S)

final = set(re.findall(r'<partition_name>([^<]+)</partition_name>\s*'
                       r'<file_name>[^<]*</file_name>\s*'
                       r'<is_download>true</is_download>', new_xml))
if final != INTENDED:
    errors.append("ticked set %s != intended %s" % (sorted(final), sorted(INTENDED)))

# encrypted scatter must not be present where the tool looks
imgdir = os.path.join(HERE, "image")
bad = [f for f in os.listdir(imgdir) if re.search(r"\.(x|t)$", f, re.I)]
if bad:
    errors.append("encrypted scatter present in image/: %s" % bad)

notes.append("is_download before: %s" % sorted(ticked_before))
notes.append("is_download after : %s" % sorted(final))
notes.append("lk_a size=0x%x (%d MB), lk_b size=0x%x" %
             (size_by_name.get("lk_a", 0), size_by_name.get("lk_a", 0) // (1 << 20),
              size_by_name.get("lk_b", 0)))
import hashlib as _h
_sc_md5 = _h.md5(open(SCATTER, "rb").read()).hexdigest().upper()
for m in MIRRORS:
    if os.path.isfile(m):
        _m_md5 = _h.md5(open(m, "rb").read()).hexdigest().upper()
        notes.append("mirror %s md5=%s%s" %
                     (m, _m_md5[:16], "  (in sync)" if _m_md5 == _sc_md5 else
                      "  <-- STALE, will be rewritten by --apply"))
    else:
        notes.append("mirror %s (absent, will be created by --apply)" % m)

# ---------- report ----------------------------------------------------------
print("=" * 74)
for n in notes:
    print("  " + n)
print("-" * 74)
for w in warns:
    print("  [WARN] " + w)
for e in errors:
    print("  [FAIL] " + e)
if not errors:
    print("  all assertions passed")
print("=" * 74)

if errors:
    sys.exit(1)

if APPLY:
    if DST:
        shutil.copyfile(SRC, DST)
        print("APPLIED: wrote %s" % DST)
    open(SCATTER, "w", encoding="utf-8", newline="\n").write(new_xml)
    print("APPLIED: wrote %s" % SCATTER)
    for m in MIRRORS:
        if os.path.abspath(m) != os.path.abspath(SCATTER):
            open(m, "w", encoding="utf-8", newline="\n").write(new_xml)
            print("APPLIED: mirrored scatter -> %s" % m)
    print("\nNext (device must be attached -- full timing procedure in docs/05-flashing.md):")
    print("  SPFlashToolV6.exe -c download -f image/download_agent/flash.xml -a da.auth")
    print("Before flashing run:  python preflight_dual.py --image image/%s" % OUT_NAME)
else:
    print("dry-run only.  Re-run with --apply to stage file_name=%s into the scatter." % OUT_NAME)