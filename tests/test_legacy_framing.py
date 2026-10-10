# Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
# All rights reserved.

"""Revision: 3. Logical flight allocations versus physical 256-byte blocks."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from jpi2excel.model import DataError, UnsupportedError
from jpi2excel.reader import read_jpi
from test_parser import FIXTURES, data_start, dollar, synthetic_file


class LegacyFramingTests(unittest.TestCase):
    def parse(self, raw):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.JPI'
            path.write_bytes(raw)
            return read_jpi(path)

    def test_original_fixture_boundaries_and_values(self):
        # Digests captured from all declared-flight IDs, starts, elapsed seconds,
        # and sensor series BEFORE changing framing. Source filenames excluded.
        # Recaptured after correcting start seconds; only starts changed.
        expected = {
            'U260731.JPI': (194, 78904, 309, 79298, 200,
                'd2a341c0f1d224667bebf5fb5f3d87bb463c71679a6de0e6d9f0bc229b3a1f59'),
            'U260828.JPI': (308, 129340, 506, 129844, 196,
                '275ed210f50143bf40add25c9c5bc2fab0880806794336b7a6efb13b881bd475'),
            'U260919.JPI': (232, 94240, 369, 94696, 224,
                '56cd4dad306daf1c0ea2d4183c78f537f48bec8e6ac101634b059d621513001a'),
        }
        for name, (start, logical, blocks, end, slack, digest) in expected.items():
            with self.subTest(name=name):
                download = read_jpi(FIXTURES / name)
                meta = download.metadata
                self.assertEqual(meta['Binary data offset (bytes)'], start)
                self.assertEqual(meta['Logical binary length (bytes)'], logical)
                self.assertEqual(meta['Logical binary end offset (bytes)'], start + logical)
                self.assertEqual(meta['Binary block count ($L)'], blocks)
                self.assertEqual(meta['Binary block size (bytes)'], 256)
                self.assertEqual(meta['Physical binary length (bytes)'], blocks * 256)
                self.assertEqual(meta['Physical binary end offset (bytes)'], end)
                self.assertEqual(meta['Block slack length (bytes)'], slack)
                self.assertTrue(meta['Block slack nonzero'])
                self.assertEqual(blocks, (logical + 255) // 256)
                self.assertEqual(end, start + blocks * 256)
                self.assertEqual(end - start - logical, slack)
                snapshot = [{'id': f.id, 'start': f.start.isoformat(),
                             'elapsed': f.elapsed, 'series': f.series}
                            for f in download.flights]
                actual = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
                self.assertEqual(actual, digest)

    def test_slack_content_does_not_affect_samples_or_values(self):
        raw = synthetic_file()
        start = data_start(raw)
        logical = int(raw.split(b'$D,415,')[1].split(b'*')[0]) * 2
        end = start + 256
        original = self.parse(raw)
        for content in (b'\xff', bytes([1, 1, 0, 1, 0, 10, 243]), dollar('E,4')):
            with self.subTest(content=content):
                size = end - start - logical
                slack = (content * (size // len(content) + 1))[:size]
                changed = self.parse(raw[:start+logical] + slack + raw[end:])
                self.assertEqual(changed.flights[0].series, original.flights[0].series)
                self.assertEqual(changed.flights[0].elapsed, original.flights[0].elapsed)
                self.assertEqual(changed.flights[0].start, original.flights[0].start)
                self.assertEqual(changed.warnings, original.warnings)
                self.assertTrue(changed.metadata['Block slack nonzero'])

    def test_zero_slack_and_multiple_blocks(self):
        initial = bytes([1, 1, 0, 1, 0, 10, 243])
        # 15-byte header + 7 + 57*4 + 6 = exactly 256 bytes.
        exact = self.parse(synthetic_file([initial] + [bytes(4)] * 57 + [bytes([1,1,0,0,0,254])]))
        self.assertEqual(exact.metadata['Block slack length (bytes)'], 0)
        self.assertFalse(exact.metadata['Block slack nonzero'])
        self.assertEqual(exact.flights[0].samples, 59)
        multi = self.parse(synthetic_file([initial] + [bytes(4)] * 64))
        self.assertEqual(multi.metadata['Binary block count ($L)'], 2)
        self.assertEqual(multi.metadata['Block slack length (bytes)'], 234)
        self.assertEqual(multi.flights[0].samples, 65)

    def test_bad_block_counts_and_fields_rejected(self):
        raw = synthetic_file()
        for body in ('L,0', 'L,-1', 'L,2', 'L,999999999999', 'L,', 'L,no', 'L,1.0', 'L,1,2'):
            with self.subTest(body=body), self.assertRaisesRegex(DataError, r'\$L'):
                self.parse(raw.replace(dollar('L,1'), dollar(body)))

    def test_bad_L_checksum_rejected(self):
        raw = synthetic_file().replace(dollar('L,1'), b'$L,2*51\r\n')
        with self.assertRaisesRegex(DataError, 'ASCII checksum'):
            self.parse(raw)

    def test_early_or_late_footer_rejected_without_scanning(self):
        raw = synthetic_file()
        for candidate in (raw[:-10] + raw[-9:], raw[:-9] + b'\x00' + raw[-9:]):
            with self.subTest(length=len(candidate)), self.assertRaisesRegex(DataError, r'\$E'):
                self.parse(candidate)

    def test_truncated_slack_with_early_footer_rejected(self):
        raw = synthetic_file()
        logical = int(raw.split(b'$D,415,')[1].split(b'*')[0]) * 2
        with self.assertRaisesRegex(DataError, r'\$E'):
            self.parse(raw[:data_start(raw)+logical] + dollar('E,4'))

    def test_footer_checksum_still_validated(self):
        raw = synthetic_file().replace(dollar('E,4'), b'$E,4*00\r\n')
        with self.assertRaisesRegex(DataError, 'ASCII checksum'):
            self.parse(raw)

    def test_declared_record_corruption_not_treated_as_slack(self):
        raw = bytearray(synthetic_file())
        raw[data_start(raw) + 15 + 6] ^= 1
        with self.assertRaisesRegex(DataError, 'record.*checksum'):
            self.parse(raw)

    def test_no_generalization_to_protocol_two(self):
        raw = synthetic_file().replace(dollar('L,1'), dollar('P,2') + dollar('L,1'))
        with self.assertRaises(UnsupportedError):
            self.parse(raw)
