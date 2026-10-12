# Copyright © 2025-2026 by Alan M. Marcum, Nescorna Professional.
# All rights reserved.

"""Revision: 8. Command-line orchestration and errno-based exit status."""
import argparse
from collections import Counter
import errno
import math
from pathlib import Path
import re
import signal
import sys

from . import __version__
from .model import ConversionError
from .export import duration_text, info_items, write_csv, write_xlsx


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ConversionError(message)


def parser():
    p = Parser(prog='jpi2excel', add_help=False,
               description='Validate single-engine EDM-700/800 (legacy) and EDM-730 (protocol 2) JPI files '
                           'and export CSV or XLSX. '
                           'Use --info alone or with one other action.')
    p.add_argument('--info', action='store_true',
                   help='Print file and selected-flight properties, alone or with one other action')
    p.add_argument('--graph', '--graphs', dest='graphs', action='store_true',
                   help='Add graphs after each XLSX flight sheet; invalid with --csv; ignored without an XLSX export')
    actions = p.add_mutually_exclusive_group()
    for flag, help_text in [('list', 'List every flight; flights shorter than five minutes last'),
                            ('validate', 'Validate structure and all checksums'),
                            ('csv', 'Write one CSV per selected flight'),
                            ('xls', 'Write one XLSX with summary and one sheet per selected flight (default: JPI2Excel.xlsx)'),
                            ('xls-separate', 'Write one XLSX per selected flight with a hidden Summary for alarm formatting'),
                            ('version', 'Print version'), ('help', 'Show this help')]:
        actions.add_argument('--' + flag, action='store_const', const=flag, dest='action', help=help_text)
    p.add_argument('--flights', default='all', metavar='ALL|N,N:M', help='Flight numbers or inclusive ranges (default: all)')
    p.add_argument('--engine', default='all', help='Engine selection (initial release: one engine; any single positive number or left/center/right)')
    p.add_argument('--output', type=Path, help='Explicit output path; valid only when creating one file. '
                   'Defaults: JPI2Excel.xlsx for --xls; <source>_Flight_<number>.csv or .xlsx for separate files')
    p.add_argument('--output-dir', type=Path, help='Existing output directory (default: current directory)')
    p.add_argument('--minimum-duration', type=float, default=5, metavar='MINUTES', help='Export cutoff in minutes (default: 5); explicitly selecting a shorter flight is an error')
    p.add_argument('--verbose', action='store_true', help='Report configuration, durations, and skipped/exported counts')
    p.add_argument('inputs', nargs='*', type=Path, metavar='FILE.JPI')
    return p


def flight_selection(spec):
    if spec.lower() == 'all':
        return None
    chosen = set()
    for item in spec.split(','):
        if not re.fullmatch(r'\d+(?::\d+)?', item):
            raise ConversionError(f'Invalid flight selection: {item!r}')
        limits = list(map(int, item.split(':')))
        start, end = limits[0], limits[-1]
        if not 0 <= start <= end <= 65535:
            raise ConversionError(f'Invalid flight range: {item}')
        chosen.update(range(start, end + 1))
    return chosen


def check_engine(spec):
    parts = spec.lower().split(',')
    if len(parts) != 1:
        if all(part in ('left', 'center', 'right') or (part.isdigit() and int(part) > 0) for part in parts):
            raise ConversionError('Only one engine is present; multiple-engine selection is unavailable', errno.EDOM)
        raise ConversionError('Invalid engine selection')
    if parts[0] not in ('all', 'left', 'center', 'right') and not (parts[0].isdigit() and int(parts[0]) > 0):
        raise ConversionError('Engine must be all, a position, or a positive number')


def error_code(exc):
    if isinstance(exc, ConversionError):
        return exc.code
    code = getattr(exc, 'errno', None) or 200
    return errno.EPERM if code == errno.EACCES else code if 0 < code < 256 else 200


def report(message):
    print(message, file=sys.stderr)


def counted(count, noun):
    return f'{count} {noun if count == 1 else noun + "s"}'


def select(downloads, choices, cutoff):
    all_flights = [(f, d) for d in downloads for f in d.flights]
    if choices is not None:
        missing = choices - {f.id for f, _ in all_flights}
        if missing:
            raise ConversionError(f'Flights not found: {", ".join(map(str, sorted(missing)))}', errno.EDOM)
        short = [f'{d.path.name}: flight {f.id}' for f, d in all_flights if f.id in choices and f.duration < cutoff]
        if short:
            raise ConversionError('Explicitly selected flights are below minimum duration: ' + '; '.join(short), 201)
    return [(f, d) for f, d in all_flights if (choices is None or f.id in choices) and f.duration >= cutoff]


def output_plan(args, selected):
    directory = args.output_dir or Path.cwd()
    if args.output and args.output_dir:
        raise ConversionError('Use either --output or --output-dir')
    count = 1 if args.action == 'xls' else len(selected)
    if args.output and count != 1:
        raise ConversionError('--output requires exactly one output file')
    if not directory.exists():
        raise FileNotFoundError(errno.ENOENT, 'Destination directory not found', str(directory))
    if not directory.is_dir():
        raise NotADirectoryError(errno.ENOTDIR, 'Destination is not a directory', str(directory))
    extension = '.csv' if args.action == 'csv' else '.xlsx'
    if args.output:
        paths = [args.output]
    elif args.action == 'xls':
        paths = [directory / 'JPI2Excel.xlsx']
    else:
        paths, names = [], set()
        for flight, download in selected:
            stem = re.sub(r'[^\w.-]+', '_', download.path.stem).strip('.') or 'JPI'
            base = f'{stem}_Flight_{flight.id}'
            name, index = base + extension, 1
            while name.casefold() in names:
                index += 1
                name = f'{base}_{index}{extension}'
            names.add(name.casefold())
            paths.append(directory / name)
    for path in paths:
        if path.is_dir():
            raise IsADirectoryError(errno.EISDIR, 'Destination is a directory', str(path))
        if path.exists() or path.is_symlink():
            raise FileExistsError(errno.EEXIST, 'Destination already exists', str(path))
        if not path.parent.exists():
            raise FileNotFoundError(errno.ENOENT, 'Destination directory not found', str(path.parent))
        if not path.parent.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, 'Destination parent is not a directory', str(path.parent))
    return paths


def run(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.action == 'help':
        p.print_help()
    elif args.action == 'version':
        print(f'JPI2Excel {__version__}')
    if args.action in ('help', 'version') and not (args.info and args.inputs):
        return 0
    if args.action is None and not args.info:
        raise ConversionError('An action is required; use --info alone or with one other action; see --help', errno.EOPNOTSUPP)
    if not args.inputs:
        raise ConversionError('At least one input file is required')
    if not math.isfinite(args.minimum_duration) or args.minimum_duration < 0:
        raise ConversionError('--minimum-duration must be a finite nonnegative number of minutes')
    choices = flight_selection(args.flights)
    check_engine(args.engine)
    exporting = args.action in ('csv', 'xls', 'xls-separate')
    if args.graphs and args.action == 'csv':
        raise ConversionError('--graph/--graphs cannot be used with --csv')
    if not exporting and (args.output or args.output_dir):
        raise ConversionError('Output options require an export action')
    if not (exporting or args.info) and (choices is not None or args.engine != 'all'):
        raise ConversionError('Flight/engine selection requires --info or an export action')
    try:
        from .reader import read_jpi
    except ImportError as exc:
        raise ConversionError('JPI-Parser dependency is unavailable; install the project or use pgms/jpi2excel.py', 200) from exc
    downloads, failures = [], []
    for path in args.inputs:
        try:
            download = read_jpi(path)
            downloads.append(download)
            for warning in download.warnings:
                report(f'Warning: {path.name}: {warning}')
        except (ConversionError, OSError) as exc:
            if error_code(exc) == errno.ECANCELED:
                raise
            report(f'Error: {path}: {exc}')
            failures.append(error_code(exc))
    counts = Counter(f.id for d in downloads for f in d.flights)
    for fid, count in counts.items():
        if count > 1:
            warning = f'Flight number {fid} occurs {count} times across inputs; preserving all copies'
            report('Warning: ' + warning)
            for download in downloads:
                if any(f.id == fid for f in download.flights):
                    download.warnings.append(warning)
    try:
        if failures and choices is not None:
            available = {f.id for d in downloads for f in d.flights}
            missing = choices - available
            if missing:
                report('Error: requested flights unavailable after input failures: '
                       + ', '.join(map(str, sorted(missing))))
                failures.append(errno.EDOM)
                choices = choices & available
        if args.info:
            # Info may inspect short flights. The minimum remains a count
            # threshold here and an export cutoff when exporting below.
            select(downloads, choices, 0)
            for download in downloads:
                for name, value in info_items(download, args.minimum_duration, flight_ids=choices):
                    print(f'{name}: {value}')
        if args.action == 'list':
            flights = sorted(((f, d) for d in downloads for f in d.flights),
                             key=lambda pair: (pair[0].duration < 300, pair[0].id))
            for flight, download in flights:
                print(f'{download.path.name}: Flight {flight.id}, {flight.start}, {duration_text(flight.duration)}, {"GPS" if flight.gps else "No GPS"}')
        elif args.action == 'validate':
            for download in downloads:
                print(f'{download.path.name}: Valid ({counted(len(download.flights), "flight")})')
        elif exporting and downloads:
            selected = select(downloads, choices, args.minimum_duration * 60)
            if not selected:
                report('No flights meet the minimum duration; no output files created')
            else:
                paths = output_plan(args, selected)
                if args.action == 'xls':
                    warnings = write_xlsx(paths[0], selected, downloads, args.minimum_duration,
                                          graphs=args.graphs)
                    for warning in warnings:
                        report('Warning: ' + warning)
                else:
                    for path, (flight, download) in zip(paths, selected):
                        if args.action == 'csv':
                            write_csv(path, flight, download)
                        else:
                            warnings = write_xlsx(path, [(flight, download)], [download], args.minimum_duration,
                                                  summary=False, graphs=args.graphs)
                            for warning in warnings:
                                report('Warning: ' + warning)
                if args.verbose:
                    report(f'Exported {counted(len(selected), "flight")} to {counted(len(paths), "file")}')
            if args.verbose:
                skipped = sum(f.duration < args.minimum_duration * 60 for d in downloads for f in d.flights)
                report(f'Skipped {counted(skipped, "flight")} below minimum duration')
        if args.verbose:
            for download in downloads:
                report(f'{download.path.name}: {counted(len(download.flights), "flight")}')
                for flight in download.flights:
                    report(f'Flight {flight.id}: {counted(flight.cylinder_count, "cylinder")}; '
                           f'{counted(flight.tit_count, "TIT channel")}; duration {duration_text(flight.duration)}')
    except (ConversionError, OSError) as exc:
        if error_code(exc) == errno.ECANCELED:
            raise
        report(f'Error: {exc}')
        failures.append(error_code(exc))
    # A corrupt input must remain visible even if another file/output also fails.
    return errno.EILSEQ if errno.EILSEQ in failures else failures[0] if failures else 0


def main(argv=None):
    def interrupted(signum, frame):
        raise OSError(errno.ECANCELED, f'Interrupted by signal {signum}')
    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, interrupted)
        return run(argv)
    except (ConversionError, OSError) as exc:
        report(f'Error: {exc}')
        return error_code(exc)
    except ImportError as exc:
        report(f'Error: missing dependency: {exc}')
        return 200
    except KeyboardInterrupt:
        return errno.ECANCELED
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
