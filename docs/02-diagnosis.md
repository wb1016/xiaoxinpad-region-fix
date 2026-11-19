# 02 — Diagnosis: prove it is the region lock before touching anything

Two completely different failures produce "the tablet powers itself off with a
screen". They need opposite fixes, so always classify first.

| | A — region lock | B — AVB / verified boot |
|---|---|---|
| Screen | white + red bitmap | nothing (dead black, sometimes logo then nothing) |
| LK log line | `[Check_Region] 1427` or `1437` | `avb_slot_verify.c … Public key used to sign data rejected` + `ASSERT FAILED` |
| Fix | region patch / region-matching `dtbo` / official unlock | coherent `vbmeta` set, or unlock |
| This guide | yes | [09-troubleshooting.md](09-troubleshooting.md#avb) |

The distinction is invisible from outside — both look like "it just turns off".

## 2.1 Step 1 — recognise what the screen is made of

The sentence exists only as pixels:

* it is a BGRA bitmap (3200×1280×4 = 16,384,000 bytes) inside a zlib
  block inside the signed container of `logo.img` (file offset `0x369ebb` in
  the reference build);
* `logo.img` itself is signed (PKCS#7 trailer) → do not try to patch it;
* searching the firmware for `compatible with the hardware` returns 0 hits,
  always. That is expected. Do not conclude the message is generated at
  runtime — it isn't, and chasing that theory wastes an entire session.

Scripts: [`scripts/logo_parse.py`](../scripts/logo_parse.py),
[`scripts/logo_decode.py`](../scripts/logo_decode.py),
[`scripts/logo_render.py`](../scripts/logo_render.py) (needs Pillow).

```bash
python scripts/logo_parse.py  logo.img          # container + zlib stream map
python scripts/logo_decode.py logo.img          # decompress candidate offsets
python scripts/logo_render.py logo.img          # writes *_port / *_land PNGs
```

Read the rendered PNG — that gives you the *exact* wording of your unit's
message. Some Lenovo devices add a third line ("It can work normally after
flashing back to the factory version system."); the reference build has only
two.

## 2.2 Step 2 — get the LK log out of `expdb`

LK writes its decision to `expdb` (128 MB). The log lives in the tail region
`0x7E00000 … 0x8000000` (2 MB).

1. Read `expdb` with SP Flash Tool using the read-only config in
   [`configs/read_calibration.xml`](../configs/read_calibration.xml)
   (procedure: [05-flashing.md](05-flashing.md#reading)).
2. Extract the printable strings and grep the interesting markers:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dump_lk_log.ps1 `
    -Expdb expdb.bin -Out lk_boot_log.txt
```

`dump_lk_log.ps1` prints four sections for you:

* `[Check_Region]` lines — the decision trace (this is the answer),
* AVB / `ASSERT FAILED` / `HALT:` lines — the competing failure mode,
* a keyword sweep (`compatib`, `hardware`, `sku`, `reject`, `arb`, …),
* the last 60 lines of the log.

3. Split into boot cycles and classify the newest one:

```bash
python scripts/cycles.py lk_boot_log.txt        # per-cycle event summary
python scripts/s5_log_report.py new_log.txt old_log.txt
```

## 2.3 Step 3 — interpret the result

Region lock confirmed when you see:

```
[Check_Region]  1427: region is not update flag
```

or

```
[Check_Region]  1437: new region is not same
```

…repeatedly, with the white screen present.

* 1427 on a device that has never had a region change is the normal case.
  It means `region_state.update_flag != 1`, i.e. *no official region change is
  staged*. It fires before the actual region comparison.
* 1437 means the regions really differ and the `update_flag` gate was
  passed (only an official region-change does that).

Which one matters for the fix: the popular community LK image flips only
the 1437 branch. If your log says 1427, that image will not change
anything — you need the two-gate approach
([06-fix-options.md](06-fix-options.md#option-a), [07-lk-patching.md](07-lk-patching.md)).

AVB confirmed when you see (typically with no screen):

```
[AVB] invalid pubk size
avb_slot_verify.c:860: ERROR: vbmeta_a: Public key used to sign data rejected.
avb_ret = 5
ASSERT FAILED at (app/mt_boot/boot_info.c:181): g_boot_info.hdr_loaded
HALT: action = 0, reason = 9
```

In the reference log, 20 boot cycles split into two populations — 10 boots
that reached `decompress kernel image` and then died at `[Check_Region] 1427`,
and 10 that died in the AVB assert. Mixed populations are normal: the ring
buffer keeps only the most recent cycles. Classify the *newest* cycle, not
the oldest.

## 2.4 Step 4 — read the two region values (optional but conclusive)

Firmware side — what the flashed build claims:

```bash
python scripts/dtbo_regions.py dtbo.img     # every FDT, region-related props
python scripts/dtbo_parse.py   dtbo.img     # full property dump
python scripts/avb_desc.py     vbmeta.img vbmeta_system.img vbmeta_vendor.img
python scripts/vbmeta_dump.py  vbmeta.img dtbo.img proinfo.bin
```

You are looking for:

```
product_region node (dtbo):  country = ROW  province = ROW  city = ROW   ← firmware
```

Device side — what the hardware claims:

* `proinfo` carries `countrycode = CNXX` and the factory fingerprint
  (e.g. `Lenovo/<MODEL>_PRC/<MODEL>:15/...`). `region_scan.py` sweeps all
  dumps for these tokens:

```bash
python scripts/region_scan.py
```

If device = `CN/PRC` and firmware = `ROW`, the diagnosis is complete.

Note: the *stored* region itself lives in RPMB and appears in no dump —
[`scripts/hunt_region_state.py`](../scripts/hunt_region_state.py) proves that
by scanning every readable partition for the `region_state` magic
(`1a2b3c4d` / byte-reversed `4d3c2b1a`) and finding nothing.

```bash
python scripts/hunt_region_state.py '*.bin' '*.img'
```

## 2.5 Step 5 — write down your "before" state

Before writing anything, record:

1. `[Check_Region]` line number(s) present in the newest cycle (1427 / 1437),
2. AVB lines present or not,
3. `dtbo` `product_region` value,
4. `proinfo` country code,
5. current `lk_a`/`lk_b` contents (md5) — you will want them for rollback.

You will compare against this in [08-verify-and-rollback.md](08-verify-and-rollback.md).

Next: [03 — Root cause](03-root-cause.md).
