# Legal, licensing, and what is deliberately missing

## Licence of this repository

Unless stated otherwise, the original documentation and code in this repository
is released under CC0 1.0 Universal (see [`LICENSE`](LICENSE)) — public
domain dedication. Use it, copy it, modify it, publish it.

No warranty: flashing firmware and patching bootloaders can permanently destroy
a device. You do everything at your own risk.

## Trademarks

Lenovo, ZUI, Xiaoxin, MediaTek, SP Flash Tool, Magisk and Android are trademarks
of their respective owners. This project is not affiliated with, endorsed by, or
supported by any of them. Model names are used descriptively.

---

## What is NOT included, and why

| Not included | Why |
|---|---|
| Any firmware package or firmware image (`lk.img`, `dtbo.img`, `vbmeta*.img`, `super.img`, `logo.img`, `preloader`, …) | Copyrighted by Lenovo/MediaTek. Obtain them from Lenovo's official support site for your model. |
| Any patched bootloader image | A derivative of Lenovo's copyrighted bootloader. This repo gives you the script that builds it from your own copy instead (`scripts/lk_build_dualpatch.py`). |
| SP Flash Tool and its files (`SPFlashToolV6.exe`, `Qt5*.dll`, `console_mode.xsd`, `da.auth`, `DA_BR.bin`, `flash.xml`) | MediaTek proprietary; redistributing it is not allowed. It ships inside the official firmware package for your device — extract it from there. |
| Partition dumps / calibration data (`cal_*.bin`, `proinfo`, `nvram`, `expdb`, `lk_a` read-backs, …) | Device-unique, contain device identity and radio calibration. Publishing them would leak a specific device's identifiers and could be used to clone identity data. |
| Third-party patched binaries (e.g. the LPMBox release zip) | See below — GPL-3 source is linked, binary is not mirrored here. |
| Photos / video of the reference device | May contain identifying information on screen. |
| Device identifiers of the reference unit (serial numbers, bootloader SN, `sn.img`, MAC/IMEI, fingerprints of that unit, absolute local paths) | Personal/device data; `sn.img` in particular is device-specific and must never be shared. |

Nothing in this repository is encrypted or obfuscated; the omissions are
deliberate and listed here so you know exactly what you must supply yourself.

---

## Third-party software referenced (not redistributed)

### SP Flash Tool (MediaTek)

Proprietary. Comes in the official firmware package for your device. This repo
documents the command lines and XML configuration shapes only.

### LPMBox — community recovery tool

* Source: <https://github.com/dwas-KR/LPMBox> — GPL-3.0
* Licence obligations for the binary rest with whoever distributes it. This
  repository does not ship the binary or its bundled images; link, read the
  source, and build/obtain it yourself.
* Its published source is genuinely useful documentation: the `cert2`
  digest scheme described in [`docs/07-lk-patching.md`](docs/07-lk-patching.md)
  was first found there (`crates/lpmbox-firmware/src/lk_cert_simulator.rs`) and
  then independently verified against real images by
  [`scripts/lk_cert_verify.py`](scripts/lk_cert_verify.py).

### Android Verified Boot / AOSP formats

`avbtool`-format structures, FDT/`dt_table`, EROFS, `liblp` and sparse-image
layouts are documented in AOSP/kernel sources. The readers in `scripts/`
(`avb_desc.py`, `dtbo_parse.py`, `dtbo_regions.py`, `erofs.py`, `super.py`) were
written from those public specifications.

### Python dependencies

* `capstone` — BSD-3-Clause (disassembly)
* `Pillow` — MIT-CMU (PNG rendering of `logo.img` frames)

Both are only needed for optional scripts; install them yourself via pip.

---

## Where to get what you need

| You need | Get it from |
|---|---|
| Firmware package (incl. SP Flash Tool) | Lenovo official support / repair site for your model |
| MTK USB drivers | the same package, or Lenovo/MediaTek driver downloads |
| `sn.img` (official unlock) | `zui.com/iunlock` — device-specific, ~356 bytes, never shared |
| Community tool | the GPL repository linked above |
| The patched image | build it yourself: `python scripts/lk_build_dualpatch.py` |

---

## If you publish your own fork

Please keep this file, keep the omissions above (no firmware, no dumps, no
device identifiers), and consider contributing back anything you had to
re-derive — offsets for another build, a different gate layout, a working
driver recipe. The whole point of publishing this is that the next person with
the same white screen does not have to reverse-engineer it again.
