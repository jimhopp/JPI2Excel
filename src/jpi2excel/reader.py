# Project-specific additions:
# Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
# All rights reserved.
#
# Portions adapted from unicornlines/JPI-Parser,
# jpi_analyzer/decoder.py, pinned commit
# e1a34c37d3cc2194699faba92e6666300cb85e86.
# Those upstream-derived portions retain the following license:
#
# MIT License
#
# Copyright (c) 2026 Unicornlines
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Revision: 4. Strict legacy validation around the pinned MIT JPI-Parser.

Binary delta unpacking and metric definitions remain upstream. This adapter
checks boundaries/checksums, makes running totals dense, and normalizes metadata.
"""
from datetime import datetime
from functools import reduce
from operator import xor
from pathlib import Path
import re

from jpi_analyzer.decoder import FlightDecoder, DecodedFlight, _ByteReader
from jpi_analyzer.parser import JpiFile, FlightRecord
from jpi_analyzer.metrics import headers_for_model

from . import __version__, UPSTREAM_REVISION
from .model import DataError, Download, Flight, UnsupportedError


class CheckedReader(_ByteReader):
    def byte(self):
        value = super().byte()
        if value < 0:
            raise DataError(f'Truncated binary record at byte {self.ptr}')
        return value

    def word(self):
        return (self.byte() << 8) | self.byte()


class LegacyDecoder(FlightDecoder):
    @staticmethod
    def _decode_date_time(date_word, time_word):
        # DOS-style packing: seconds are bits 0-4 doubled, matching EZTrends.
        # Upstream reads time_word & 62 (bits 1-5, including the minute's low
        # bit) and treats time word zero as absent, but it represents midnight.
        if date_word <= 0:
            return None
        year = (date_word >> 9) & 127
        try:
            return datetime((2000 if year < 75 else 1900) + year,
                            (date_word >> 5) & 15, date_word & 31, time_word >> 11,
                            (time_word >> 5) & 63, (time_word & 31) * 2)
        except ValueError:
            return None

    def unpack(self):
        reader = CheckedReader(self.flight.data)
        out = DecodedFlight(self.flight.id)
        self._scan_flight_header(reader, out)
        block = self.flight.data
        self.checksum(block[:reader.ptr], 'flight header')
        if int.from_bytes(block[:2], 'big') != self.flight.id:
            raise DataError('Flight ID does not match directory')
        if self.cfg_interval <= 0 or self.start_datetime is None:
            raise DataError('Invalid flight timestamp or recording interval')
        # Reject invalid date/time fields instead of upstream's fallback/rollover.
        date_word, time_word = int.from_bytes(block[10:12], 'big'), int.from_bytes(block[12:14], 'big')
        if (not date_word or ((time_word >> 11) & 31) > 23
                or ((time_word >> 5) & 63) > 59 or (time_word & 31) > 29):
            raise DataError('Invalid packed flight date/time')
        self.headers = headers_for_model(self.jpi.model, block[6], False, False)
        self.active_headers = [h for h in self.headers if h.code == 'DIF' or self._cfg_enabled(h)]
        self.running_total = {h.code: (0.0 if h.code == 'HP' else 240.0) for h in self.headers}
        series = {h.code: [] for h in self.active_headers}
        elapsed, seen, previous = [], set(), None
        interval = self.cfg_interval
        next_time = 0

        def append(values):
            nonlocal next_time
            elapsed.append(next_time)
            next_time += interval
            for code in series:
                series[code].append(values.get(code))

        while reader.ptr < len(block):
            # $D sizes count words; observed legacy blocks have an arbitrary
            # single alignment byte. It is not part of a checksummed record.
            if len(block) - reader.ptr == 1:
                break
            offset = reader.ptr
            values, repeats = self._read_one_record(reader)
            if values is None:
                raise DataError(f'Invalid record masks at flight byte {offset}')
            self.checksum(block[offset:reader.ptr], f'record at flight byte {offset}')
            if repeats and previous is None:
                raise DataError('Repeat count appears before the first sample')
            if previous is not None:
                for _ in range(repeats):
                    append(previous)
            # Upstream emits None for a zero delta. Once initialized, unchanged
            # channels retain their running values; entirely absent channels do not.
            for code, value in values.items():
                if value is not None and code != 'DIF':
                    seen.add(code)
            dense = {}
            for metric in self.active_headers:
                code = metric.code
                if code == 'DIF':
                    continue
                dense[code] = (self.running_total[code] / metric.scale_val if code in seen else None)
                if code == 'MARK' and dense[code] is not None:
                    dense[code] = int(self.running_total[code]) & 7
            egts = [value for code, value in dense.items() if re.fullmatch(r'E\d+', code)]
            dense['DIF'] = max(egts) - min(egts) if egts and all(v is not None for v in egts) else None
            # MARK transitions select fast recording. Repeated rows retain the
            # preceding interval; the transition affects the next sample spacing.
            mark = dense.get('MARK')
            old_mark = previous.get('MARK') if previous else None
            if mark != old_mark:
                if mark in (2, 4):
                    interval = 1
                elif mark in (3, 5):
                    interval = self.cfg_interval
            append(dense)
            previous = dense
        if not elapsed:
            raise DataError('Flight has no complete samples')
        return Flight(self.flight.id, Path(self.jpi.path), self.start_datetime,
                      self.cfg_interval, out.horsepower_setting, block[6],
                      series, elapsed, self.cfg_word[:2])

    def checksum(self, data, description):
        value = reduce(xor, data, 0) if self.use_xor_checksum else sum(data) % 256
        if value:
            raise DataError(f'Invalid {description} checksum')


def dollar_record(raw, offset):
    end = raw.find(b'\r\n', offset)
    if end < 0:
        raise DataError(f'Unterminated dollar record at byte {offset}')
    line = raw[offset:end]
    match = re.fullmatch(rb'\$([^*\r\n]+)\*([0-9A-Fa-f]{2})', line)
    if not match:
        raise DataError(f'Malformed dollar record at byte {offset}')
    body, expected = match.groups()
    if reduce(xor, body, 0) != int(expected, 16):
        raise DataError(f'Invalid ASCII checksum at byte {offset}')
    try:
        text = body.decode('ascii')
    except UnicodeDecodeError as exc:
        raise DataError('Non-ASCII dollar header') from exc
    return text, end + 2


def read_jpi(path):
    path = Path(path)
    raw = path.read_bytes()
    start = raw.find(b'$U,')
    if start < 0 or any(raw[:start]):
        raise DataError('Missing $U header or unexpected leading bytes')
    ptr, headers, fields, directory = start, [], {}, []
    while ptr < len(raw):
        text, ptr = dollar_record(raw, ptr)
        headers.append('$' + text)
        kind, *values = text.split(',')
        if kind in fields and kind != 'D':
            raise DataError(f'Duplicate ${kind} header')
        fields[kind] = values
        if kind == 'D':
            try:
                fid, size = map(int, values)
            except ValueError as exc:
                raise DataError('Malformed flight directory') from exc
            if not 0 <= fid <= 65535 or size < 8 or any(f == fid for f, _ in directory):
                raise DataError('Invalid or duplicate flight directory entry')
            directory.append((fid, size * 2))
        if kind == 'L':
            break
    if not {'U', 'A', 'F', 'T', 'C', 'D', 'L'} <= fields.keys():
        raise DataError('Missing required dollar header records')
    try:
        config = list(map(int, fields['C']))
        fuel = list(map(int, fields['F']))
        alarms = list(map(int, fields['A']))
        timestamp = list(map(int, fields['T']))
        if len(config) != 5 or len(fuel) < 1 or len(timestamp) != 6:
            raise UnsupportedError('Unrecognized legacy header layout')
        model, firmware = config[0], config[-1]
        if model not in (700, 800) or 'P' in fields:
            raise UnsupportedError(f'Model {model}/protocol layout is not yet supported; initial support is legacy single-engine EDM-700/800')
        if len(alarms) != 8:
            raise UnsupportedError('Unrecognized legacy alarm layout (expected eight fields)')
        if fuel[0] != 0:
            raise UnsupportedError(f'Fuel unit code {fuel[0]} has not yet been validated; raw metadata retained in source')
        # Legacy $D entries allocate logical flights in words; $L counts the
        # physical 256-byte blocks. Validate framing before decoding any flight.
        if len(fields['L']) != 1 or not re.fullmatch(r'[0-9]+', fields['L'][0].strip()):
            raise DataError('Malformed $L block count: expected one nonnegative integer')
        block_count = int(fields['L'][0])
        block_size = 256
        data_start = ptr
        logical_length = sum(size for _, size in directory)
        expected_blocks = (logical_length + block_size - 1) // block_size
        if block_count != expected_blocks:
            raise DataError(f'Invalid $L block count {block_count}: expected {expected_blocks} '
                            f'for {logical_length} bytes of $D flight allocations')
        logical_end = data_start + logical_length
        physical_length = block_count * block_size
        physical_end = data_start + physical_length
        if not raw.startswith(b'$E,', physical_end):
            raise DataError(f'Missing $E marker at physical binary end (byte {physical_end}, '
                            f'$L={block_count}); truncated or inconsistent legacy framing')
        trailer, end = dollar_record(raw, physical_end)
        if trailer != 'E,4' or end != len(raw):
            raise UnsupportedError('Unrecognized legacy trailer or trailing configuration')
        jpi = JpiFile(path=str(path), raw=raw, header_offset=start)
        jpi._parse_dollar_records()
        if jpi.file_created_at is None:
            raise DataError('Invalid download timestamp')
        flights = []
        for fid, size in directory:
            block = raw[ptr:ptr + size]
            if len(block) != size or len(block) < 15:
                raise DataError(f'Truncated flight {fid}')
            if block[6] != fuel[0]:
                raise UnsupportedError(f'Flight {fid} fuel units differ from the download header')
            rec = FlightRecord(fid, size, ptr, True, block)
            try:
                flights.append(LegacyDecoder(jpi, rec).unpack())
            except DataError as exc:
                raise DataError(f'Flight {fid}: {exc}') from exc
            ptr += size
        # [logical_end, physical_end) is unused final-block space, not flight
        # data. Its contents are unrestricted, even if they resemble records or
        # $E markers. Never scan it for recoverable samples or validate records.
    except (ValueError, IndexError, OverflowError) as exc:
        raise DataError(f'Invalid metadata or binary structure: {exc}') from exc
    alarm_limits = {'BAT': (alarms[1]/10, alarms[0]/10), 'DIF': (None, alarms[2]),
                    'CHT': (None, alarms[3]), 'CLD': (-abs(alarms[4]), None),
                    'TIT': (None, alarms[5]), 'OILT': (alarms[7], alarms[6])}
    metadata = {'Source file': path.name, 'Aircraft ID': jpi.tail_number,
                'Download datetime': jpi.file_created_at, 'Model code': str(model),
                'Firmware version': firmware, 'Protocol': 'Legacy (no $P)',
                'Engine count': 1, 'Engine temperature units': jpi.eng_deg,
                'OAT temperature units': jpi.oat_deg, 'Fuel units': 'US gallons',
                'Fuel flow units': 'US gallons/hour', 'Fuel unit code': fuel[0],
                'Configuration words ($C)': ', '.join(map(str, config[1:])),
                'Fuel configuration ($F)': ', '.join(map(str, fuel)),
                'File size (bytes)': len(raw), 'Total flights': len(flights),
                'Binary data offset (bytes)': data_start,
                'Logical binary length (bytes)': logical_length,
                'Logical binary end offset (bytes)': logical_end,
                'Binary block size (bytes)': block_size,
                'Binary block count ($L)': block_count,
                'Physical binary length (bytes)': physical_length,
                'Physical binary end offset (bytes)': physical_end,
                'Block slack length (bytes)': physical_end - logical_end,
                'Block slack nonzero': any(raw[logical_end:physical_end]),
                'Validation': 'Passed', 'JPI2Excel version': __version__,
                'JPI-Parser revision': UPSTREAM_REVISION}
    warnings = []
    for flight in flights:
        missing = [code for code, values in flight.series.items() if all(v is None for v in values)]
        if missing:
            warnings.append(f'Flight {flight.id}: header-declared channels have no values: {", ".join(missing)}')
    return Download(path, metadata, headers, flights, alarm_limits, warnings)
