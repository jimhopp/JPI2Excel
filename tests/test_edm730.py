# Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
# All rights reserved.

"""Revision: 2. Protocol-2 (EDM-730) framing, decoding, and EZTrends agreement.

EDM730-anon.JPI was built by pgms/make_edm730_fixture.py from flights 735,
745, 747 (zero-length $D entry) and 749 of private EDM-730 downloads. Expected
engine values are copied from JPI EZTrends CSV exports of flights 735 and 749.
GPS position was anonymized, so LAT/LNG expectations come from the fixture.
"""
import csv
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from jpi2excel.export import ordered_codes, units, write_xlsx
from jpi2excel.model import DataError, UnsupportedError
from jpi2excel.reader import read_jpi
from test_parser import FIXTURES, ROOT, dollar

FIXTURE = FIXTURES / 'EDM730-anon.JPI'
PRIVATE = ROOT / 'testdata-730'
EZ_COLUMNS = ('E1', 'E2', 'E3', 'E4', 'E6', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6',
              'DIF', 'CLD', 'CRB', 'FF', 'FF2', 'BAT', 'USD', 'HRS')
# EZTrends rows: index -> values for EZ_COLUMNS.
EZ_735 = {
    0: (594, 619, 650, 635, 583, 291, 286, 289, 284, 265, 250, 67, 12, 81, 0.0, 0.0, 12.4, 35.6, 924.0),
    1: (589, 613, 646, 632, 579, 290, 286, 288, 284, 264, 250, 67, 12, 81, 0.0, 0.0, 12.4, 35.6, 924.0),
    2: (585, 608, 642, 628, 574, 290, 285, 288, 283, 264, 249, 68, 12, 81, 0.0, 0.0, 12.4, 35.6, 924.0),
}
EZ_749 = {
    0: (620, 620, 644, 484, 618, 76, 72, 70, 72, 74, 73, 160, 0, 69, 1.4, 0.0, 14.2, 0.0, 938.0),
    1: (654, 668, 687, 533, 667, 77, 74, 70, 73, 75, 74, 154, 0, 68, 1.6, 0.0, 14.2, 0.0, 938.0),
    497: (1445, 1477, 1474, 1454, 1440, 362, 359, 313, 351, 338, 351, 37, 0, 33, 14.4, 0.0, 13.7, 1.5, 938.3),
    1790: (878, 914, 909, 878, 909, 313, 309, 305, 301, 288, 282, 36, 0, 85, 0.2, 0.0, 13.2, 7.9, 939.0),
}


def parse(raw):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'sample.JPI'
        path.write_bytes(raw)
        return read_jpi(path)


def flight_start(raw):
    return raw.index(b'\r\n', raw.index(b'$L,')) + 2


def with_configuration(raw, xml):
    # Replace the XOR-0x02 configuration block between the two $E markers.
    start = raw.index(b'$E,4*5D\r\nJPI') + 12
    end = raw.rindex(b'$E,4*5D\r\n$V,')
    return raw[:start] + bytes(b ^ 2 for b in ('\ufeff' + xml).encode('utf-8')) + raw[end:]


class Edm730FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.download = read_jpi(FIXTURE)
        cls.flights = {f.id: f for f in cls.download.flights}

    def assert_ez_rows(self, flight, expected):
        for index, values in expected.items():
            for code, value in zip(EZ_COLUMNS, values):
                with self.subTest(flight=flight.id, index=index, code=code):
                    self.assertAlmostEqual(flight.series[code][index], value, places=6)

    def test_metadata(self):
        meta = self.download.metadata
        self.assertEqual(meta['Aircraft ID'], 'TEST730')
        self.assertEqual(meta['Model code'], '730')
        self.assertEqual(meta['Protocol'], '2 ($P)')
        self.assertEqual(meta['Firmware version'], 140)
        self.assertEqual(meta['Firmware build'], 2014)
        self.assertEqual(meta['Firmware beta'], 4)
        self.assertEqual(meta['Instrument version ($V)'], 'Created by EDM730 VER 1.40 BLD 2014 BETA 4')
        self.assertEqual(meta['$H'], '0')
        self.assertEqual(meta['Carbureted (configuration)'], 'Yes')
        self.assertEqual(meta['Total flights'], 3)
        self.assertEqual(meta['Engine temperature units'], 'F')
        self.assertEqual(self.download.alarms['BAT'], (12.0, 16.0))
        self.assertEqual(self.download.alarms['CHT'], (None, 450))

    def test_flight_packing_ignores_word_rounding(self):
        # 735 and 745 have odd byte lengths, so 749 starts two bytes before the
        # cumulative $D allocations predict.
        self.assertEqual(list(self.flights), [735, 745, 749])
        meta = self.download.metadata
        self.assertEqual(meta['Logical binary length (bytes)'], 153 + 85 + 57410)
        self.assertEqual(meta['$D allocated length (bytes)'], 2 * (77 + 43 + 0 + 28705))
        self.assertEqual(meta['Binary block count ($L)'], 226)

    def test_zero_length_directory_entry_skipped_with_warning(self):
        self.assertNotIn(747, self.flights)
        self.assertIn('Flight 747: zero-length $D entry skipped', self.download.warnings)

    def test_start_times_and_sample_counts_match_eztrends(self):
        self.assertEqual(self.flights[735].start, datetime(2026, 6, 23, 18, 10, 28))
        self.assertEqual(self.flights[735].elapsed, [0, 2, 4])
        self.assertEqual(self.flights[749].start, datetime(2026, 7, 24, 18, 3, 32))
        self.assertEqual(self.flights[749].samples, 1791)
        self.assertEqual(self.flights[749].timestamps[-1], datetime(2026, 7, 24, 19, 3, 12))

    def test_engine_values_match_eztrends(self):
        self.assert_ez_rows(self.flights[735], EZ_735)
        self.assert_ez_rows(self.flights[749], EZ_749)

    def test_carburetor_temperature_named_crb(self):
        # The configuration block says carbureted="1"; upstream's CDT channel
        # is carburetor temperature, labeled CRB as in EZTrends.
        for flight in self.download.flights:
            self.assertIn('CRB', flight.series)
            self.assertNotIn('CDT', flight.series)
        codes = ordered_codes(self.flights[749])
        self.assertEqual(codes[codes.index('CRB') - 1], 'FF2')
        self.assertEqual(units('CRB', self.download), 'F')

    def test_unconnected_channels_exported_as_recorded(self):
        # No second fuel-flow sensor is installed; FF2 reads 0.0 and is kept.
        series = self.flights[749].series
        self.assertEqual(set(series['FF2']), {0.0})
        for code in ('E5', 'MAP', 'USD2'):
            if code in series:
                self.assertEqual(set(series[code]), {None})

    def test_gps_carried_forward_in_decimal_degrees(self):
        series = self.flights[749].series
        self.assertEqual(series['SPD'][:3], [None] * 3)
        self.assertEqual((series['SPD'][497], series['ALT'][497]), (88, 1858))
        # EZTrends shows NA when the last record has zero GPS deltas.
        self.assertIsNotNone(series['SPD'][-1])
        self.assertIsNotNone(series['ALT'][-1])
        # Ten samples precede the first fix; the anonymized fix is 257 units
        # (one high and one low delta byte) from the fixture's N45 W100 start.
        self.assertEqual(series['LAT'][:10], [None] * 10)
        self.assertAlmostEqual(series['LAT'][10], 270257 / 6000)
        self.assertAlmostEqual(series['LNG'][10], -599743 / 6000)
        self.assertTrue(all(v is not None for v in series['LAT'][10:]))

    def test_second_fuel_and_hours_columns(self):
        flight = self.flights[749]
        codes = ordered_codes(flight)
        self.assertEqual(codes[codes.index('FF') + 1], 'FF2')
        self.assertEqual(codes[codes.index('USD') + 1], 'USD2')
        self.assertEqual(units('FF2', self.download), 'US gallons/hour')
        self.assertEqual(units('USD2', self.download), 'US gallons')
        self.assertEqual(units('HRS', self.download), 'hours')

    def test_xlsx_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'out.xlsx'
            write_xlsx(path, [(f, self.download) for f in self.download.flights],
                       [self.download], 0, graphs=True)
            self.assertGreater(path.stat().st_size, 0)


class Edm730FramingTests(unittest.TestCase):
    raw = FIXTURE.read_bytes()

    def test_fixture_is_anonymized(self):
        self.assertIn(dollar('U,TEST730'), self.raw)
        self.assertLess(len(self.raw) - self.raw.index(b'$E,4'), 200)

    def test_missing_end_marker_after_last_flight(self):
        raw = self.raw.replace(b'$E,4*5D\r\nJPI', b'$X,4*5D\r\nJPI', 1)
        with self.assertRaisesRegex(DataError, r'\$E'):
            parse(raw)

    def test_flight_id_must_match_directory(self):
        raw = bytearray(self.raw)
        raw[flight_start(self.raw) + 154] ^= 1   # second flight's ID (735 is 153 bytes)
        with self.assertRaisesRegex(DataError, 'Flight 745'):
            parse(bytes(raw))

    def test_record_checksum_validated(self):
        raw = bytearray(self.raw)
        raw[flight_start(self.raw) + 50] ^= 1   # a data byte in the first record
        with self.assertRaisesRegex(DataError, 'Flight 735.*checksum'):
            parse(bytes(raw))

    def test_directory_size_must_round_actual_length(self):
        raw = self.raw.replace(dollar('D, 745, 43'), dollar('D, 745, 44'))
        with self.assertRaisesRegex(DataError, 'Flight 745'):
            parse(raw)

    def test_block_count_validated(self):
        raw = self.raw.replace(dollar('L, 226'), dollar('L, 227'))
        with self.assertRaisesRegex(DataError, r'\$L'):
            parse(raw)

    def test_trailer_layout_validated(self):
        for name, raw in (
                ('extra bytes', self.raw + b'\x00'),
                ('no config marker', self.raw.replace(b'\r\nJPI', b'\r\nXYZ', 1)),
                ('no $V', self.raw[:self.raw.rindex(b'$V,')])):
            with self.subTest(name), self.assertRaises((DataError, UnsupportedError)):
                parse(raw)

    def test_carbureted_flag_selects_channel_name(self):
        for xml, code, meta, warned in (
                ('<edm_cfg><EDM carbureted="0"/></edm_cfg>', 'CDT', 'No', False),
                ('<edm_cfg><EDM/></edm_cfg>', 'CDT', 'Not stated', True),
                ('<edm_cfg><EDM carbureted="yes"/></edm_cfg>', 'CDT', 'Not stated', True)):
            with self.subTest(xml=xml):
                download = parse(with_configuration(self.raw, xml))
                self.assertIn(code, download.flights[0].series)
                self.assertNotIn('CRB', download.flights[0].series)
                self.assertEqual(download.metadata['Carbureted (configuration)'], meta)
                self.assertEqual(any('carbureted' in w for w in download.warnings), warned)

    def test_other_protocol_two_models_unsupported(self):
        raw = self.raw.replace(dollar('C,730,63741,22657,1536,17634,120,140,2014,4'),
                               dollar('C,830,63741,22657,1536,17634,120,140,2014,4'))
        with self.assertRaisesRegex(UnsupportedError, '830'):
            parse(raw)

    def test_other_protocol_versions_unsupported(self):
        with self.assertRaises(UnsupportedError):
            parse(self.raw.replace(dollar('P, 2'), dollar('P, 3')))


def ez_rows(path):
    with open(path, newline='') as handle:
        lines = list(csv.reader(handle))
    columns = [c.strip() for c in lines[0]]
    return columns, [r for r in lines[2:] if r and r[0].strip().isdigit()]


@unittest.skipUnless(PRIVATE.is_dir(), 'private EDM-730 downloads not present')
class Edm730PrivateDataTests(unittest.TestCase):
    """Full comparison with EZTrends exports; runs only where the data exists."""

    def test_all_private_downloads_decode(self):
        total = 0
        for path in sorted(PRIVATE.glob('*.JPI')):
            with self.subTest(path=path.name):
                total += len(read_jpi(path).flights)
        self.assertEqual(total, 37)

    def test_every_sample_matches_eztrends(self):
        for name, fid, export in (('U260705.JPI', 735, 'Flt735.csv'),
                                  ('U260726.JPI', 749, 'Flt749.csv')):
            flight = next(f for f in read_jpi(PRIVATE / name).flights if f.id == fid)
            columns, data = ez_rows(PRIVATE / export)
            self.assertEqual(flight.samples, len(data))
            for i, row in enumerate(data):
                stamp = datetime.strptime(f'{row[1]} {row[2]}', '%m/%d/%Y %H:%M:%S')
                self.assertEqual(flight.timestamps[i], stamp)
                for column, text in zip(columns, row):
                    text = text.strip()
                    code = column
                    if column in ('INDEX', 'DATE', 'TIME', 'MARK', '') or text in ('', 'NA'):
                        continue
                    if code in ('LAT', 'LNG'):
                        degrees, minutes, hundredths = map(int, text[1:].split('.'))
                        value = (degrees * 6000 + minutes * 100 + hundredths) / 6000
                        value = -value if text[0] in 'SW' else value
                    else:
                        value = float(text)
                    with self.subTest(flight=fid, index=i, code=code):
                        self.assertAlmostEqual(flight.series[code][i], value, places=6)


if __name__ == '__main__':
    unittest.main()
