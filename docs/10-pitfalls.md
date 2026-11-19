# 10 — Pitfalls: the wrong turns that cost the most time

Every item below was actually followed and disproved. They are listed in the
order they derail people.

---

## 10.1 "The message string is not anywhere in the firmware → it must be generated at runtime"

Wrong. The sentence exists only as pixels:

* a 3200×1280×4 BGRA bitmap inside a zlib block inside the signed
  container of `logo.img`;
* searching for the text returns 0 hits *always*, in *every* build;
* reading the raw bytes as RGBA makes it look blue — it is red-on-white;
* an early "test" (`longest single-byte run = 4095 B → not a bitmap`) was
  meaningless because the data is compressed;
* similarly, carving JPEG slices out of `logo.img` produces garbage — there are
  no JPEGs in it.

Correct approach: parse the container, decompress, render
(`scripts/logo_parse.py` / `logo_decode.py` / `logo_render.py`) and *look* at
the image. That immediately tells you which component draws the screen: LK,
before Linux.

## 10.2 "`expdb` reaches `notify_boot_linux`, so LK is not rejecting the system"

Wrong. A 128 MB ring buffer holds many cycles with different outcomes.
In the reference log 10 of 20 cycles reached the kernel and 10 died in an AVB
assert — and the *newest* cycles all died at the region gate. Always classify
the newest cycle, never an average or an old one.

## 10.3 "The device is ROW (the factory build says ROW) so there is no region mismatch"

Half wrong. The *firmware package* is ROW; the device's `proinfo` carries
`countrycode = CNXX` and a `_PRC` factory fingerprint, and the stored region in
RPMB is the PRC one. Package naming and device region are different things —
`TB336FU_ROW_OPEN_USER_…` describes the *software*, not the hardware's region
record.

## 10.4 "The community patch is the known-good fix"

Wrong for units that log 1427. The community image flips only `0xaf7c`
(gate 1437). If your log says 1427, the patched instruction is never reached and
the screen comes back unchanged. Conversely the same image *does* boot other
people's units — those devices had `update_flag == 1` and died one gate later.

Rule: match the patch to your log line, and prove the branch topology with
an edge audit before flashing anything.

## 10.5 "We can't hand-patch, because we can't find the digests"

Wrong — the digests are reproducible. Two mistakes caused the dead end:

1. hashing something other than the 512-byte header for `header_sha`;
2. hashing the payload at its raw length instead of 16-byte zero-padded.

With both corrected, the scheme reproduces exactly on stock *and* patched
images. The deeper lesson: a negative result from one probe design is not a
proof of impossibility — document what you actually tried.

## 10.6 "Disassembly says the string has no cross-reference → our analysis is broken"

Trap in the tooling. ADRP/ADR targets computed at file-offset PCs need the
skew `file = T+0x200 if (T & 0xFFF) ≥ 0x200 else T−0xE00`. Without it you get
plausible-looking nonsense (an early run found "273 exact hits" that were chance,
because strings are dense). With it, all 19 `[Check_Region]` strings resolve.

## 10.7 "The edge audit says those branches have no other in-edges"

Only trust it if it scanned all branch classes. A first version counted
`CBZ`/`TBZ` only and produced a confident, wrong answer. The correct audit
covers `B`, `BL`, `B.cond`, `CBZ`, `TBZ` (30,127 branches here). Re-run the
tool rather than trusting a stored log — including the one in this repo.

## 10.8 "I updated the scatter I'm using, so I'm fine"

The DA resolves `<scatter>` relative to `flash.xml`. In practice there were
three copies; two root-level ones stayed armed for an *old* `misc` write while
the copy being edited looked correct. Anything path-dependent can silently point
at a different partition set.

Rule: after touching a scatter, verify every copy is byte-identical
(`preflight_dual.py` does this), and never leave an encrypted `.x`/`.t` sibling
around.

## 10.9 "Write verbs: I'll just try them"

Two of the three console write verbs cannot work in this tool version:

* `WRITE-FLASH` never sends the scatter → `Cannot find [x] on current device storage.`
* `WRITE-PARTITIONS` sends it, then the DA rejects it because `console_mode.xsd`
  and the DA disagree about the `<pt>` element shape → `flash list elements invalid.`

Only `-c download` (scatter-driven, `is_download=true`) works for writes. Reads
work in `-i` console mode because they are address-based.

## 10.10 "I'll press Power first and then start the tool"

The preloader port exists only during the boot attempt, and the failure screen
powers the device off after 10 s — one press = one attempt. Start the tool
first, then make the window (unplug → hold Power 10 s → release → plug → press
Power once). And power-cycle between sessions: the DA stays running.

## 10.11 "Format All / factory reset will clear it"

Neither touches RPMB. `userdata`/`metadata` are irrelevant to the check. Format
is also the step most likely to cost you calibration data — do it last, if ever.

## 10.12 "Recovery has ADB / fastboot has a driver"

On this family recovery exposes no ADB, and fastboot enumerates but may have
no driver (PnP 28). Neither blocks the recommended procedure — everything
goes through SP Flash Tool — but both cost time when assumed.

## 10.13 "The exact factory package will satisfy it"

Case in the history: *factory 250424, all 47 files, original bootloader* → still
"not compatible". Because the factory package declares `ROW` and the device's
RPMB says `PRC`. This is the single strongest evidence that the value is
device-side.

---

## The transferable playbook (short form)

1. Recognise the screen — a bitmap drawn by LK; text search will never find
   it.
2. Read `expdb` first — separate region lock (1427/1437 + screen) from AVB
   (assert, no screen).
3. Never flash firmware expecting it to help — RPMB is out of reach.
4. Back up calibration in one read-only pass before any write.
5. Choose the fix deliberately: two-gate LK patch (works for any stored
   region), matching `dtbo` (works if you know the stored region), the community
   orchestrator (read its source), or the official unlock/region change.
6. Patch only after proving the branch topology on *your* bytes, and
   regenerate `cert2` (512-byte header digest + 16-byte-padded payload digest).
7. Scatter discipline: one intended tick set, all copies identical, no
   encrypted siblings, preflight green.
8. Timing: tool first, then Power; power-cycle between sessions.
9. Verify from `expdb`, keep the patched image, the stock image and this
   document — an OTA can bring the screen back.
