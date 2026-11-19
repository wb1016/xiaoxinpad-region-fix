# 03 — Root cause: the region check in LK

Everything in this document refers to file offsets inside the `lk` section
container of `lk.img`, for the reference build (TB336FU, ZUI 17.5.10.321,
`…ST_260804`). Offsets move between builds; the *logic* does not. Scripts
re-verify the expected bytes at every offset before acting.

---

## 3.1 The two values that must agree

| | Where it lives | Who writes it | Reference value |
|---|---|---|---|
| device region | RPMB (`product_region` + `region_state` block) | the factory (Lenovo) | `PRC` / `CNXX` |
| build region | `dtbo.img` → FDT overlay `fragment@N` → `product_region` node → `country`, `province`, `city` | the firmware you flashed | `ROW` / `ROW` / `ROW` |

The `dtbo` side is easy to confirm:

```bash
python scripts/dtbo_regions.py dtbo.img
```

```
fragment@48/__overlay__/product_region:  country=ROW  province=ROW  city=ROW
fragment@48 is the target of __fixups__: product_region
```

Both the V and the W packages of the reference model declare `ROW` — including
the *exact factory* package. So no firmware available to the user can ever
match a `PRC` device. That is the whole problem.

The device side shows up in `proinfo` (`countrycode = CNXX`, factory fingerprint
`…_PRC…`) and in LK's boot log (`read countrycode is CNXX`).

---

## 3.2 What LK actually does

`region_check_main` occupies `0xac5c … 0xafd4` in the reference build.
Decompiled to pseudocode:

```c
val = read_boot_history_after_flush_lenovo_from_rpmb();
if (val == 0) {                      // virgin device: provision from DT
    build region_state from DT;
    write_product_region_to_rpmb(...);
    return OK;
}

read_product_region_from_rpmb(&stored);          // device region
read_build_region_from_dt(&build);              // firmware region (dtbo)

if (region_compare(stored, build) == SAME)      // 0xaec4 tbz -> 0xaec8  healthy
    return OK;

/* --- mismatch: two further gates --- */
read_region_state_from_rpmb(&region_state);

if (region_state.update_flag != 1) {            // 0xaf10 cmp w8,#1
    /* line 1427 */
    clear_screen(); draw_error_bitmap();
    log("[Check_Region] 1427: region is not update flag");
    backlight_on(); delay_us(10_000_000);       // 10 s
    power_off();
}

if (xor_compare(staged_region, build_region) != 0) {   // 64-byte XOR reduce
    /* line 1437 */
    clear_screen(); draw_error_bitmap();
    log("[Check_Region] 1437: new region is not same");
    backlight_on(); delay_us(10_000_000);
    power_off();
}

write_product_region_to_rpmb(build_region);     // ← the SUCCESS path
clean_update_flag();
return OK;                                      // boot continues
```

### The two gates

| Log line | Address | Stock bytes | Condition to survive |
|---|---|---|---|
| 1427 `region is not update flag` | `0xaf14` | `41 04 00 54` = `b.ne #0xaf9c` | `region_state.update_flag == 1` — only Lenovo's *signed* region-change flow sets it |
| 1437 `new region is not same` | `0xaf7c` | `e8 01 00 b4` = `cbz x8,#0xafb8` | staged region == build region |

Layout of `region_check_main`:

```
0xaf0c  ldr  w8,[x22,#0x410]     read update_flag
0xaf10  cmp  w8,#1
0xaf14  b.ne #0xaf9c             ──┐ GATE 1427  ← a never-region-changed device dies HERE
0xaf18..0xaf78  64-byte XOR reduce │
0xaf7c  cbz  x8,#0xafb8          ── GATE 1437  ← only the community patch flips this
0xaf80..0xaf98  clear + draw + log 1437   (fatal)
0xaf9c..0xafb4  clear + draw + log 1427   (fatal)
0xafb8..        write_product_region_to_rpmb(build) + clean_update_flag → OK
```

### Why a never-region-changed device always dies at 1427

On a factory-fresh unit `update_flag` is `0`: nothing official ever staged a
region change, so the flag was never set. The `cmp` at `0xaf10` therefore fails
and LK branches to the 1427 fatal block at `0xaf9c` — upstream of the actual
region comparison. The 1437 branch is never even evaluated.

Verified by the edge audit in
[`scripts/lk_audit_gate.py`](../scripts/lk_audit_gate.py):

* `0xaf14` and `0xaf9c` have no other in-edges anywhere in `.text`;
* `0xaf9c` is reachable *only* from `0xaf14`;
* `0xaf80` is reachable *only* by fallthrough from `0xaf7c`;
* the screen renderer at `0x77644` has exactly two callers — `0xaf84` and
  `0xafa0`, i.e. exactly the two fatal blocks.

> ⚠️ The audit must scan all five AArch64 branch classes (`B`, `BL`,
> `B.cond`, `CBZ`, `TBZ`), 30,127 branches in this build. An early version that
> only counted `CBZ`/`TBZ` produced a misleading result — re-run it rather than
> trusting a stale log.

### The fatal tail (why "screen, then off")

| Address | Behaviour |
|---|---|
| `0xada0` | pre-screen clear, then `0x77644` draws the bitmap from `logo.img` |
| `0x3cd10` | MMIO `0xffff1c007008 ← 0x1971` — backlight on |
| `0x6189c` | `delay_us(10_000_000)` = 10 seconds |
| `0x1bba0` → `0x1e848(2,3)` | queue → power off |

Exactly the observed behaviour: one screen, ~10 s, off, no loop.

---

## 3.3 Why firmware flashing can never fix it

1. The mismatched value is in RPMB. SP Flash Tool works through the
   preloader and only addresses *flash* partitions; RPMB is
   hardware-authenticated per-device with a replay counter. It is not in the
   scatter and cannot be written.
2. Format-all does not touch it either (format targets `userdata`/
   `metadata`, not RPMB).
3. Factory reset does not touch it (`userdata` is irrelevant).
4. Every available package declares `ROW`, including the exact factory one.

⇒ "I flashed the official package and it still fails" is the *expected* result,
not a sign of a bad download.

## 3.4 Why the popular community patch does nothing on these units

The widely circulated patch flips exactly one branch:

```
0x00af7c   stock: cbz x8, #0xafb8   (e8 01 00 b4)
           patch: b    #0xafb8       (0f 00 00 14)
```

That is the 1437 gate. On a unit that dies at 1427 the patched
instruction is never reached — LK still branches at `0xaf14` into the untouched
1427 block and re-draws the same screen. Static CFG
([`scripts/lk_region_cfg.py`](../scripts/lk_region_cfg.py)) proves there is no
alternate entry into the fatal blocks, and the reference device's own log
confirms it: `[Check_Region] 1427` ×11, `1437` ×0.

This is why the same community image boots *someone else's* unit: that device
had a staged region change (`update_flag == 1`) and died one gate later.

## 3.5 The fix that works: bypass both gates

```
0xaf14   41 04 00 54   b.ne #0xaf9c   →   29 00 00 14   b #0xafb8
0xaf7c   e8 01 00 b4   cbz  x8,#af80  →   0f 00 00 14   b #0xafb8
```

Both fatal blocks become unreachable and every path converges on `0xafb8`:

```
write_product_region_to_rpmb(build region) → clean_update_flag() → return OK
```

### Why this is *self-healing*

After the first successful boot:

* RPMB `stored_region` is now the build's region (`ROW`) → the earlier
  `region_compare` at `0xaec4` returns *same* on every later boot → LK takes the
  healthy path even with an unpatched stock bootloader;
* `update_flag` has been cleared consistently with the stored region.

So the patch only has to survive *one* boot. If you later re-flash stock `lk`,
the device keeps booting.

### Why that path is safe on this unit

`clean_update_flag` (`0xaa78`) re-validates exactly what
`read_region_state_from_rpmb` (`0xa820`) validated: magic `1a2b3c4d` at `+0`,
byte-reversed `4d3c2b1a` at `+0x47c`, a 32-byte checksum at `+0x484`, and
`[0x408]==0 && [0x40c]==1`. The reference device *passed* `0xa820` (it logged
1427, not 1422), so `clean_update_flag` returns 0 → no line-1447 death.

Before applying the patch on your own unit, confirm the same: your log must
show 1427 (not 1422/1447) — see [02-diagnosis.md](02-diagnosis.md).

---

## 3.6 Where `update_flag = 1` comes from (why we cannot fake it)

Exactly one writer exists in `.text`: function `0x9bc0` (dispatched through
a function table — i.e. the official `oem unlock-region` flow). It:

1. reads `region_state` from RPMB (`id 0xf800`, length `0x500`);
2. validates checksum + `MAGIC_NUM1`/`MAGIC_NUM2` + `[0x408]/[0x40c]`;
3. copies the new region into `+0x8` and `+0x208`;
4. `str w8=1, [x21,#0x410]` at `0x9e04` — sets the flag;
5. recomputes the checksum and writes RPMB.

The error strings around it (`sign verify fail`, `digest verify fail`,
`wrong region length`, `Bootloader_SN not matched`) show the payload is
signed — you cannot forge this path with a hand-made write. Either Lenovo's
tooling signs it, or you bypass the gate (the patch) instead.

---

## 3.7 The `cert2` problem (why a naive hand-patch is rejected)

`lk.img` is a sequence of `{magic 0x58881688, size, name[32]}` sections, each
payload at header+`0x200`, padded to 16 bytes:

```
lk (code) → cert1 → cert2 → bl2_ext → aee → lk_main_dtb → lk_dtbo → … (15 total)
```

The bootloader verifies `cert2` before running the code. It contains a 995-byte
DER blob plus, in *patched* images, a 90-byte override prefix:

```
cert2 = a0 58
      | OID_HEADER 06 07 60 86 76 93 16 02 04 03 21 00 | SHA-256(img[0x0000..0x0200])
      | OID_DATA   06 07 60 86 76 93 16 02 01 03 21 00 | SHA-256(payload zero-padded to 16 B)
      + the original 995-byte DER
      → section size 995 → 1085, padded to 1088 (+80 bytes total shift)
```

Two traps that make this look impossible at first:

1. the header digest covers only the first 512 bytes (the MTK section
   header), not the whole file;
2. the payload digest is over the section payload zero-padded to 16-byte
   alignment.

Get either wrong and "no hash of any range matches". With both correct, the
scheme reproduces byte-for-byte on *both* the stock image and a known-good
community image — see [`scripts/lk_cert_verify.py`](../scripts/lk_cert_verify.py)
and [07-lk-patching.md](07-lk-patching.md).

---

## 3.8 The second, independent failure mode

AVB (Android Verified Boot) runs *before* the region check. If `vbmeta` does not
match the device's stored public key:

```
[AVB] invalid pubk size
avb_slot_verify.c:860: ERROR: vbmeta_a: Public key used to sign data rejected.
ASSERT FAILED at (app/mt_boot/boot_info.c:181): g_boot_info.hdr_loaded
HALT: action = 0, reason = 9   →  power off, no screen
```

Same visible outcome ("it powers off"), completely different cause and fix.
Always separate the two before acting: [02-diagnosis.md](02-diagnosis.md),
[09-troubleshooting.md](09-troubleshooting.md#avb).

Next: [04 — Safety and backup](04-safety-and-backup.md).
