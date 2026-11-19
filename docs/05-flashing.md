# 05 — Flashing with SP Flash Tool (console mode)

All device writes in this procedure go through **SP Flash Tool v6 console
mode**. It ships inside the official firmware package for your model (extract
the package; the tool lives next to the images). **Do not download it from
random sites** — the tool, its `DA_BR.bin`, and `da.auth` must match your
device's boot chain, and you get a consistent set by taking them from the same
firmware zip you already trust.

---

## 5.1 Setup

* Windows PC, MTK VCOM/preloader drivers installed.
* Extract SP Flash Tool + the firmware package.
* Keep the tool's own files together: `SPFlashToolV6.exe`, its Qt DLLs
  (`Qt5Core/Gui/Network/SerialPort/Widgets/Xml/XmlPatterns.dll` — **all of them
  or the exe dies with `0xC0000135`**), `console_mode.xsd`, `da.auth`,
  `image/download_agent/DA_BR.bin`, `image/download_agent/flash.xml`,
  `image/MT6835_Android_scatter.xml`.
* Delete or move away any encrypted `*.x` / `*.t` scatter siblings — this tool
  does **not** auto-decrypt; it needs the plaintext `.xml`.

### USB IDs (how to tell what state the tablet is in)

| ID | Meaning |
|---|---|
| `0e8d:2000` | preloader / VCOM — **the window you need for flashing** |
| `0e8d:2001` | DA VCOM (after the download agent is running) |
| `0e8d:201c` | fastboot |
| `0e8d:0003` | BROM |
| `0e8d:2046` | **off-mode charging — the tool ignores this one** |

Because `off-mode-charge=1` (stored in `para`), a powered-off tablet that is
just plugged in enumerates as `2046` and is invisible to the tool. **You must
press Power to produce a preloader window.**

---

## 5.2 Command forms that work

| Purpose | Command |
|---|---|
| **Read partitions** (read-only, safe) | `SPFlashToolV6.exe -i read_config.xml` |
| **Write partitions** (the only write form that works) | `SPFlashToolV6.exe -c download -f image\download_agent\flash.xml -a da.auth` |
| Format / firmware-upgrade / efuse ops | `-c format`, `-c format-download`, `-c firmware-upgrade`, `-c dram-repair`, `-c write-efuse`, `-c read-efuse` — **avoid**; see [04-safety-and-backup.md](04-safety-and-backup.md) |
| Other flags | `-p COMx` (explicit port), `-b` (reboot), `-r` |

### Command forms that do **not** work (do not waste cycles)

* `WRITE-FLASH` → `Cannot find [x] on current device storage.`
  Console mode never sends the scatter to the DA; reads work because they are
  address-based.
* `WRITE-PARTITIONS` → the scatter *is* sent, then `flash list elements
  invalid.` The DA wants `<pt><name>x</name></pt>` (a child element, as in its
  own partition-table output), while `console_mode.xsd` only permits
  `<pt name="x"/>`. **Schema and DA are incompatible in this tool version —
  console writes through these verbs are impossible.**

**`-c download` writes exactly the partitions whose scatter entry has
`is_download=true`.** That is the entire write mechanism used here.

### Console config requirements (validated against `console_mode.xsd`)

```xml
conn_stage="2nd DA"                 <!-- NOT "brom": that fails with
                                       'No such node (brom.version)' -->
flash-xml  = image/download_agent/flash.xml
auth-file  = da.auth
system_os  = WINDOWS
baud_rate  = 115200
timeout_ms = 300000
log_path   = logs
```

Validate any config you edit against `console_mode.xsd` before running it.

### Logs

| Mode | Location |
|---|---|
| `-i` (console reads) | `<tool>/logs/SP_FT_V6_Dump_*/` |
| `-c` (CLI) | `C:\ProgramData\SP_FT_V6_Logs\SP_FT_V6_Dump_*/` (from `option.ini`) |
| per session | `QT_FLASH_TOOL_V6.log` (host) + `host_0.log` / `device_0.log` (DA protocol) |

---

## 5.3 The timing procedure: start the tool first, then make the preloader window

This is the single most important operational detail.

1. **Start the tool first**, so it is already scanning for the port.
2. Then create the preloader window:
   1. unplug USB,
   2. hold **Power for 10 s**, release,
   3. plug USB in,
   4. **press Power once**.
3. The tool catches the device within about a second and the transfer starts.

If you press Power *before* starting the tool, you miss the window: the
preloader port only exists for a moment during the boot attempt, and the screen
comes up, shows for 10 s, and the device powers off — **one press = one
attempt, no second chance**.

### Power-cycle between sessions

**Every SP Flash Tool session leaves the download agent running.** The tablet
cannot handshake again until you power-cycle it:

```
unplug → hold Power 10 s → release → plug USB → press Power once
```

Skipping this produces "device not found" no matter how many times you retry.

### Enters, if you need them

* **Recovery:** hold **Vol UP + Vol DOWN** together, tap Power, keep holding.
* **Fastboot:** from recovery → `Enter fastboot`.
* Recovery exposes **no ADB** on these units — don't wait for it.
* Fastboot may enumerate (`0e8d:201c`) but have **no driver** (PnP error 28).
  Nothing in the recommended procedure needs fastboot; the community "Device
  Recovery" mode is SPFT/PreLoader-only for the same reason.

---

## 5.4 <a name="reading"></a>Reading partitions

```powershell
SPFlashToolV6.exe -i read_calibration.xml      # configs/read_calibration.xml
```

Same timing rules as above (tool first, then Power). Output lands in
`logs\SP_FT_V6_Dump_*\`.

Typical read set and why: [04-safety-and-backup.md §4.3](04-safety-and-backup.md#43-the-backup-pass-one-read-only-device-cycle).
Extract the LK log from `expdb` afterwards:
[02-diagnosis.md §2.2](02-diagnosis.md#22-step-2--get-the-lk-log-out-of-expdb).

---

## 5.5 Writing: the full sequence

```bash
# 1. stage: arm the scatter for exactly {lk_a, lk_b} and copy the image in
python scripts/prep_lk_patch.py --dual --apply --expect-sha256 <sha256>

# 2. pre-flight: assert everything the DA will see
python scripts/preflight_dual.py --image image/lk_patched_dual.img \
        --expect-sha256 <sha256>
#    → must print "ALL GREEN - ready to flash"

# 3. launch the tool (it starts scanning immediately)
SPFlashToolV6.exe -c download -f image\download_agent\flash.xml -a da.auth

# 4. now make the preloader window: unplug → hold Power 10 s → release →
#    plug → press Power once
```

**Expected:** `lk_a` + `lk_b` reported as downloaded, then the tool issues
`CMD:REBOOT IMMEDIATE` and the tablet restarts by itself.

**Expected result:** white screen gone → boot animation → Android.

### If the scatter has extra copies

Tell the preflight about them so they are compared too:

```bash
python scripts/preflight_dual.py --scatter MT6835_Android_scatter.xml \
        --scatter ../MT6835_Android_scatter.xml
```

---

## 5.6 Scatter discipline (why this deserves its own section)

`prep_lk_patch.py`:

1. rewrites `<is_download>` to `true` for **exactly** `{lk_a, lk_b}` and `false`
   for *every* other entry (clearing any stale tick from an earlier attempt);
2. points those two entries' `<file_name>` at the staged image;
3. asserts the intended set is the only ticked set, the image fits, and no
   encrypted scatter is present;
4. **mirrors the rewritten scatter to every other copy in the work dir**, so no
   path-resolution ambiguity can pick a different partition set.

Run it as a dry run first (no `--apply`) and read the report: it prints the
`is_download` set *before* and *after*. If "before" shows something you didn't
intend (e.g. `['misc']`), that is exactly the stale state that would otherwise
have been flashed.

---

## 5.7 What the tool looks like when it goes wrong

| Message | Meaning | Action |
|---|---|---|
| No device, tool spinning | wrong port state / no Power press | power-cycle, start tool first, press Power once |
| `0e8d:2046` only | off-mode charging | press Power |
| Second attempt fails immediately | DA still running from previous session | full power-cycle (10 s) |
| `Security deny [x] Signature(Entity) invalid` | the partition refuses unsigned writes (e.g. `misc`) | don't fight it; use a different route |
| `flash list elements invalid` | you used `WRITE-PARTITIONS` | use `-c download` |
| `No such node (brom.version)` | `conn_stage="brom"` | use `conn_stage="2nd DA"` |
| Tool exits immediately with `0xC0000135` | missing Qt DLL | restore the tool's own DLLs |

More: [09-troubleshooting.md](09-troubleshooting.md).

Next: [06 — Fix options](06-fix-options.md).
