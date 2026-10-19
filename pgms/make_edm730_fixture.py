#!/usr/bin/env python3
# Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
# All rights reserved.

"""Revision: 2. Build an anonymized protocol-2 (EDM-730) regression fixture.

Copies selected flights from private EDM-730 downloads into one new file and
removes aircraft-identifying content: the tail number becomes TEST730, the XML
configuration block (which holds the tail number) becomes a stub keeping only
the first source's carbureted attribute, each flight's
starting latitude/longitude moves to N45 W100, and every nonzero LAT/LNG delta
byte becomes 1 (signs kept). Engine, fuel, SPD and ALT bytes are unchanged.
Record checksums are recomputed after the GPS bytes change.

Each SOURCE is FILE.JPI:FLIGHT. A Z suffix (e.g. U260726.JPI:747Z) adds a
zero-length $D entry with that flight number instead of copying the flight.
"""
import argparse
from functools import reduce
from operator import xor
from pathlib import Path
import re

FAKE_LAT, FAKE_LNG = 45 * 6000, -100 * 6000
HEADER_LENGTH = 29
GPS_BYTES = {(10, 1), (10, 2), (10, 6), (10, 7)}   # LAT/LNG lo and hi delta bytes


def dollar(body):
    return f"${body}*{reduce(xor, body.encode('ascii'), 0):02X}\r\n".encode('ascii')


def records(raw):
    """Yield (kind, values, end) for each ASCII record up to and including $L."""
    ptr = raw.index(b'$U,')
    while True:
        end = raw.index(b'\r\n', ptr) + 2
        body = raw[ptr + 1:end - 2].rsplit(b'*', 1)[0].decode('ascii')
        kind, *values = body.split(',')
        yield kind, [v.strip() for v in values], end
        if kind == 'L':
            return
        ptr = end


def walk_record(block, ptr):
    """Return (end, offsets of GPS delta bytes) for the 16-bit-mask record at ptr."""
    word1 = int.from_bytes(block[ptr:ptr + 2], 'big')
    if word1 != int.from_bytes(block[ptr + 2:ptr + 4], 'big'):
        raise ValueError(f'mask mismatch at flight byte {ptr}')
    ptr += 5                                      # two mask words + repeat count
    present = [i for i in range(16) if word1 & (1 << i)]
    ctl = {}
    for i in present:
        ctl[i] = block[ptr]
        ptr += 1
    ptr += sum(1 for i in present if i < 6 or i > 7)   # sign bytes
    gps = []
    for i in present:
        for bit in range(8):
            if ctl[i] & (1 << bit):
                if (i, bit) in GPS_BYTES:
                    gps.append(ptr)
                ptr += 1
    if ptr >= len(block):
        raise ValueError('record runs past allocation')
    return ptr + 1, gps                           # checksum byte


def extract_flight(path, fid):
    raw = Path(path).read_bytes()
    directory, ptr = [], None
    for kind, values, end in records(raw):
        if kind == 'D':
            directory.append((int(values[0]), int(values[1]) * 2))
        ptr = end
    for number, allocation in directory:
        if not allocation:
            continue
        block = raw[ptr:ptr + allocation]
        offset = HEADER_LENGTH
        while len(block) - offset > 1:
            offset, _ = walk_record(block, offset)
        if number == fid:
            return bytearray(block[:offset])
        ptr += offset
    raise SystemExit(f'{path}: flight {fid} not found')


def anonymize(flight):
    if len(flight) < HEADER_LENGTH or sum(flight[:HEADER_LENGTH]) % 256:
        raise SystemExit('unexpected flight header')
    flight[12:16] = FAKE_LAT.to_bytes(4, 'big', signed=True)
    flight[16:20] = FAKE_LNG.to_bytes(4, 'big', signed=True)
    flight[HEADER_LENGTH - 1] = 0
    flight[HEADER_LENGTH - 1] = -sum(flight[:HEADER_LENGTH]) % 256
    ptr = HEADER_LENGTH
    while ptr < len(flight):
        end, gps = walk_record(flight, ptr)
        for offset in gps:
            if flight[offset]:
                flight[offset] = 1
        flight[end - 1] = 0
        flight[end - 1] = -sum(flight[ptr:end]) % 256
        ptr = end
    return bytes(flight)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('output', type=Path, help='fixture file to write')
    parser.add_argument('sources', nargs='+', metavar='SOURCE', help='FILE.JPI:FLIGHT or FILE.JPI:FLIGHTZ')
    args = parser.parse_args()
    first = Path(args.sources[0].split(':')[0]).read_bytes()
    keep = {k: v for k, v, _ in records(first) if k in 'AFTCPH'}
    if first[first.index(b'$C,'):].split(b',')[1].strip() != b'730' or keep['P'] != ['2']:
        raise SystemExit('first source is not an EDM-730 protocol-2 download')
    trailer = first[first.rindex(b'$V,'):]
    start = first.index(b'$E,4*5D\r\nJPI') + 12
    xml = bytes(b ^ 2 for b in first[start:first.rindex(b'$E,4*5D\r\n$V,')]).decode('utf-8-sig')
    carbureted = re.search(r'<EDM\b[^>]*\bcarbureted="([^"]*)"', xml)
    attribute = f' carbureted="{carbureted[1]}"' if carbureted else ''
    entries, blocks = [], []
    for source in args.sources:
        path, flight = source.rsplit(':', 1)
        match = re.fullmatch(r'(\d+)(Z?)', flight)
        if not match:
            raise SystemExit(f'bad SOURCE {source}')
        fid = int(match[1])
        block = b'' if match[2] else anonymize(extract_flight(path, fid))
        entries.append(f'D, {fid}, {(len(block) + 1) // 2}')
        blocks.append(block)
    halfsizes = sum((len(b) + 1) // 2 for b in blocks)
    # Original record order and leading-space style; $H and $P copied verbatim.
    lines = ['U,TEST730', 'A, ' + ', '.join(keep['A']), 'F,' + ','.join(keep['F']),
             'T, ' + ', '.join(keep['T']), 'C,' + ','.join(keep['C']),
             'P, ' + keep['P'][0], 'H,' + keep['H'][0], *entries,
             f'L, {(2 * halfsizes + 255) // 256}']
    stub = f'\ufeff<edm_cfg><EDM{attribute}/></edm_cfg>'
    config = b'JPI' + bytes(b ^ 2 for b in stub.encode('utf-8'))
    out = (b''.join(dollar(line) for line in lines) + b''.join(blocks)
           + dollar('E,4') + config + dollar('E,4') + trailer)
    args.output.write_bytes(out)
    print(f'wrote {args.output} ({len(out)} bytes)')


if __name__ == '__main__':
    main()
