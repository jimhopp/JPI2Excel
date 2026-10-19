# JPI2Excel

Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
All rights reserved.

Revision: 13

A Python CLI for validating JP Instruments EDM-700/800 (legacy) and EDM-730
(protocol 2) downloads and exporting flight data to CSV or Excel (`.xlsx`). Version 2 adds optional flight graphs. Application code lives in `src`,
utilities in `pgms`, tests in `tests`, and the original fixtures in `testdata`.
`testdata/EDM730-anon.JPI` is an anonymized EDM-730 fixture built by
`pgms/make_edm730_fixture.py`.

## Run from this checkout

Requires Python 3.10+, `openpyxl==3.1.5`, and JPI-Parser. The development launcher
can read the existing sibling `../JPI-Parser` checkout at commit
`e1a34c37d3cc2194699faba92e6666300cb85e86`; it verifies the revision and does not
write bytecode or change that repository.

```sh
python3 pgms/jpi2excel.py --help
python3 pgms/jpi2excel.py --list testdata/U260919.JPI
python3 pgms/jpi2excel.py --validate testdata/*.JPI
python3 pgms/run_tests.py --verbose
```

For a standalone installation, create a virtual environment and run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/jpi2excel --help
```

Installation retrieves the exact JPI-Parser commit pinned in `pyproject.toml`.
The development launcher also works with an installed dependency.

## Export

For inputs that pass validation:

```sh
python3 pgms/jpi2excel.py --csv --flights 415,416:418 --minimum-duration 0 --output-dir /existing/output data.JPI
python3 pgms/jpi2excel.py --xls --graphs --output flights.xlsx first.JPI second.JPI
python3 pgms/jpi2excel.py --xls-separate --minimum-duration 0 --output-dir /existing/output data.JPI
python3 pgms/jpi2excel.py --info data.JPI
```

`--info` is an action that can run alone or alongside one other action. For example:

```sh
./pgms/jpi2excel.sh --info --flights 418 testdata/U260919.JPI
./pgms/jpi2excel.sh --info --csv --flights 418 --output flight418.csv testdata/U260919.JPI
```

`--flights` limits per-flight info while file-level properties and counts remain
complete. Info can inspect short flights. Export duration rules still apply when
an export action is also requested. All actions other than `--info` remain mutually
exclusive.

The default cutoff is **5 minutes**. Explicitly selecting a shorter flight is an
error; use a lower cutoff to include it. `Delta T` is always elapsed **seconds**,
and sample numbering starts at 1. CSV files and flight worksheets share the same
column order. Existing destinations are never overwritten.

Combined workbooks contain a Summary sheet and a sheet per selected flight.
Separate workbooks contain one flight sheet and a hidden Summary sheet supplying
conditional-formatting limits. With `--graph` (alias `--graphs`),
each Flight sheet is immediately followed by its Graph sheet with exhaust and
cylinder temperature charts, FF/RPM secondary axes, and red alarm limits.
Graph X values are Delta T seconds, with proportional time spacing.
Graph options are invalid with CSV and ignored without an XLSX export.
See [graphing details and future multi-engine requirements](docs/Graphing.md). Row 1 and columns A/B are frozen.
Autofilters and cell comments are disabled. Info/Summary properties identify units.
Datetimes display through seconds. Column widths follow the data type, including
a wider Limits column. Summary has Source, Property, and Value columns; Value wraps.
Flight sheets highlight readings at or above high limits with light
red fill/dark red text and readings at or below low limits with yellow fill/dark yellow
text. Rules reference the appropriate Summary cells; blank readings stay uncolored.
Flights with such readings have yellow tabs; affected sensor headers have red text.
Those tab/header indicators reflect values and limits at export time.
Opening window width follows `data/t4.xlsx` (36,860 twips); height and position
follow `data/t2.xlsx`.
Headings use Delta T, % HP, and Mark. Flight widths are Sample 50 pixels,
Delta T 44, DateTime 115, Limits 125, CHT and supporting sensors 53, and MAP/RPM,
EGT/TIT/navigation 55. See [conditional formatting](docs/ConditionalFormatting.md).
Navigation columns, when available, appear last; latitude and longitude are decimal
degrees. Binary decoding is limited to legacy single-engine 700/800 layouts and
protocol-2 EDM-730 layouts with fuel code 0 (US gallons); other layouts fail explicitly.
Channels are exported as recorded, including enabled but unconnected inputs such as
an EDM-730's FF2. Zero-length `$D` entries are skipped with a warning. When an
EDM-730's configuration says `carbureted="1"`, the channel JPI-Parser calls CDT is
exported as CRB (carburetor temperature), as in EZTrends.
The exporter/data model are prepared for additional sensors and engine identity.

## Current fixture finding

All three original fixtures now pass strict validation. For the supported legacy
layout, `$D` entries give logical flight allocations, while `$L` gives the binary
area's physical length in 256-byte blocks. The unused portion of the final block
is 200 bytes in `U260731.JPI`, 196 in `U260828.JPI`, and 224 in `U260919.JPI`.

The parser verifies `$L == ceil(logical_bytes / 256)` and requires `$E` at that
physical boundary. It decodes only the `$D` allocations. The unused bytes may be
nonzero or resemble records; they do not create flight samples. Block lengths,
boundaries, and slack counts appear in `--info` and the workbook Summary.

Invalid framing and bad checksums still reject the affected input with `EILSEQ`,
while processing continues for other inputs. The original files remain unchanged.
Tests read the originals directly and verify that sample counts, sensor values,
and timestamps match the pre-change declared-flight baselines. See
[the trailing-data conclusions](docs/JPI-Trailing-Data-Summary.md) for the evidence.
No comparison with JPI's Windows software has been performed.

The suite covers strict corruption handling, the three declared-block baselines,
dense sensor reconstruction, repeats, seconds-based timing, alarm labels, duplicate
flight IDs, CLI errors, and CSV/XLSX agreement.

## Documentation and attribution

- [Command and output specification](docs/PgmSpec.txt)
- [Architecture and project notes](docs/JPI-Project-Notes.md)
- [Format observations and regression findings](docs/JPI-Format.md)

JPI-Parser is an MIT-licensed dependency by
[unicornlines](https://github.com/unicornlines/JPI-Parser). JPI2Excel imports its
decoder and metric definitions; the compatibility adapter also contains adapted
decoder orchestration with the original MIT notice.
See [third-party attribution](docs/THIRD-PARTY.md). Project-specific material carries the notice in
[COPYRIGHT](COPYRIGHT); upstream-derived portions retain the MIT license.
