# 09 — Troubleshooting

Grouped by what you observe. Always start by re-reading `expdb`
([02-diagnosis.md §2.2](02-diagnosis.md#22-step-2--get-the-lk-log-out-of-expdb))
— the log tells you which of these you actually have.

---

## <a name="avb"></a>A. Device powers off with no screen

### A1 — AVB rejects `vbmeta`

```
[AVB] invalid pubk size
avb_slot_verify.c:860: ERROR: vbmeta_a: Public key used to sign data rejected.
avb_ret = 5
ASSERT FAILED at (app/mt_boot/boot_info.c:181): g_boot_info.hdr_loaded
HALT: action = 0, reason = 9
```

Meaning: verified boot failed *before* the region check. This is not the
white-screen problem and the region patch will not help.

Fix: restore a coherent `vbmeta*` set that matches the rest of the firmware
(same package, same build), or unlock and flash matching images. Check the
descriptors first:

```bash
python scripts/avb_desc.py vbmeta.img vbmeta_system.img vbmeta_vendor.img
```

Look for `HashPartition`/`ChainPartition` descriptors and whether the partition
you changed is covered.

### A2 — `ASSERT FAILED … g_boot_info.hdr_loaded`

The boot header was never loaded (an earlier step died). Scroll up in the log
for the actual first error; the assert is a consequence, not a cause.

### A3 — Powers off immediately, log ends mid-cycle

Likely a power/button issue or the download agent still running from a previous
session. Full power-cycle: unplug → hold Power 10 s → release → plug → press
Power once.

---

## B. White screen still there after flashing

| Log shows | Meaning | Fix |
|---|---|---|
| `[Check_Region] 1427` again | the image that was flashed either was not the dual-gate one, or its `cert2` was rejected so LK fell back / refused | verify what was actually written: re-read `lk_a` and md5 it against your built image; rebuild with `lk_build_dualpatch.py` and confirm all verification checks are green |
| `[Check_Region] 1437` now (was 1427) | progress — gate 1 was passed, gate 2 wasn't | make sure `0xaf7c` is patched too (dual-gate, not the community image) |
| `[Check_Region] 1422` | `read_region_state_from_rpmb` failed validation on your unit | the success path you unlocked would also fail (`clean_update_flag` re-validates the same fields) → do not rely on Option A; use Option B/C/D instead |
| `[Check_Region] 1447` | `clean_update_flag` returned an error | same as 1422: the RPMB record is not in a state the success path accepts → use Option B/C/D |
| no `[Check_Region]` at all | the check never ran (AVB death, or the tool flashed something else) | see section A, and verify the scatter tick set you flashed |

Verification steps when you suspect the wrong bytes were written:

```bash
# 1. what does the scatter say right now?
python scripts/prep_lk_patch.py            # dry run, prints before/after tick sets

# 2. what is actually on the device? (read lk_a back, read-only: add a
#    READ-PARTITION entry for lk_a to your read config, see configs/README.md)
SPFlashToolV6.exe -i read_calibration.xml

# 3. does it match what I built?
sha256sum lk_a.bin                          # compare with the build log output
```

---

## C. Flash tool problems

| Symptom | Cause | Fix |
|---|---|---|
| Tool spins, nothing found | no preloader window | start tool first, then unplug → hold Power 10 s → release → plug → press Power once |
| Device shows as `0e8d:2046` | `off-mode-charge=1` | press Power once to leave charging mode |
| Second run never connects | DA still running from the last session | full power-cycle before the next attempt |
| `No such node (brom.version)` | `conn_stage="brom"` | use `conn_stage="2nd DA"` |
| `flash list elements invalid` | used `WRITE-PARTITIONS` | use `-c download` (the only working write verb) |
| `Cannot find [x] on current device storage` | used `WRITE-FLASH` | use `-c download` |
| `Security deny [x] Signature(Entity) invalid` | partition refuses unsigned writes | don't fight it — pick a different route for that partition |
| exe exits instantly, `0xC0000135` | missing Qt DLLs | restore the tool's own DLL set (7 `Qt5*.dll`) |
| Stale partitions written | multiple scatter copies, only one updated | `prep_lk_patch.py` mirrors them; `preflight_dual.py` compares them |
| Encrypted scatter ignored / wrong one used | `.x`/`.t` next to the plaintext | move them away; the tool reads `image/MT6835_Android_scatter.xml` |

---

## D. Fastboot / driver problems

* Fastboot enumerates (`0e8d:201c`) but no driver (PnP error 28).
  Nothing in Options A/B/C needs fastboot. For Option D you need a real
  driver: Zadig (WinUSB) for the fastboot interface, or a Lenovo/MediaTek INF
  (driver installs require an elevated shell).
* Recovery exposes no ADB on this family — confirmed twice; don't test it
  again.
* Recovery entry: hold Vol UP + Vol DOWN, tap Power, keep holding.
  Fastboot entry: recovery → *Enter fastboot*.

---

## E. The screen looks different

| Screen | Meaning |
|---|---|
| `The current system is not compatible with the hardware.` | region lock (this guide) |
| `Device Cannot Boot. Enter Repair Mode.` ("Red State") | verified-boot / dm-verity class failure → coherent `vbmeta`/`boot` set |
| `Or, device will power off in %ds` | LK's generic countdown string — find which check logged it |
| Orange/Red/Yellow State text (small font, not a bitmap) | normal Android verified-boot warnings, drawn by a *text* renderer — different code path entirely |
| Boot animation with glitches, then nothing | kernel/userspace issue — not LK; check `pstore`, `dmesg` if you can get in |

---

## F. "It booted once, then it came back"

1. Was it an OTA? Check `Settings → about` incremental and whether `lk_a`
   changed (md5 your current `lk_a` against the image you flashed).
2. Re-read `expdb` and classify again — do not assume it is the same failure.
3. If `[Check_Region] 1427` is back, the region record is no longer consistent
   with the build (e.g. a different firmware region was flashed). Re-run the
   dual-gate fix for the build you are now on.

---

## G. When everything above says "fine" but it still doesn't boot

* Verify the *newest* expdb cycle, not older ones — the ring buffer rotates.
* Mixed populations are normal (some cycles die in AVB, others at the region
  gate); classify the last one.
* Confirm the tablet is actually the model/build you think: `proinfo`
  fingerprint vs the package you flashed
  (`python scripts/region_scan.py`).
* Confirm nothing else was silently written: compare pre/post md5s of
  `dtbo_a/b`, `vbmeta*`, `boot_a/b`, `super`, `proinfo`.
