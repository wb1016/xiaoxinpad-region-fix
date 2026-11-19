# 08 — Verifying the fix, and rolling back

## 8.1 Immediate signs of success

After the flash completes (tool reports `lk_a` + `lk_b` downloaded, then
`CMD:REBOOT IMMEDIATE`):

1. the tablet restarts without you touching anything;
2. the LENOVO logo → boot animation (the white/red screen does not appear);
3. Android finishes first boot (if `userdata` was wiped, the setup wizard);
4. Settings → system updater reports the build as "latest" — this was the
   final acceptance check on the reference unit.

If the boot animation never appears, go to
[09-troubleshooting.md](09-troubleshooting.md) — do not re-flash blindly.

---

## 8.2 Proof, not vibes: re-read `expdb`

The device state is only trustworthy if the LK log says so.

1. Read `expdb` again (read-only config,
   [05-flashing.md §5.4](05-flashing.md#reading)).
2. Extract and inspect:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dump_lk_log.ps1 `
    -Expdb expdb.bin -Out lk_boot_log_after.txt
```

```bash
python scripts/cycles.py lk_boot_log_after.txt
python scripts/s5_log_report.py lk_boot_log_after.txt lk_boot_log_before.txt
```

### Pass criteria

| Check | Before | After |
|---|---|---|
| `[Check_Region] 1427` in the newest cycle | present (×11) | absent |
| `[Check_Region] 1437` | absent | absent |
| `decompress kernel image` / `dtbo auth pass` | reached, then died | reached |
| `notify_boot_linux` / `Notify boot linux` | not in newest cycles | present |
| AVB `Public key … rejected` | present in older cycles | absent in newest |

Or simply: the device boots and stays up. A log without a new fatal
`[Check_Region]` line is the confirmation; the screen being gone is the
consequence.

### Extra confirmations

* `dtbo`, `vbmeta`, `super`, `proinfo` unchanged (md5 them against your
  pre-fix records — Option A must not touch them);
* bootloader lock state unchanged (`unlocked: no` if you never unlocked);
* `proinfo` country code still `CNXX` — the *device* identity was not rewritten;
  what changed is that LK wrote the build region into RPMB, making the two
  agree.

---

## 8.3 Why the state is now stable (and what "rollback" really means)

After the first successful boot LK executed:

```
write_product_region_to_rpmb(build region)   ← RPMB now says ROW
clean_update_flag()                          ← flag cleared
```

So `stored_region == build_region` persistently. From now on:

* an unpatched stock LK takes the `region_compare == same` path at `0xaec4`
  and boots normally;
* re-flashing the stock `lk_a`/`lk_b` is therefore *safe* — and is the cleanest
  way to return to a fully stock bootloader if you want that.

You can prove this with one extra device cycle: flash the stock image
(`python scripts/prep_lk_patch.py --stock --apply`) and boot. If it boots, the
self-healing property is confirmed on your unit.

---

## 8.4 Rollback procedure (at any time)

Rollback sources you should have from [04](04-safety-and-backup.md):

1. `lk_a` read from your device before any write (byte-exact original);
2. the stock `lk.img` from your own firmware package (`image/lk.img`).

To roll back:

```bash
python scripts/prep_lk_patch.py --stock --apply --expect-sha256 <stock sha256>
python scripts/preflight_dual.py --image image/lk.img --expect-sha256 <stock sha256>
SPFlashToolV6.exe -c download -f image\download_agent\flash.xml -a da.auth
```

Same timing rules ([05-flashing.md §5.3](05-flashing.md#53-the-timing-procedure-start-the-tool-first-then-make-the-preloader-window)).

Expected after rollback: boots normally (because of §8.3) — unless you
rolled back *before* the patched LK ever completed a boot, in which case the
white screen returns. That is not a new problem; it is the original one.

---

## 8.5 Keeping the state (future risks)

| Risk | What to do |
|---|---|
| An OTA rewrites `lk_a` with a stock image and the stored region somehow reverts / a future build changes the check | keep this repo, your patched image, your `expdb` logs, and your backups. Re-diagnose first ([02](02-diagnosis.md)) — the fix may not be the same one. |
| You sell/discard the device | wipe your backups — they contain device-unique identity and calibration data. |
| A future build changes offsets | re-derive ([07 §7.7](07-lk-patching.md#77-if-you-must-port-to-another-build)) |
| Someone else's unit, same screen | give them [01](01-overview-and-symptom.md) → [10](10-pitfalls.md); the playbook is written to be transferable |

---

## 8.6 Final state checklist (record it)

```
[ ] device boots to Android
[ ] updater reports build is "latest"
[ ] [Check_Region] fatal lines absent in newest expdb cycle
[ ] no AVB rejections in newest cycle
[ ] dtbo / vbmeta / super / proinfo md5 unchanged from pre-fix
[ ] bootloader lock state as expected
[ ] calibration backups verified present + non-empty
[ ] stock lk.img + original lk_a dump retained for rollback
[ ] patched image + its sha256 retained
```
