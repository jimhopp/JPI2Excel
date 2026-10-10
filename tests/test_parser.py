# Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
# All rights reserved.

"""Revision: 4. Regression contracts established before decoder changes."""
import tempfile
import unittest
from pathlib import Path

from jpi2excel.model import DataError
from jpi2excel.reader import read_jpi

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "testdata"


def dollar(body):
    check = 0
    for value in body.encode("ascii"):
        check ^= value
    return f"${body}*{check:02X}\r\n".encode("ascii")


def data_start(raw):
    return raw.index(b'\r\n', raw.index(b'$L,')) + 2


def synthetic_file(records=None, *, interval=2, cfg=(0xF8FD, 0x7FB1)):
    # A complete, checksummed legacy file with one initialized EGT and repeats.
    # E1 delta +10 from the format's 240 baseline; then unchanged, then +5.
    if records is None:
        records = [bytes([1, 1, 0, 1, 0, 10, 243]), bytes(4),
                   bytes([1, 1, 2, 1, 0, 5, 246])]
    date = (26 << 9) | (9 << 5) | 17
    time = (18 << 11) | (2 << 5) | 2
    hdr = b''.join(n.to_bytes(2, 'big') for n in (415, *cfg))
    hdr += bytes([0, 208]) + b''.join(n.to_bytes(2, 'big') for n in (interval, date, time))
    hdr += bytes([-sum(hdr) % 256])
    block = hdr + b''.join(records)
    if len(block) % 2:
        block += b'\x00'
    lines = ['U,TEST', 'A,305,240,500,400,200,1700,220,95',
             'F,0,40,35,8300,8300', 'T,9,19,26,20,48,4795',
             'C,700,63741,32689,1556,306', f'D,415,{len(block)//2}', f'L,{(len(block)+255)//256}']
    slack = bytes(-len(block) % 256)
    return b''.join(dollar(s) for s in lines) + block + slack + dollar('E,4')


class ParserTests(unittest.TestCase):
    def parse(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.JPI'
            path.write_bytes(data)
            return read_jpi(path)

    def test_dense_deltas_repeats_seconds_and_missing_channels(self):
        data = self.parse(synthetic_file())
        flight = data.flights[0]
        self.assertEqual(flight.series['E1'], [250, 250, 250, 250, 255])
        self.assertEqual(flight.elapsed, [0, 2, 4, 6, 8])
        self.assertEqual(flight.series['C1'], [None] * 5)
        self.assertTrue(any('C1' in warning for warning in data.warnings))
        self.assertEqual(data.alarms['BAT'], (24.0, 30.5))
        self.assertEqual(data.alarms['CLD'], (-200, None))
        self.assertEqual(data.metadata['Model code'], '700')

    def test_ascii_checksum_rejected(self):
        data = synthetic_file().replace(b'U,TEST', b'U,BEST')
        with self.assertRaises(DataError):
            self.parse(data)

    def test_binary_header_checksum_rejected(self):
        data = bytearray(synthetic_file())
        offset = data_start(data)
        data[offset + 7] ^= 1
        with self.assertRaises(DataError):
            self.parse(data)

    def test_record_checksum_rejected(self):
        bad = bytes([1, 1, 0, 1, 0, 10, 242])
        with self.assertRaises(DataError):
            self.parse(synthetic_file([bad]))

    def test_mismatched_record_masks_rejected(self):
        with self.assertRaises(DataError):
            self.parse(synthetic_file([bytes([1, 2, 0, 1, 0, 10, 242])]))

    def test_truncated_record_rejected(self):
        with self.assertRaises(DataError):
            self.parse(synthetic_file([bytes([1, 1, 0, 255])]))

    def test_missing_footer_rejected(self):
        with self.assertRaises(DataError):
            self.parse(synthetic_file()[:-9])

    def test_invalid_interval_rejected(self):
        with self.assertRaises(DataError):
            self.parse(synthetic_file(interval=0))

    def test_duplicate_directory_id_rejected(self):
        original = synthetic_file()
        directory = next(line + b'\r\n' for line in original.split(b'\r\n') if line.startswith(b'$D'))
        with self.assertRaises(DataError):
            self.parse(original.replace(directory, directory * 2))

    def test_unexplained_trailer_is_not_silently_ignored(self):
        original = synthetic_file().replace(dollar('E,4'), b'garbage' + dollar('E,4'))
        with self.assertRaises(DataError):
            self.parse(original)

    def test_original_fixtures_match_declared_flight_counts(self):
        # Parse original files directly, including their physical block slack.
        expected = {'U260731.JPI': [4872, 3547],
                    'U260828.JPI': [1430,1470,885,679,1348,1299,1683,1209],
                    'U260919.JPI': [724,1008,33,5507]}
        for name, counts in expected.items():
            with self.subTest(name=name):
                result = read_jpi(FIXTURES / name)
                self.assertEqual([f.samples for f in result.flights], counts)
                self.assertEqual(result.flights[0].cylinder_count, 6)
                self.assertEqual(result.flights[0].tit_count, 1)
                self.assertNotIn('LAT', result.flights[0].series)
                if name == 'U260919.JPI':
                    self.assertEqual(str(result.flights[0].start), '2026-09-17 18:01:54')
                    # Matches JPI EZTrends' CSV export of flight 418.
                    self.assertEqual(str(result.flights[3].start), '2026-09-19 17:06:12')
                    self.assertEqual(result.flights[0].elapsed[-1], 1446)
                    self.assertEqual(result.flights[0].series['E1'][:3], [898,905,912])
