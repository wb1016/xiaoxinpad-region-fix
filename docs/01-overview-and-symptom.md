# 01 — Overview and symptom

## 1.1 What you see

```
LENOVO logo  →  white screen, red text:

   The current system is not compatible with the hardware.
   The device will power off automatically.

…then the tablet powers itself off after ~10 seconds.
```

Important properties of the symptom:

* It does not loop. One power-on = one attempt. The screen is shown once and
  the device turns off. There is no "try again" and no progress bar.
* It happens before Android. The screen is drawn by LK, the little
  AArch64 bootloader that runs before the kernel. Nothing you do inside Android,
  recovery, or `super`/`system` can influence it.
* It is independent of the firmware you flash. V build, W build, "exact
  factory" 47-file package — all show it, because the mismatched value is not in
  the firmware.
* A factory reset does not help (userdata is not involved).
* A bootloader unlock does not help by itself (the check runs on locked and
  unlocked devices alike).

A related screen that occasionally appears instead:

```
Device Cannot Boot. Enter Repair Mode.     ("Red State")
```

That is a *different* failure (AVB / verified-boot), see
[02-diagnosis.md](02-diagnosis.md).

## 1.2 What is actually going on (one paragraph)

Lenovo ships these tablets in a China (PRC) hardware configuration and the
same hardware also gets ROW (rest-of-world) firmware. LK — before booting
anything — reads a `product_region` record that the factory wrote into the
device's RPMB secure storage, and compares it against the `product_region`
declared by the firmware you just flashed (a device-tree property inside
`dtbo.img`). If they differ, LK treats the flash as a region change that was
never authorised, draws a pre-rendered error bitmap that ships inside
`logo.img`, waits 10 seconds, and powers the device off. RPMB cannot be written
by SP Flash Tool and is not cleared by a format, which is why *no* amount of
reflashing can satisfy the check. Full mechanism:
[03-root-cause.md](03-root-cause.md).

## 1.3 The procedure at a glance

```
        ┌─ 02 diagnosis ───────────────────────────────────────────┐
        │ read expdb → extract LK log → grep [Check_Region]        │
        │   1427/1437 + white screen  → region lock  (this guide)  │
        │   AVB "Public key … rejected", no screen → AVB problem   │
        └──────────────────────────────────────────────────────────┘
                              │
        ┌─ 04 backup (one read-only SPFT cycle) ───────────────────┐
        │ proinfo · nvram · nvcfg · nvdata · protect1/2 · otp ·    │
        │ efuse(RO) · dram_para · persist · metadata · bk1 · sec1 ·│
        │ preloader · misc · expdb · pstore                        │
        └──────────────────────────────────────────────────────────┘
                              │
        ┌─ 06 pick a fix ──────────────────────────────────────────┐
        │ A. dual-gate LK patch          ← fixed the reference unit│
        │ B. dtbo with matching region   ← no bootloader patch     │
        │ C. community tool (LPMBox)     ← orchestrates A/B        │
        │ D. official Lenovo unlock/region change                  │
        └──────────────────────────────────────────────────────────┘
                              │
        ┌─ 05 flash safely ────────────────────────────────────────┐
        │ stage scatter → preflight → tool first, then Power       │
        └──────────────────────────────────────────────────────────┘
                              │
        ┌─ 08 verify / keep a rollback ────────────────────────────┐
        │ re-read expdb, no [Check_Region] fatal line, updater OK  │
        └──────────────────────────────────────────────────────────┘
```

Never skip the diagnosis step (02) and never skip the backup step (04).
Both were, at different points, the reason earlier attempts failed.

## 1.4 Vocabulary

| Term | Meaning |
|---|---|
| LK | The AArch64 bootloader (MediaTek "lk" = little kernel). Decides whether to start the kernel; draws this error screen. |
| RPMB | Replay-Protected Memory Block — a hardware-authenticated area of the UFS/eMMC that only the *device* can write, with a rolling counter. Not reachable from SP Flash Tool. |
| `product_region` | A three-part string (`country` / `province` / `city`, e.g. `PRC`/`PRC`/`PRC` or `ROW`/`ROW`/`ROW`). Exists twice: in RPMB (device) and in `dtbo.img` (firmware). |
| `update_flag` | A flag inside `region_state` (RPMB, offset `0x410`) that says "a region change has been officially staged". Only Lenovo's signed `oem unlock-region` flow sets it. |
| scatter | The XML file that tells SP Flash Tool where each partition lives and which ones to write. |
| SPFT / DA | SP Flash Tool / Download Agent — the MediaTek flashing stack that talks to the preloader port. |
| `expdb` | A 128 MB diagnostic partition. Its last 2 MB contain the LK log — the only place where LK's decision is written down. |
| 1427 / 1437 | The two line numbers LK logs when it takes a fatal path out of its region check (`region is not update flag` / `new region is not same`). |

Next: [02 — Diagnosis](02-diagnosis.md).
