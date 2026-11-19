# 06 — Fix options, ranked

All four options assume you have completed
[02 — diagnosis](02-diagnosis.md) and [04 — backup](04-safety-and-backup.md).

Pick one. Options A and B can be combined. Do not try two at once — you
lose the ability to tell which one worked.

---

## <a name="option-a"></a>Option A — patch LK at both gates  ← *fixed the reference unit*

Idea: make the two fatal branches unreachable, so LK always takes the
success path: `write_product_region_to_rpmb(build region)` →
`clean_update_flag()` → return OK.

```
0xaf14   41 04 00 54   b.ne #0xaf9c   →   29 00 00 14   b #0xafb8
0xaf7c   e8 01 00 b4   cbz  x8,#0xafb8 →  0f 00 00 14  b #0xafb8
```

Pros

* Minimal: 8 code bytes, `dtbo`/`vbmeta`/`super` stay coherent with the
  firmware's own region.
* Self-healing. After one good boot the RPMB region *is* the build's region,
  so even a stock LK boots afterwards. You can roll the bootloader back
  immediately if you prefer.
* Works regardless of what exactly is stored in RPMB (you don't need to know
  whether it is `PRC`, `CN`, or something else).

Cons / requirements

* The image must carry a regenerated `cert2`, or the bootloader rejects it
  before running any code → white screen again.
* Offsets are build-specific; you must re-derive them for another build
  ([07-lk-patching.md](07-lk-patching.md)).
* Needs SP Flash Tool + a working preloader window.

How

```bash
python scripts/lk_cert_verify.py      # prove the cert2 scheme on your images
python scripts/lk_build_dualpatch.py  # build + 16-way-verify the patched image
python scripts/prep_lk_patch.py --dual --apply --expect-sha256 <sha256>
python scripts/preflight_dual.py --image image/lk_patched_dual.img --expect-sha256 <sha256>
SPFlashToolV6.exe -c download -f image\download_agent\flash.xml -a da.auth
```

Details: [07-lk-patching.md](07-lk-patching.md). Rollback:
[08-verify-and-rollback.md](08-verify-and-rollback.md).

Gate check: only do Option A if your log shows 1427 or 1437 *and*
your build's stock bytes at `0xaf14`/`0xaf7c` match what the script expects.
If they don't, re-derive the gates first — never force a patch onto an
unverified image (`lk_build_dualpatch.py` refuses by itself).

---

## Option B — flash a `dtbo` whose region matches the device (no bootloader patch)

Idea: instead of making LK ignore the comparison, make the comparison
*succeed*. `dtbo.img` carries `product_region`; if the flashed value equals the
RPMB value, `region_compare` returns *same* and LK falls through to success with
a completely stock bootloader.

Community packages for this model family ship a PRC `dtbo_a`
(`country=PRC, province=PRC, city=PRC`) alongside the ROW one.

Pros

* No LK patch, no `cert2` regeneration.
* Cheap to try; one extra device cycle.
* LK's success path at `0xaec4` is the *healthy* path — no code is bypassed.

Cons

* Only works if the stored region is *exactly* `PRC`. If it is `CN`, `CNXX`, or
  anything else, `region_compare` still differs and you're back to 1427.
* You are putting a non-matching `dtbo` into a ROW build (kernel/DT property
  mismatch is possible in principle — on the reference family it boots).
* `dtbo` is authenticated by its own cert chain
  (`[SEC] dtbo cert chain vfy pass`), and `vbmeta*.img` of the reference build
  contain no HashPartition/Chain descriptor naming `dtbo` — so a genuine
  Lenovo PRC `dtbo` should pass. Treat this as *probable*, not proven.

How: arm `dtbo_a` for exactly one cycle (set `is_download=true` for `dtbo_a`
only, `file_name` = the PRC image) and flash with the same `-c download`
command. Verify with `preflight`-style assertions adapted to `dtbo_a`.

Order of attack used successfully: try A first (works for any stored
region), keep B as the fallback.

---

## Option C — community tool (LPMBox), "Device Recovery" mode

Idea: a GPL-3 tool that orchestrates the same artifacts for you.

* Source: <https://github.com/dwas-KR/LPMBox> — GPL-3, small — *read it
  before running it*; this repo does not redistribute the binary).
* For this model family it flashes `lk_a` + `dtbo_a` and hard-disables
  `lk_b`/`dtbo_b` (MT6835 policy in its source).
* Its `ReinstallWipe` ("기기 복구 / Device Recovery") mode runs entirely over
  PreLoader/SP Flash Tool — no fastboot, no ADB driver needed, and forces
  `preloader/efuse/misc/para/boot_para/metadata/proinfo` to stay off.
* Other modes: `CountryReset` (proinfo-only country-code change),
  `ConvertWipe` / `RowUpdateKeepData` (need a fastboot working device).

Before trusting it, check:

1. its pinned image hashes match the files you independently verified;
2. which partitions it actually ticks (read `patch_plan.rs` / `flash_plan.rs`);
3. that it never touches `efuse`/`preloader`.

Caveat that matters here: the image it ships for this family flips only
the 1437 gate. If your log says 1427, that alone will not fix your unit —
run it only if you combine it with a `dtbo` that matches (option B), or build
the two-gate image yourself (option A).

---

## Option D — official Lenovo route

If you need a *legitimate* region change/unlock anyway:

1. `fastboot getvar Bootloader_SN_Part1` + `Bootloader_SN_Part2`, concatenated =
   the 64-char bootloader serial (needs a working fastboot driver —
   installing one is a separate chore: Zadig/WinUSB or a Lenovo/MediaTek INF;
   the shell here needs elevation for driver installs).
2. <https://www.zui.com/iunlock> — enter tablet serial + the 64-char BL serial.
   Approval takes on the order of a day or two. Use a fresh email address and
   don't let the browser auto-translate the page (it breaks the form).
   Note: for some models you must use a *different* model's section of the form
   than the one named after your tablet; the TB336FU section asks for a legacy
   SN and fails.
3. Poll the returned URL for `sn.img` — it must be exactly 356 bytes and is
   device-specific (never share it, never use a generator: fake generators fail
   with `Info Auth failed!`).
4. `fastboot flash unlock sn.img`, then `fastboot oem unlock` in the same
   session, without a reboot in between; confirm on-device within 5 s with
   Vol+/Vol−. Verify: `fastboot getvar all` → `unlocked: yes`, `flash_lock: no`.
5. `fastboot oem unlock-region` then performs the *signed* region change — this
   is the only legitimate way to set `update_flag = 1`.

Root, if you want it afterwards: patch `init_boot` (not `boot`) with Magisk.

Why it is last in the list: it needs a working fastboot driver, a form
approval, and it does not help while the device still boots into the white
screen (fastboot is reachable, but the region check runs before Android and
before `unlock-region` would have any effect).

---

## Not worth doing

| Idea | Why not |
|---|---|
| Re-flash "known-good" / exact factory firmware | the mismatched value is in RPMB; [03-root-cause.md §3.3](03-root-cause.md#33-why-firmware-flashing-can-never-fix-it) |
| Format All / factory reset | doesn't touch RPMB; highest risk to calibration |
| Searching for the message text in the firmware | it is a bitmap inside a zlib block in `logo.img` — 0 hits always |
| Hand-editing `lk.img` without regenerating `cert2` | bootloader rejects the image before running it |
| Patching `logo.img` to hide the message | signed container; and the device still wouldn't boot |
| Unlocking the bootloader "to make it boot" | the check runs regardless of lock state |

---

## Decision flowchart

```
log shows 1427 or 1437, white screen present?
├── no  → different problem → 09-troubleshooting.md
└── yes
    ├── you can rebuild + verify an LK image
    │     └── Option A (two-gate)            ← recommended
    ├── you want no bootloader modification
    │     └── Option B (matching dtbo), if stored region == PRC
    ├── you want it orchestrated and you read the tool's source
    │     └── Option C (LPMBox) combined with B when your log says 1427
    └── you want it official / you need a real unlock
          └── Option D
```

Next: [07 — Building the LK patch](07-lk-patching.md).
