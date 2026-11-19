# Xiaoxin Pad / Lenovo Tab "current system is not compatible with the hardware" — region-lock fix

Recovery documentation and analysis tooling for a family of Lenovo / ZUI MediaTek
tablets that show a white screen with red text and then power themselves off
before Android ever starts:

```
The current system is not compatible with the hardware.
The device will power off automatically.
```

This repository explains why that happens, why flashing firmware can never fix
it, and gives a step-by-step, verified procedure to recover the device, plus the
scripts used to reach those conclusions.

---

## Who this is for

You have a Lenovo/ZUI MediaTek tablet that:

* boots to the LENOVO logo, then shows the white/red screen above and powers off
  after ~10 s (no loop);
* shows the same screen with every firmware package, including the exact
  factory package, with the bootloader still locked and after a factory reset;
* never reaches Android, recovery still works (or the device can still be
  attached to SP Flash Tool).

Known-affected model family (same platform, same bootloader logic):

| Family | Models |
|---|---|
| TB335FC / TB336FU | Xiaoxin Pad 2025 / Lenovo Tab K11 Gen 2 (Wi-Fi) |
| TB365FC / TB361FU | same generation, region variants |
| TB375FC / TB373FU | same generation, region variants |

The reference device this documentation was written against is a TB336FU
(`sycamore_row_wifi`, MT6835V/ZA, UFS, A/B virtual A/B). The mechanism is
identical across the family; byte offsets are build-specific and every script
in this repo re-verifies them before acting (see [`docs/07-lk-patching.md`](docs/07-lk-patching.md)).

---

## Status

* Fixed and verified end-to-end. After the fix the device boots Android, and
  the system updater reports the build as "latest". The bootloader stayed
  locked, `dtbo`/`vbmeta`/`super`/`proinfo` were not touched, and all
  calibration backups were retained.

---

## The short version

1. Root cause: the bootloader (LK) compares the `product_region` stored in
   RPMB at factory time (PRC/CN on these units) with the `product_region`
   declared by the flashed firmware in `dtbo.img` (`ROW`). Mismatch → fatal
   path → bitmap screen → 10 s → power off.
   Details: [`docs/03-root-cause.md`](docs/03-root-cause.md).
2. You cannot flash your way out of it. RPMB is not writable by SP Flash
   Tool, and format-all does not touch it.
3. Diagnose before you touch anything — a second, unrelated failure mode
   (AVB rejecting `vbmeta`) looks identical from outside:
   [`docs/02-diagnosis.md`](docs/02-diagnosis.md).
4. Back up the calibration partitions first (one read-only cycle):
   [`docs/04-safety-and-backup.md`](docs/04-safety-and-backup.md).
5. Pick a fix — ranked options in [`docs/06-fix-options.md`](docs/06-fix-options.md);
   the one that fixed the reference device is a two-gate LK patch built by
   [`scripts/lk_build_dualpatch.py`](scripts/lk_build_dualpatch.py).

---

## Repository layout

```
docs/       step-by-step guides (read 01 → 10 in order the first time)
scripts/    analysis + staging scripts (Python 3, a few need capstone / Pillow)
configs/    SP Flash Tool console-mode read-only backup configuration
LEGAL.md    what is deliberately NOT included, and where to get it
```

Start here:

| # | Document | What it answers |
|---|---|---|
| 01 | [overview-and-symptom](docs/01-overview-and-symptom.md) | What the symptom is, and a map of the whole procedure |
| 02 | [diagnosis](docs/02-diagnosis.md) | How to *prove* this is the region lock (and not AVB) |
| 03 | [root-cause](docs/03-root-cause.md) | Why the device refuses to boot — full mechanism |
| 04 | [safety-and-backup](docs/04-safety-and-backup.md) | Hard rules, and the read-only backup pass |
| 05 | [flashing](docs/05-flashing.md) | SP Flash Tool console mode, timing, scatter discipline |
| 06 | [fix-options](docs/06-fix-options.md) | The ranked menu of fixes with trade-offs |
| 07 | [lk-patching](docs/07-lk-patching.md) | How the LK patch + `cert2` signature are built |
| 08 | [verify-and-rollback](docs/08-verify-and-rollback.md) | Proving it worked, and getting back |
| 09 | [troubleshooting](docs/09-troubleshooting.md) | Every failure mode we have seen, and what it means |
| 10 | [pitfalls](docs/10-pitfalls.md) | Wrong turns that cost days — so you don't repeat them |

---

## What this repo does not contain (on purpose)

* No firmware, no device dumps, no bootloader images. Those belong to their
  respective copyright holders (Lenovo/MediaTek) and/or are device-unique
  calibration data. You must supply your own, obtained from Lenovo's official
  support site for your model.
* No flashing tools. SP Flash Tool is MediaTek proprietary — obtain it from
  the official firmware package for your device.
* No third-party patched binaries. The community tool (LPMBox) is GPL-3 and
  linked from [`LEGAL.md`](LEGAL.md); read its source before using it.
* No device identifiers (serial numbers, calibration dumps, fingerprints of
  the reference unit), no local paths, no photos of the reference device.

See [`LEGAL.md`](LEGAL.md) for the full list and rationale.

## Requirements

* Windows PC with MTK USB drivers (SP Flash Tool is Windows-only here).
* Python 3.8+ for the scripts; `capstone` for the disassembly scripts,
  `Pillow` only for the `logo_*` image scripts (`pip install capstone pillow`).
* PowerShell 5+ for `dump_lk_log.ps1`.
* Patience: this procedure involves power-cycling the tablet at exactly the
  right moment, more than once.

## Licence

See [`LICENSE`](LICENSE) (CC0 1.0 for the original text and code in this
repository). Third-party names and trademarks belong to their owners; nothing
here is endorsed by them.
