# scripts — what each one does and how to run it

All scripts are read-only with respect to the device. The only one that
modifies anything on disk is `prep_lk_patch.py`, and only with `--apply` (it
rewrites your *local* scatter file, never a device).

Nothing here flashes anything: flashing is always a separate, explicit step
([`docs/05-flashing.md`](../docs/05-flashing.md)).

---

## Requirements

```bash
python -m pip install capstone        # disassembly scripts (lk_*)
python -m pip install pillow          # logo_* rendering scripts only
```

Python 3.8+. No other dependencies. `dump_lk_log.ps1` needs Windows PowerShell 5+.

---

## The work directory convention

Scripts resolve paths relative to your current working directory. Run them
from a work directory laid out like this (create it yourself; it is gitignored):

```
work/
├── image/                      ← from YOUR firmware package
│   ├── lk.img                     the stock bootloader image
│   ├── MT6835_Android_scatter.xml the scatter (name = your platform)
│   └── download_agent/
│         ├── flash.xml            used by: -c download
│         └── da.auth
├── patched/                    ← images you build or obtain yourself
│   ├── lk_patched_dual.img        output of lk_build_dualpatch.py
│   └── lk_patched_community.img   (optional) community-patched image
├── dtbo.img  vbmeta.img  vbmeta_system.img  vbmeta_vendor.img  logo.img
├── *.bin                        ← partition dumps (cal_*, expdb, proinfo, …)
└── lk_boot_log.txt              ← extracted LK log
```

Every script also takes the important path(s) as command-line arguments, so
you can use any layout you like — the default is only a default.

```bash
cd work
python ../scripts/lk_layout.py image/lk.img
python ../scripts/lk_layout.py /path/to/other/lk.img
```

---

## Script reference

### Bootloader (LK) analysis

| Script | Needs | What it does |
|---|---|---|
| `lk_layout.py [lk.img]` | — | maps the container: section headers (`0x58881688`), sizes, ELF signatures |
| `lk_region_cfg.py [stock] [patched]` | capstone | full annotated CFG of `region_check_main` (`0xac5c..0xafd4`); resolves every `[Check_Region]` line number and format string (answers "which gate does this build use?") |
| `lk_audit_gate.py [lk.img]` | capstone | branch-edge audit: proves `0xaf14`/`0xaf9c` have no other in-edges and that the screen renderer has exactly 2 callers; also dumps `read_region_state_from_rpmb`, the magic check, and `write_product_region_to_rpmb` |
| `lk_region_state_refs.py [lk.img]` | capstone | every load/store of `region_state+0x410`, every `BL` caller of the region helpers, string xrefs |
| `lk_flag_writer.py [lk.img]` | capstone | finds the only `update_flag = 1` writer in `.text` (the signed official region-change flow) |
| `lk_cert_verify.py [stock] [patched]` | — | proves the `cert2` digest scheme on both images (512-byte header digest + 16-byte-padded payload digest) |
| `lk_build_dualpatch.py [stock] [community]` | capstone | builds the two-gate patched image and runs a 16-way verification battery before writing it |

### Firmware / image inspection

| Script | What it does |
|---|---|
| `dtbo_regions.py <dtbo>` | finds every FDT blob by magic and prints region-related properties (`country`/`province`/`city`/`hardware`) — this is how you read the build's `product_region` |
| `dtbo_parse.py [dtbo]` | full Android `dt_table` + FDT overlay property dump |
| `avb_desc.py [vbmeta…]` | AVB header, algorithm, flags, and every descriptor — answers "is `dtbo` covered by a hash descriptor?" |
| `vbmeta_dump.py` | printable strings of `vbmeta*` + region-token context in `dtbo`/`proinfo` (expects `dtbo.img`, `vbmeta*.img`, `proinfo.bin` in cwd) |
| `region_scan.py` | sweeps `vbmeta*`, `dtbo`, `proinfo`, `lk` for region/country/board keywords |
| `hunt_region_state.py [globs…]` | searches dumps for the `region_state` magic (`1a2b3c4d` / `4d3c2b1a`) — used to prove it lives only in RPMB |
| `logo_parse.py [logo.img]` | container parser (headers, zlib block table, signature trailer) |
| `logo_decode.py [logo.img]` | decompresses candidate offsets |
| `logo_render.py [logo.img]` | renders the decoded screens (BGRA→RGBA) — produces the readable error-screen PNGs |
| `erofs.py` | standalone EROFS reader (LZ4, compact indexes) used by `hunt.py` |
| `super.py` | Android sparse-image + liblp reader used by `hunt.py` |
| `hunt.py <file\|super> <img> [part\|*]` | multi-encoding, multi-needle text search over a firmware image (raw, EROFS, nested zips, carved compressed streams) |
| `streamhunt.py` | raw-bytes + nested-zip + carved gzip/lz4/xz/zstd/bzip2 search |

> `hunt.py` exists to *disprove* things: running it with the error-screen phrases
> returns 0 hits in every build, which is exactly why the screen must be a
> bitmap.

### Boot-log tooling

| Script | What it does |
|---|---|
| `dump_lk_log.ps1 -Expdb <bin> -Out <txt>` | extracts printable strings from `expdb`'s `0x7E00000..0x8000000` tail and prints the `[Check_Region]`, AVB/ASSERT, keyword and last-60-line sections |
| `cycles.py [log]` | splits the log into boot cycles and reports per-cycle events |
| `s5_log_report.py [new] [old]` | classifies the newest cycle: region death, AVB death, or a boot that reached Linux; optionally compares two logs |

### Scatter staging (the only scripts that write files, locally)

| Script | What it does |
|---|---|
| `prep_lk_patch.py [--dual\|--stock\|--src F] [--apply] [--expect-sha256 H] [--force]` | stages an image into `image/`, rewrites the scatter so exactly `lk_a`+`lk_b` are ticked, mirrors the scatter to every copy, asserts fit/no-encrypted-siblings. Dry run by default. |
| `preflight_dual.py [--image F] [--expect-sha256 H] [--scatter P] [--rollback F]` | final pre-flight of everything the DA will see → `ALL GREEN - ready to flash` / `FAILURES PRESENT - do NOT flash` |

Typical sequence:

```bash
python ../scripts/prep_lk_patch.py --dual --apply --expect-sha256 <sha256>
python ../scripts/preflight_dual.py --image image/lk_patched_dual.img --expect-sha256 <sha256>
# then, from the SP Flash Tool directory:
SPFlashToolV6.exe -c download -f image\download_agent\flash.xml -a da.auth
```

---

## Safety properties built into these scripts

* `lk_build_dualpatch.py` refuses to patch unless the stock bytes at each
  site match (so it cannot silently patch a different build), and refuses to
  write its output unless every verification check passes.
* `prep_lk_patch.py` treats a hash/size mismatch as a failure unless you
  pass `--force`, and prints the `is_download` set before and after.
* `preflight_dual.py` exits non-zero on any failure and requires an explicit
  `--expect-sha256` to claim the staged image is the one you built.
* Nothing in `scripts/` opens a device or issues a flash command.
