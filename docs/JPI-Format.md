# JPI File Format Notes

Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
All rights reserved.

**Revision:** 8
**Revision date:** 2026-10-12
**Project:** JPI2Excel

## Revision history

| Revision | Date | Summary |
|---|---|---|
| 1 | 2026-09-23 | Initial notes on the ASCII header, binary flight blocks, delta compression, sample file, units, validation, and upstream JPI-Parser output. |
| 2 | 2026-09-27 | Added legacy EDM-800 `$A` alarm mapping, GPS/altitude findings, twin-engine representation, and current upstream-parser limitations. |
| 3 | 2026-09-28 | Added initial observations that the three legacy fixtures contain bytes between the end implied by the `$D` directory entries and the `$E` marker; interpretation remained unresolved. |
| 4 | 2026-09-28 | Identified the `$L` value as a 256-byte binary-block count for all three legacy fixtures; reclassified the bytes after the logical `$D` data as final-block slack rather than additional flight data; added validation and implementation rules. |
| 6 | 2026-10-09 | Added section 14.1: flight start time uses DOS-style packing with seconds in bits 0-4 doubled, verified against EZTrends; upstream JPI-Parser's `time_word & 62` is wrong. |
| 7 | 2026-10-12 | Added section 25: protocol-2 EDM-730 header, flight packing, trailer, channel, GPS, and timestamp findings, checked against EZTrends exports. |
| 8 | 2026-10-12 | Added section 25.10: JPI2Excel protocol-2 decoding rules, the DIF rule for unused EGT inputs, and the anonymized fixture. |

## Status and evidence

These notes summarize the current understanding of JP Instruments `.JPI` files relevant to JPI2Excel.

Primary reverse-engineering reference:

- `unicornlines/JPI-Parser`
- upstream `filespec.md`
- JPI-Parser commit used during the local investigation:
  `e1a34c37d3cc2194699faba92e6666300cb85e86`

Official JPI Pilot's Guide material is also useful where it documents user-visible configuration semantics, especially alarm programming.

The principal real-world legacy fixtures currently available are:

```text
U260731.JPI
U260828.JPI
U260919.JPI
```

All three are from the same apparent legacy EDM-700/800 family and share:

```text
$C model code: 700
software value: 306
```

`U260919.JPI` is known to have been downloaded from an EDM-800.

The conclusions about `$L` in Revision 4 are based on exact arithmetic relationships in all three fixtures. The interpretation of the residual bytes as stale prior contents of a reused 256-byte block is strongly supported but remains an inference rather than an explicitly documented JPI rule.

---

## 1. High-level legacy file layout

For the three legacy fixtures, the file layout is:

```text
ASCII header
    |
    |-- $D entries describe logical flight allocations in 16-bit words
    |-- $L gives the physical binary-area length in 256-byte blocks
    v
binary area of exactly ($L * 256) bytes
    |
    |-- declared flight blocks, totaling 2 * sum($D sizes) bytes
    |-- final-block slack, if the declared data do not fill the last 256-byte block
    v
$E,4*5D\r\n
EOF
```

These files contain no bytes after `$E`, no `$V` trailer, and no trailing configuration XML.

Later JPI formats may contain additional header records and/or later-format sections. Do not generalize this exact legacy layout to every JPI model without evidence.

---

## 2. ASCII header records

The legacy ASCII header uses CRLF-terminated records such as:

```text
$U,...
$A,...
$F,...
$T,...
$C,...
$D,...
$L,...
```

Records use NMEA-like XOR checksums: XOR the bytes between `$` and `*`, then compare with the hexadecimal checksum after `*`.

Later files may additionally contain records such as `$P`, `$H`, and `$I`.

The byte immediately following the `$L` record's CRLF is the first byte of the binary area. Call this offset:

```text
data_start
```

---

## 3. `$U` — aircraft/device identifier

Example:

```text
$U,N2FR___*4E
```

This field may contain aircraft-identifying information and should be treated as potentially private data.

---

## 4. `$A` — alarm/limit configuration

The legacy EDM-800 sample contains:

```text
$A,305,240,500,400,200,1700,220,95*68
```

For this legacy EDM-800, the field order matches the alarm-programming sequence documented by JPI:

| Index | Sample | Legacy EDM-800 meaning |
|---:|---:|---|
| 1 | 305 | High battery-voltage alarm; divide by 10 = 30.5 V |
| 2 | 240 | Low battery-voltage alarm; divide by 10 = 24.0 V |
| 3 | 500 | EGT differential (`DIF`) alarm = 500°F |
| 4 | 400 | High CHT alarm = 400°F |
| 5 | 200 | Cooling-rate (`CLD`) magnitude = 200°F/min; operational/display threshold is negative |
| 6 | 1700 | High TIT alarm = 1700°F |
| 7 | 220 | High oil-temperature alarm = 220°F |
| 8 | 95 | Low oil-temperature alarm = 95°F |

The sample `$A` record contains only these eight numeric fields.

Do not invent values for alarm settings that are absent from the file.

The current upstream JPI-Parser does not correctly represent this legacy `$A` layout; JPI2Excel needs a model/format-aware compatibility mapping.

---

## 5. `$F` — fuel-flow unit/configuration

Example:

```text
$F,0, 40, 35,8300,8300*58
```

For the current sample family, the first field `0` corresponds to U.S. gallons / gallons per hour.

Do not assume that fields ignored by the current upstream parser are necessarily meaningless on every model.

---

## 6. `$T` — download date/time

Example:

```text
$T, 9,19,26,20,48, 4795*60
```

For the September fixture this corresponds to:

```text
2026-09-19 20:48:04.795
```

The final numeric field is interpreted as:

```text
seconds      = value // 1000
milliseconds = value % 1000
```

This is a file/download timestamp, not necessarily a flight-start timestamp.

---

## 7. `$C` — model/system configuration

Example:

```text
$C, 700,63741,32689, 1556, 306*4B
```

The first numeric field is a model code.

Known model codes in the reverse-engineered material include single- and twin-engine models such as 700, 711, 730, 740, 760, 790, 800, 830, 831, 900, 930, 950, and 960.

Important observed anomaly:

```text
physical instrument: EDM-800
file model code:     700
software value:      306
```

Do not silently rewrite the recorded model code.

For the sample family, model code 700 and software 306 select the additive binary-record checksum rule under the current reverse-engineered algorithm.

The `$C` configuration words also carry flags affecting available data and unit interpretation.

---

## 8. `$D` — flight-directory entries

A `$D` record has the form:

```text
$D, flight_id, halfsize*checksum
```

The second numeric field is a count of 16-bit words allocated to that flight block.

Therefore:

```text
flight_block_bytes = halfsize * 2
```

and the total logical flight allocation is:

```text
logical_binary_length = 2 * sum(all $D halfsize values)
logical_end = data_start + logical_binary_length
```

The flight block itself contains a binary flight header, compressed records, and in some cases a final one-byte word-alignment pad.

The one-byte per-flight alignment pad, when present, is part of the corresponding `$D` allocation. It is distinct from the final physical block slack described under `$L`.

---

## 9. `$L` — physical binary-area block count

### 9.1 Revision 4 interpretation

For all three legacy fixtures examined, the numeric `$L` value is exactly the number of **256-byte blocks** in the complete binary area between the end of the `$L` ASCII record and the beginning of `$E`.

Define:

```text
physical_binary_length = L_value * 256
physical_end = data_start + physical_binary_length
```

For all three fixtures:

```text
$E_offset == physical_end
```

and:

```text
L_value == ceil(logical_binary_length / 256)
```

Equivalently, because `$D` sizes are in 16-bit words:

```text
L_value == ceil(sum($D halfsize values) / 128)
```

### 9.2 Evidence

| Fixture | `data_start` | Sum of `$D` bytes | `$L` | `$L*256` | `$E` offset | Slack |
|---|---:|---:|---:|---:|---:|---:|
| `U260731.JPI` | 194 | 78,904 | 309 | 79,104 | 79,298 | 200 |
| `U260828.JPI` | 308 | 129,340 | 506 | 129,536 | 129,844 | 196 |
| `U260919.JPI` | 232 | 94,240 | 369 | 94,464 | 94,696 | 224 |

For each row:

```text
$E_offset - data_start == $L * 256
slack == ($L * 256) - logical_binary_length
```

and:

```text
0 <= slack < 256
```

### 9.3 Confidence and scope

Confidence that this is the correct interpretation of `$L` for this legacy family is greater than 99%.

This should nevertheless be implemented as a **legacy format rule validated from the file**, not as an unconditional assumption for every JPI format.

For a candidate legacy file, the parser can accept this framing when all applicable relationships hold.

---

## 10. Final 256-byte block and block slack

The logical `$D` allocations do not necessarily fill the final 256-byte physical block.

For the three fixtures:

| Fixture | Bytes of `$D` allocation in final 256-byte block | Final-block slack |
|---|---:|---:|
| `U260731.JPI` | 56 | 200 |
| `U260828.JPI` | 60 | 196 |
| `U260919.JPI` | 32 | 224 |

Within the first two fixtures, one of the allocated bytes at the end of the last `$D` block is a one-byte word-alignment pad after the last complete record. September ends exactly at a record boundary.

The bytes after `logical_end` and before `physical_end` are **not part of any declared flight**.

Call this interval:

```text
block_slack = [logical_end, physical_end)
```

JPI2Excel must not append these bytes to the last flight merely because some of them can be parsed as record-shaped data.

---

## 11. Why the block slack contains valid-looking records

The block slack is not zero-filled.

Diagnostic scanning found long consecutive runs whose record framing and additive checksums are valid:

| Fixture | Leading fragment before valid run | Valid records | Valid-run bytes | Trailing fragment |
|---|---:|---:|---:|---:|
| `U260731.JPI` | 3 | 16 | 196 | 1 |
| `U260828.JPI` | 4 | 10 | 184 | 8 |
| `U260919.JPI` | 12 | 16 | 206 | 6 |

The absolute valid-run ranges are:

```text
U260731.JPI  [79101, 79297)
U260828.JPI  [129652, 129836)
U260919.JPI  [94484, 94690)
```

The pattern is:

```text
current logical data ends
    |
    v
short non-record fragment
one or more complete checksum-valid legacy records
partial record at the physical 256-byte block boundary
    |
    v
$E
```

This pattern is strongly consistent with **stale contents of a reused 256-byte storage/download buffer**:

1. current flight data overwrite the beginning of a block;
2. writing stops when the declared logical data end;
3. the remainder of the block is not erased;
4. the first surviving old record is usually truncated because its beginning was overwritten;
5. later old records remain intact and checksum-valid;
6. the physical block boundary truncates the final surviving old record.

This explanation is estimated at roughly 95% confidence.

It is stronger than the alternatives of deliberate padding or additional current-flight data, but it is still an inference. The exact source flight/download of the stale bytes cannot be determined safely from these delta records alone.

No exact duplicate of the complete valid slack runs was established elsewhere in the three available files.

---

## 12. `$E` — end marker

All three fixtures end immediately after:

```text
$E,4*5D\r\n
```

The XOR checksum is valid.

For these legacy fixtures, `$E` begins at:

```text
data_start + ($L * 256)
```

not at:

```text
data_start + 2 * sum($D halfsize values)
```

unless those two happen to be equal.

This distinction is essential for strict validation.

---

## 13. Required JPI2Excel boundary behavior

### 13.1 Do not use the old strict rule

The following check is incorrect for these legacy fixtures:

```text
require($E_offset == logical_end)
```

It wrongly rejects all three original files.

### 13.2 Recommended legacy validation

For a legacy candidate with `$D`, `$L`, and `$E`:

```text
logical_binary_length = 2 * sum($D halfsize values)
logical_end = data_start + logical_binary_length

physical_binary_length = $L_value * 256
physical_end = data_start + physical_binary_length

expected_L = ceil(logical_binary_length / 256)
```

Then require or strongly validate:

```text
$L_value == expected_L
$E_offset == physical_end
logical_end <= physical_end
0 <= physical_end - logical_end < 256
```

The declared flight blocks are:

```text
[data_start, logical_end)
```

The final-block slack is:

```text
[logical_end, physical_end)
```

The slack should be ignored for flight decoding.

### 13.3 Conservative compatibility behavior

Because `$L` has been established from only three files of the same apparent legacy family, implementation should avoid forcing this rule onto unrelated later formats.

A reasonable strategy is:

```text
if legacy format and $L relationship validates:
    accept declared $D data
    classify remainder to $E as block slack
else:
    follow the format-specific parser/validator
```

Unexpected relationships should produce a diagnostic or error rather than silently redefining boundaries.

---

## 14. Binary flight representation

The binary flight data are compressed and are not a fixed-width row-major table.

Conceptually:

```text
current_value[sensor] += decoded_delta
```

Each record identifies changed groups/channels, signs, delta magnitudes, repeat behavior, and a checksum.

Unchanged values are reconstructed by retaining accumulated state.

Because decoding is stateful, isolated record-shaped bytes in the block slack cannot safely be assigned absolute sensor values or timestamps without the correct preceding state.

This is another reason not to recover or append slack records.

### 14.1 Flight start date and time

Each flight header carries a packed date word and time word (bytes 10-13 of a legacy flight header), using DOS-style packing:

```text
day    =  date_word        & 0x1F
month  = (date_word >> 5)  & 0x0F
year   = (date_word >> 9)  & 0x7F    (2000 + year when below 75, else 1900 + year)
hour   =  time_word >> 11
minute = (time_word >> 5)  & 0x3F
second = (time_word & 0x1F) * 2
```

Verified against an EZTrends CSV export of flight 418 in `U260919.JPI`: time word `0x88C6` gives 17:06:12, and every sample time matches.

Upstream JPI-Parser at the pinned commit computes `second = time_word & 62`, which reads bits 1-5: it includes the minute's low bit and drops the seconds field's low bit. Its start times are therefore off by between -30 and +32 seconds. JPI2Excel decodes the time itself and rejects a seconds field above 29 rather than rolling over. A fix was proposed upstream as unicornlines/JPI-Parser#3.

A time word of zero is midnight, not a missing time.

---

## 15. Binary checksums

For the current sample family:

```text
model code = 700
software   = 306
```

The reverse-engineered rule selects additive modulo-256 record checksums.

A complete valid record therefore sums to zero modulo 256.

The checksum-valid records in the block slack demonstrate that those bytes once plausibly represented valid records. They do **not** demonstrate that they belong to the current final flight.

---

## 16. GPS, position, groundspeed, and altitude

`U260919.JPI` contains no decoded:

```text
LAT
LNG
ALT
SPD
```

No separate barometric/pressure-altitude channel has been established in that legacy sample.

Do not synthesize altitude from manifold pressure.

Later/protocol-2 JPI formats can contain navigation fields including `LAT`, `LNG`, `ALT`, and `SPD`; JPI2Excel should preserve them when present.

---

## 17. Engine configuration and enabled channels

The legacy format does not provide a normalized descriptive engine record such as:

```text
cylinders=6
turbochargers=1
fuel_system=injected
```

Instead, many installation properties are represented indirectly by enabled sensor-channel bits in the per-flight configuration words.

Examples:

- individual EGT and CHT channels permit an inferred monitored-cylinder count;
- CDT and IAT have separate enable bits;
- TIT1 and TIT2 are separate channels;
- twin-engine models use separate left/right sensor slots.

Distinguish:

```text
explicit file properties
derived channel/configuration properties
external/inferred aircraft-engine properties
```

Do not infer carbureted versus injected or actual turbocharger count solely from the presence/absence of individual channels unless separate evidence supports it.

---

## 18. Twin-engine representation

Twin-capable JPI models represent both engines within the same synchronized flight timeline.

Engine identity is carried by distinct left/right channel slots rather than separate `.JPI` files or separate flight IDs.

A normalized internal representation should support engine-qualified channels such as:

```text
L-EGT1
L-CHT1
L-MAP
L-RPM
...
R-EGT1
R-CHT1
R-MAP
R-RPM
...
```

The current upstream JPI-Parser has only partial twin-engine support and must not be assumed to decode every twin channel correctly without regression fixtures.

---

## 19. Units and scaling

Do not hard-code a single temperature unit.

The file can distinguish engine-temperature and OAT temperature units.

Fuel-related scaling depends on the fuel-unit configuration.

Common fixed-point examples include:

```text
MAP: tenths of inHg
FF:  tenths of GPH for U.S.-gallon configuration
BAT: tenths of volts
```

JPI2Excel should derive units from file metadata/model-aware rules.

---

## 20. Excel normalization

The compressed on-disk representation should not leak into workbook design.

A flight sheet should present a dense chronological table:

```text
DateTime | Elapsed | sensor-1 | sensor-2 | ...
```

Unchanged values should appear as their reconstructed running values.

Block slack must never produce rows in the workbook.

Where navigation fields exist, preserve them.

For twin-engine files, use explicit left/right column names.

---

## 21. Regression expectations for the three legacy fixtures

### 21.1 File-level framing

Tests should assert:

```text
U260731.JPI:
    data_start = 194
    logical_binary_length = 78904
    logical_end = 79098
    L = 309
    physical_binary_length = 79104
    physical_end = E offset = 79298
    block_slack = 200

U260828.JPI:
    data_start = 308
    logical_binary_length = 129340
    logical_end = 129648
    L = 506
    physical_binary_length = 129536
    physical_end = E offset = 129844
    block_slack = 196

U260919.JPI:
    data_start = 232
    logical_binary_length = 94240
    logical_end = 94472
    L = 369
    physical_binary_length = 94464
    physical_end = E offset = 94696
    block_slack = 224
```

For all three:

```text
L == ceil(logical_binary_length / 256)
E_offset == data_start + L*256
0 <= block_slack < 256
```

### 21.2 Logical flight decoding

Tests should continue to assert that:

- only bytes covered by `$D` entries are decoded as flights;
- complete records inside declared blocks pass expected checksums;
- optional 0/1-byte word padding at a declared flight-block end is handled separately;
- slack bytes do not add samples to the final flight;
- nonzero or record-shaped slack does not cause `EILSEQ` merely because `$E` is not at `logical_end`.

### 21.3 Diagnostic slack tests

Optional diagnostics may verify the known record-shaped content in the slack, but those tests must not convert it into exported samples.

---

## 22. Current upstream/JPI2Excel implications

The pinned upstream parser reads the declared `$D` sizes and effectively ignores the remainder before `$E`.

That behavior is safer than appending the slack records, although JPI2Excel's stricter wrapper previously rejected the files because it required `$E` at `logical_end`.

JPI2Excel should change that strict boundary rule to recognize the validated `$L` block framing.

No upstream parser modification is required merely to decode the declared flights correctly.

---

## 23. Rule for future format work

Prefer this order:

1. preserve the original file unchanged;
2. verify ASCII checksums;
3. identify `data_start`;
4. parse `$D` logical allocations;
5. parse `$L`;
6. test the applicable block-framing relationship;
7. identify `$E`;
8. decode only the declared flight ranges;
9. preserve unexpected bytes for diagnostics;
10. compare with upstream JPI-Parser behavior;
11. compare with JPI documentation and JPI's own software output when available;
12. add regression tests before changing parser policy.

Do not recover record-shaped data outside declared flight allocations merely because its framing/checksum is valid.

---

## 24. Remaining uncertainty

The following remain unresolved:

- whether every legacy EDM-700/800 firmware uses `$L` identically;
- whether 256 bytes corresponds directly to an instrument storage page, transfer block, or another internal unit;
- exactly why the unused portion of the last block is not cleared;
- which earlier flight/session produced the surviving stale record bytes;
- whether another legacy model writes a different fill pattern.

These uncertainties do not prevent safe decoding of the three current fixtures.

The file itself provides enough information to distinguish the logical flight data from the physical transfer/storage block boundary.

---

## 25. Protocol-2 single-engine files (EDM-730)

### 25.1 Evidence

Seven downloads from one EDM-730 (firmware 1.40, build 2014, beta 4), containing 37 non-empty flights, plus JPI EZTrends CSV exports of two of those flights (one of 1,791 samples, one of 3 samples).

These files identify the aircraft and are not committed. Regression fixtures derived from them must be anonymized (see 25.5).

### 25.2 ASCII header

Record order observed in all seven files:

```text
$U, $A, $F, $T, $C, $P, $H, $D..., $L
```

Differences from the legacy family:

- Fields carry leading spaces, e.g. `$D, 735, 77`.
- `$C` has nine fields: `$C,730,63741,22657,1536,17634,120,140,2014,4`. The first is the model code (730). Upstream reads the last three as software version (140, i.e. 1.40), build (2014), and beta (4); this matches the `$V` trailer. The meaning of the middle words beyond upstream's unit flags is unconfirmed.
- `$P, 2` declares protocol 2. Upstream treats `$P` as selecting the wide flight header and 16-bit record masks.
- `$H,0` is present. Its meaning is unknown.
- `$F,0,50,9999,2168,2990` matches the instrument's settings: fuel units (0 = gallons), main tank (50), aux tank (9999), and K-factors 21.68 and 29.90 (stored ×100).
- `$A` keeps eight fields.

### 25.3 Flight directory and packing

`$D` gives each flight's length in 16-bit words, rounded **up**:

```text
$D halfsize = ceil(actual_flight_bytes / 2)
```

Flights are packed back to back with **no** alignment pad. A flight with an odd byte length therefore ends one byte before its `$D` allocation, and the next flight starts there. Across 37 flights: 19 even-length flights fill their allocation exactly; 18 odd-length flights are one byte short. Starting offsets drift 0–4 bytes earlier than the cumulative `$D` sizes predict.

This differs from the legacy family, where the pad byte sits inside the allocation (section 8). A protocol-2 reader must locate each flight by its actual decoded length, not by cumulative `$D` sizes.

A `$D` entry may have size 0 (one file). EZTrends does not list such a flight. JPI2Excel skips it and reports a warning.

`$L = ceil(2 * sum($D halfsizes) / 256)` holds in all seven files, as in the legacy family.

### 25.4 Trailer

```text
[last flight's final record]
$E,4*5D\r\n
JPI + XOR-0x02-encoded UTF-8 XML configuration (about 10 KB)
$E,4*5D\r\n
$V,Created by EDM730 VER 1.40 BLD 2014 BETA 4*68\r\n
```

The first `$E` immediately follows the last flight's final record. It is **not** at `data_start + $L*256` as in the legacy family.

The configuration block begins with the literal bytes `JPI`; the remaining bytes XOR `0x02` give a UTF-8 byte-order mark and an `<edm_cfg>` XML document. It holds instrument settings **including the tail number**, so it must never be copied into fixtures or exported output. JPI2Excel should treat it as opaque.

### 25.5 Flight header and records

The flight header is 29 bytes: flight ID, five configuration words, a 32-bit signed starting latitude and longitude, fuel-unit byte, horsepower byte, interval word, date word, time word, and a checksum byte. Upstream's `edm_typ_actual` and new-header detection select this layout for all 37 flights.

Records use 16-bit masks and upstream's `HEADERS_107` channel table. All flight headers and all records validate with the additive (`sum % 256`) checksum, which upstream selects for protocol 2.

Anonymized fixtures must replace the tail number, omit the configuration block, and replace the starting latitude/longitude and GPS position deltas.

### 25.6 Comparison with EZTrends

With running totals carried forward across unchanged samples (as the legacy reader already does), every engine and fuel channel equals the EZTrends export at every sample: E1–E4, E6, C1–C6, CLD, carb temperature, FF, FF2, BAT, USD, HRS, and DIF (maximum minus minimum EGT). E5, MAP, and USD2 are blank in both.

Channel naming: upstream's `CDT` is carburetor temperature on this installation; EZTrends labels it `CRB`.

FF2 and USD2 are enabled in the configuration, but the owner confirmed that no second fuel-flow sensor is installed. FF2 reads 0.0 throughout in both JPI2Excel and EZTrends. That value reflects an unconnected channel, not a measured zero flow.

### 25.7 GPS channels

`LAT` and `LNG` are signed integers in units of 1/6000 degree:

```text
raw = degrees * 6000 + minutes * 100 + hundredths_of_minute
```

EZTrends displays them as `N36.53.18`-style degrees.minutes.hundredths. JPI2Excel exports decimal degrees (`raw / 6000`).

EZTrends shows `SPD` and `ALT` as `NA` whenever a record carries a zero delta byte for them, even in steady cruise, and shows `LAT`/`LNG` as `NA` only before the first position fix. JPI2Excel instead carries all GPS values forward once a channel has had a value, consistent with the engine channels.

Values recorded while the GPS acquires a fix (a single-sample position jump, ground-roll speed, altitude settling) also appear in EZTrends. They are data, not decoding errors.

### 25.8 Start timestamp

Protocol-2 flight headers use the same DOS-style time word as legacy files (section 14.1). For both EZTrends-checked EDM-730 flights, `(time_word & 31) * 2` matches EZTrends exactly, while upstream's `time_word & 62` is wrong by +16 s and −14 s.

### 25.9 Remaining uncertainty

- meaning of `$H` and of the unlabeled `$C` configuration words;
- whether other EDM-730 firmware versions, or other protocol-2 models, share this packing and trailer.

### 25.10 JPI2Excel implementation

JPI2Excel accepts protocol-2 files only for model code 730 with `$P,2`, a nine-field `$C`, an eight-field `$A` (same alarm mapping as legacy), and fuel unit code 0. It:

1. requires `$L = ceil(2 * sum($D halfsizes) / 256)`;
2. decodes each flight from its true start, stops when at most one byte of the allocation remains, and requires `ceil(decoded_length / 2) * 2` to equal the allocation;
3. requires upstream to select the 29-byte header and validates the header and every record with the additive checksum;
4. requires `$E,4` directly after the last flight, a configuration block beginning with `JPI`, a second `$E,4`, and a final `$V` record ending the file;
5. initializes `LAT`/`LNG` running totals from the header's starting position and exports them as `raw / 6000` degrees once a nonzero delta has occurred;
6. exports every enabled channel as recorded, including FF2 and USD2.

DIF is the spread of the EGT channels that carry a value somewhere in the flight. The EDM-730 enables E5 but never records it; EZTrends computes DIF from the other EGTs, and so does JPI2Excel. This rule applies to legacy files too; it does not change any legacy fixture output.

The Revision 6 start-time rule (section 14.1) applies unchanged.

`testdata/EDM730-anon.JPI` was built with `pgms/make_edm730_fixture.py` from flights 735, 745, 747 (zero-length) and 749. It replaces the tail number with `TEST730`, replaces the configuration block with a stub, moves each starting position to N45 W100, and sets every nonzero LAT/LNG delta byte to 1, recomputing record checksums. Engine, fuel, SPD and ALT bytes are unchanged, and the regression tests check them against EZTrends values. When the private source downloads are present in `testdata-730/`, the tests also compare every sample of flights 735 and 749, including position, with the EZTrends exports.
