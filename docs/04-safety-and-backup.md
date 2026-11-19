# 04 — Safety rules and the read-only backup pass

Read this **before** you open SP Flash Tool even once. Everything here was
learned by breaking things or nearly breaking them.

---

## 4.1 Hard rules (never do these)

| # | Rule | Why |
|---|---|---|
| 1 | **Never write `efuse`.** | One-time programmable. Irreversible. A bad write bricks the SoC. |
| 2 | **Never write `preloader`** unless a repair tool explicitly requires it. | A corrupted preloader = no USB port at all = no recovery path. |
| 3 | **Never write `userdata` from the scatter.** If you need a wipe, use recovery's *Wipe data / factory reset*. | Scatter-driven `userdata` writes risk the encryption metadata layout; recovery does it the way the OS expects. |
| 4 | **Never write `proinfo`, `nvram`, `nvcfg`, `nvdata`, `protect1/2`, `otp`, `dram_para`, `persist`, `metadata`, `bk1`, `sec1`** before you have a verified backup of them. | These hold Wi-Fi/BT/modem calibration and device identity. **Losing them is the only unrecoverable outcome of this whole procedure.** |
| 5 | **Never patch `logo.img`** (or `dtbo`/`vbmeta` blindly). | Signed containers; a bad edit yields a dead device with no log. |
| 6 | **Never launch a write without verifying the scatter's ticked set.** | The classic foot-gun: a stale scatter still armed for an earlier partition. |

Nothing in the recommended procedure requires efuse, preloader, or userdata
writes.

## 4.2 Before every single launch — the checklist

Print it. Run it every time, including rollback runs.

1. **All copies of the scatter are byte-identical.**
   The download agent resolves `<scatter>` **relative to `flash.xml`**; a second
   copy elsewhere silently means a *different* partition set. (This actually
   happened: two root-level copies were still armed for an old `misc` write
   while the `image/` copy looked correct.)
2. **Exactly the intended set has `is_download=true`.**
3. **Image size ≤ partition size** for every ticked entry.
4. **No encrypted `.x` / `.t` scatter** sits next to the plaintext `.xml`
   (this tool does not auto-decrypt; it reads the plaintext file at
   `image/MT6835_Android_scatter.xml`).
5. **A rollback source exists** (your own `lk` read-back + the stock image of
   your build).
6. **Protected partitions are all `false`**: `preloader`, `efuse`, `misc`,
   `para`, `boot_para`, `userdata`, `proinfo`, `dtbo_*`, `super`, `vbmeta*`,
   `boot_*`, `metadata`.

Automate it:

```bash
python scripts/prep_lk_patch.py --dual --apply      # stages + asserts
python scripts/preflight_dual.py --image image/lk_patched_dual.img \
        --expect-sha256 <sha256 of the image you built>
```

`preflight_dual.py` prints `ALL GREEN - ready to flash` or `FAILURES PRESENT -
do NOT flash`. **Do not flash on FAIL.**

---

## 4.3 The backup pass (one read-only device cycle)

Do this **once, before anything else**. It costs one power-cycle and protects
against every mistake that follows.

### What to read

| Partition | Size | What it is |
|---|---|---|
| `proinfo` | 1 MB | device identity: country code, fingerprint, SN |
| `nvram` | varies | MTK NVRAM (Wi-Fi/BT/MAC calibration) |
| `nvcfg` | 32 MB | MTK NVRAM config (metadata + filter) |
| `nvdata` | 64 MB | MTK NVRAM data (modem/BT/Wi-Fi calibration) |
| `protect1` / `protect2` | 8 MB each | FAT filesystems with NVRAM backups |
| `otp` | 43 MB | one-time programmable area (read it, never write) |
| `efuse` | 512 KB | **READ ONLY — never write** |
| `dram_para` | 25 MB | DRAM parameters |
| `persist` | 54 MB | vendor persist (sensors, DRM ids) |
| `metadata` | 64 MB | vold / encryption metadata |
| `bk1` | 2.5 MB | unknown Lenovo backup area |
| `sec1` | 2 MB | unknown Lenovo secure area |
| `preloader` | 4 MB | the device's *original* preloader |
| `misc` | 512 KB | BCB + boot_ctrl |
| `expdb` | 128 MB | diagnostics + **the LK log** |
| `pstore` | 128 MB | persistent store (usually empty) |

Also worth dumping once: `seccfg`, `para`, `frp`, `boot_para`, `lk_a` (the
bootloader itself — this is your rollback image), `lenovocust`.

### How

The ready-made configuration is
[`configs/read_calibration.xml`](../configs/read_calibration.xml) — a
`READ-PARTITION`-only configuration validated against the tool's
`console_mode.xsd`. It contains **no writes at all**.

```powershell
SPFlashToolV6.exe -i configs\read_calibration.xml
```

Read-only console mode (`-i`) is the *safe* mode; it is also the only mode in
which reads work reliably (see [05-flashing.md](05-flashing.md#reading)).

**Order of operations matters** — see
[05-flashing.md § the timing procedure](05-flashing.md#53-the-timing-procedure-start-the-tool-first-then-make-the-preloader-window):
start the tool first, *then* produce the preloader window.

### Where the output goes

* console mode (`-i`) → `logs\SP_FT_V6_Dump_*\` under the tool's working dir
* each run writes `QT_FLASH_TOOL_V6.log`, `host_0.log`, `device_0.log`

Copy the resulting `.bin` files to a **read-only backup location** (a separate
disk). Verify by re-reading file sizes against the table above — a truncated
read is worse than no read, because you'll trust it later.

---

## 4.4 Verify your backup actually contains data

Before you trust it:

```bash
# sanity: sizes match the table, and files are not all 0xFF/0x00
python - <<'EOF'
import os
for f in sorted(os.listdir('.')):
    if not f.endswith('.bin'): continue
    b = open(f,'rb').read(4096)
    nz = sum(1 for x in b if x)
    print("%-24s %10d B  nonzero-bytes-in-first-4k: %d" % (f, os.path.getsize(f), nz))
EOF
```

Every calibration file should show non-trivial content. `efuse` is small —
that is normal, it is only 512 KB.

---

## 4.5 What you specifically do *not* need to back up

* `userdata` — it is expendable (and you have authorised wiping it if needed).
* `super` / `boot` / `dtbo` / `vbmeta` — all re-flashable from firmware.
* `logo.img` — signed and unmodified by this procedure.

---

## 4.6 Keeping the "before" evidence

In addition to the dumps, keep:

* the `expdb`-derived LK log of the **failing** state (you will diff against it),
* `lk_a` as read from the device (md5 recorded) — this is the byte-exact
  rollback for the bootloader,
* your `preflight` output.

Next: [05 — Flashing procedure](05-flashing.md).
