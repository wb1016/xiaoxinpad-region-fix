# 07 — Building and verifying the patched LK

This is the technical core of Option A. Everything here was derived from, and
verified against, the reference build; the scripts refuse to run on a build
whose expected bytes do not match.

> **Legal/practical note:** you patch **your own** copy of an image obtained from
> Lenovo's official package for your device. This repository does **not**
> redistribute any patched or stock bootloader image.

---

## 7.1 The container

`lk.img` is a flat sequence of sections:

```
{ u32 magic 0x58881688, u32 size, char name[32], pad }  ← 0x200-byte header
      payload at header + 0x200
      next section at align16(header + 0x200 + size)
```

Reference layout (15 sections, in order):

```
lk (the AArch64 code)  →  cert1  →  cert2  →  bl2_ext  →  aee
→  lk_main_dtb  →  lk_dtbo  →  …  (rest byte-identical after any patch,
                                   shifted by the cert2 delta)
```

```bash
python scripts/lk_layout.py image/lk.img       # section map + ELF signatures
```

Runtime address vs file offset: **payload runtime address = file offset − 0x200**.

### String cross-reference skew (a real trap)

Disassembling with capstone at *file-offset* PCs gives an ADRP/ADR target `T`
that must be mapped back:

```
file = T + 0x200   if (T & 0xFFF) >= 0x200
file = T - 0xE00   otherwise
```

Get this wrong and every string reference looks like garbage (an early pass
produced "273 exact hits" that were pure coincidence — strings are dense).
With the correct skew **all 19 `[Check_Region]` format strings resolve**, e.g.

| computed | resolves to |
|---|---|
| `0xaf88 + 0xbc8` | `0xa8dc8` = `[Check_Region] %5d: new region is not same` |
| `0xafa4 + 0x738` | `0x9c938` = `[Check_Region] %5d: region is not update flag` |

(`BL`/`B` targets need no correction — they are PC-relative, the skew cancels.)

---

## 7.2 Step 1 — prove the diagnosis statically

```bash
python scripts/lk_region_cfg.py   image/lk.img patched/lk_patched_community.img
python scripts/lk_audit_gate.py   image/lk.img
python scripts/lk_region_state_refs.py image/lk.img
python scripts/lk_flag_writer.py  image/lk.img
```

What each proves:

| Script | Answer it gives |
|---|---|
| `lk_region_cfg.py` | full annotated CFG of `region_check_main` (`0xac5c..0xafd4`) — which line number each fatal block logs, and where every `[Check_Region]` string is used |
| `lk_audit_gate.py` | edge audit: `0xaf14`/`0xaf9c` have **no other in-edges**; `0xaf80` only via fallthrough; the screen renderer has exactly 2 callers (both fatal blocks) |
| `lk_region_state_refs.py` | every load/store of `region_state+0x410`, every `BL` caller of the region helpers, string xrefs |
| `lk_flag_writer.py` | the **only** `update_flag = 1` writer in `.text` (`0x9bc0`, signed official flow) |

> Re-run the edge audit rather than trusting a stored log: the first version of
> the auditor only counted `CBZ`/`TBZ` and missed `B`/`BL`/`B.cond`. The correct
> scan covers **5 branch classes, 30,127 branches**.

**The conclusion you are looking for:** the fatal block you are about to bypass
has no other entry points, so making its branch unconditional makes it
unreachable — and nothing else changes.

---

## 7.3 Step 2 — understand the signature (`cert2`)

The bootloader verifies `cert2` before running `lk` code. Mechanism (from the
GPL source of the community tool, **verified independently against both a stock
and a known-good patched image** by `lk_cert_verify.py`):

```
header_sha = SHA-256( img[0x0000 .. 0x0200] )              # 512-byte section header ONLY
data_sha   = SHA-256( lk payload, zero-padded to 16 bytes ) # NOT the raw length!

cert2 = a0 58
      | 06 07 60 86 76 93 16 02 04 03 21 00 | header_sha      (OID_HEADER)
      | 06 07 60 86 76 93 16 02 01 03 21 00 | data_sha        (OID_DATA)
      + original DER (995 B on the reference build)
      → size field 995 → 1085, pad to 1088   (+80 bytes total)
```

`cert1` is untouched; everything after `cert2` is byte-identical but shifted by
the size delta.

Why attempts to "solve" the digests fail if you get this wrong:

* hashing the **whole file** instead of the 512-byte header;
* hashing the payload at its **raw length** instead of **16-byte zero-padded**;
* hashing an arbitrary range and hoping.

```bash
python scripts/lk_cert_verify.py image/lk.img patched/lk_patched_community.img
```

Expected output: both embedded digests reproduce exactly for the stock image
(`header_sha`, `data_sha`), and the patched image's `data_sha` equals the
SHA-256 of *its* patched payload. When both are green, you can generate a valid
`cert2` for any code patch you make.

---

## 7.4 Step 3 — apply the two patches

```python
0xaf14   41 04 00 54   b.ne #0xaf9c    →   29 00 00 14   b #0xafb8
0xaf7c   e8 01 00 b4   cbz  x8,#0xafb8 →   0f 00 00 14   b #0xafb8
```

Both become unconditional branches to the success path `0xafb8`:

```
0xafb8   write_product_region_to_rpmb(build region)
         clean_update_flag()
         return OK
```

Semantics of each change:

| Site | Was | Now |
|---|---|---|
| `0xaf14` | "no official region change staged" → 1427 fatal block | skip the check entirely |
| `0xaf7c` | "staged region ≠ build region" → 1437 fatal block | skip the check entirely |

Everything else — the RPMB read, the validation, the actual region write — still
happens normally. We are not disabling the code path, we are *selecting* it.

---

## 7.5 Step 4 — build

```bash
python scripts/lk_build_dualpatch.py
python scripts/lk_build_dualpatch.py <stock.img> <community.img>   # explicit paths
```

The script:

1. parses the container and asserts `lk`/`cert1`/`cert2` are the first three
   sections;
2. **asserts the stock bytes at every patch site** — if they differ, this is a
   different build and it stops (this is the portability guarantee);
3. applies the two 4-byte patches;
4. recomputes `header_sha` over the **original** header (unchanged by the patch)
   and `data_sha` over the **patched**, 16-byte-padded payload;
5. rebuilds `cert2` = 90-byte override + original DER, updates the size field,
   and re-emits every later section unchanged;
6. runs a verification battery (16 checks) and only then writes the output.

### Verification battery (what "green" means)

* built size == stock + (new cert2 − old cert2, 16-aligned);
* section names/order identical to stock; `lk` code section size unchanged;
* `cert1` byte-identical; everything after `cert2` byte-identical;
* `cert2` = 90-byte override + the original DER, override starts `a0 58`;
* the embedded `header_sha` is correct, and the embedded `data_sha` equals
  `SHA-256(pad16(payload))` **recomputed from the final file**;
* `img[0..0x200]` untouched;
* the code diff is exactly `{0xaf14, 0xaf7c}` — nothing else moved;
* both patched sites **disassemble** to `b #0xafb8` (not just "bytes changed");
* (if a community image is present) the only differences vs it are `0xaf14`
  and the 32-byte data digest.

Only if **all** checks pass does the script write the output. Keep the printed
sha256 — you will pin it in the next steps.

---

## 7.6 Step 5 — stage and pre-flight

```bash
python scripts/prep_lk_patch.py --dual --apply --expect-sha256 <printed sha256>
python scripts/preflight_dual.py --image image/lk_patched_dual.img \
        --expect-sha256 <printed sha256>
```

* `prep_lk_patch.py` copies the image into `image/`, rewrites the scatter so
  **exactly** `lk_a` and `lk_b` are ticked (clearing stale ticks), mirrors the
  scatter to every other copy, and asserts sizes/fit/absence of encrypted
  scatters. Run it **without** `--apply` first and read the before/after tick
  sets.
* `preflight_dual.py` re-checks what the DA will actually see and prints
  `ALL GREEN - ready to flash`.

Then flash — [05-flashing.md §5.5](05-flashing.md#55-writing-the-full-sequence).

---

## 7.7 If you must port to another build

1. Extract `lk.img` from *your* firmware package.
2. Run `lk_layout.py` → confirm the same container shape.
3. Locate `region_check_main`: find the `[Check_Region]` format strings
   (apply the §7.1 skew), then follow the references into the code. The two
   fatal blocks are the ones that call the screen renderer — find the renderer
   first (it is called from exactly two places), then look at the two branches
   that lead there.
4. Confirm with `lk_audit_gate.py` that each branch has no other in-edges.
5. Confirm the expected stock bytes, then edit `PATCHES` in
   `lk_build_dualpatch.py`.
6. Re-run `lk_cert_verify.py` on *your* stock image first — the cert2 scheme is
   expected to be the same, but **prove it on your bytes** before trusting it.
7. Re-run the full build verification.

Do **not** skip 4–6. A patch to the wrong branch, or a cert2 built with a wrong
digest range, both end in the same symptom you started with.

---

## 7.8 Common build-time mistakes

| Mistake | Symptom |
|---|---|
| Patch only `0xaf7c` | identical white screen (log still 1427) |
| Patch `0xaf14` but forget `0xaf7c` | works only if the staged region happens to match; otherwise 1437 |
| Wrong hash range in `cert2` | device shows the screen again, log still 1427 → cert rejected |
| Edit the code but keep the old `cert2` | same as above |
| Patch a different build's offsets without checking | `lk_build_dualpatch.py` stops on the byte check — **that is intended**, don't override it |
| Flash the right image but leave a stale scatter ticked | a *different* partition gets written (see [05-flashing.md §5.6](05-flashing.md)) |

Next: [08 — Verify and rollback](08-verify-and-rollback.md).
