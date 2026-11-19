# configs — SP Flash Tool console-mode configuration

## `read_calibration.xml` — **read-only backup pass**

A validated `console_mode.xsd` configuration that reads the calibration /
identity / diagnostic partitions and writes them as `.bin` files next to the
tool. **It contains no write commands.**

Run it from the SP Flash Tool directory (after copying the file there):

```powershell
SPFlashToolV6.exe -i read_calibration.xml
```

Partitions read (see [`docs/04-safety-and-backup.md`](../docs/04-safety-and-backup.md)
for what each one is and why it matters):

```
nvcfg  nvdata  protect1  protect2  otp  efuse(READ-ONLY)  dram_para
persist  metadata  bk1  sec1  preloader  expdb  pstore  misc
```

The `expdb` dump is the important diagnostic one: it contains the LK boot log
in its `0x7E00000..0x8000000` tail. Extract it with
[`scripts/dump_lk_log.ps1`](../scripts/dump_lk_log.ps1).

### Adapting it

* Partition names come from your own scatter (`<partition_name>` entries) — if
  your platform names them differently, edit the `partition=` attributes to
  match yours.
* `<flash-xml>` and `<auth-file>` must point at the files that ship with **your**
  firmware package (`image/download_agent/flash.xml`, `da.auth`).
* `conn_stage="2nd DA"` is required (`"brom"` fails with
  `No such node (brom.version)`).
* Validate any edit against the tool's own `console_mode.xsd` (ships with SP
  Flash Tool; **not** included here — it is MediaTek's file).

### To read `lk_a` for rollback

Add:

```xml
<READ-PARTITION version="1.0" partition="lk_a">
  <target-file version="1.0" file_type="LOCAL_FILE" file_name="lk_a.bin"/>
</READ-PARTITION>
```

Do this **before** you write anything — that read-back is your byte-exact
rollback image.

## Not included here

* **write configurations** — writes always go through
  `-c download` + a scatter you have verified
  ([`docs/05-flashing.md`](../docs/05-flashing.md)); keeping a ready-made
  "write this" XML in a repository is how people brick devices.
* **`console_mode.xsd`, `da.auth`, `flash.xml`, `DA_BR.bin`** — MediaTek/Lenovo
  files that come with SP Flash Tool and the firmware package
  ([`LEGAL.md`](../LEGAL.md)).
