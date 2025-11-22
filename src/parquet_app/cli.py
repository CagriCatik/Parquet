from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import app as gui_app
from .conversion import (
    CSVToParquetOptions,
    ParquetToTextOptions,
    convert_csv_to_parquet,
    convert_parquet_to_csv,
    convert_parquet_to_jsonl,
    summarize_stats,
)
from .inspection import preview_parquet, summarize_parquet


def _parse_columns(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def handle_convert(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    if not input_path.exists():
        print(f"Input path does not exist: {input_path}", file=sys.stderr)
        return 1

    if input_path.suffix.lower() == ".csv":
        if output_path is None:
            output_path = input_path.with_suffix(".parquet")
        opts = CSVToParquetOptions(
            csv_path=str(input_path),
            parquet_path=str(output_path),
            delimiter=args.delimiter,
            encoding=args.encoding,
            chunksize=args.chunksize,
            compression=args.compression,
            assume_missing=args.assume_missing,
            arrow_version=args.arrow_version,
        )
        stats = convert_csv_to_parquet(opts, log=print)
    else:
        if output_path is None:
            output_path = input_path.with_suffix(".csv")
        columns = _parse_columns(args.columns)
        opts = ParquetToTextOptions(
            parquet_path=str(input_path),
            output_path=str(output_path),
            columns=columns,
            batch_size=args.batch_size,
            delimiter=args.delimiter,
            encoding=args.encoding,
        )
        if args.jsonl:
            stats = convert_parquet_to_jsonl(opts, log=print)
        else:
            stats = convert_parquet_to_csv(opts, log=print)

    print("\n" + summarize_stats(stats))
    return 0


def handle_inspect(args: argparse.Namespace) -> int:
    summary = summarize_parquet(args.input)
    print("== Parquet Summary ==")
    print(f"Rows         : {summary.num_rows}")
    print(f"Row groups   : {summary.num_row_groups}")
    print(f"Columns      : {summary.columns}")
    print(f"Size (MB)    : {summary.size_mb:.4f}")
    print("\nSchema:\n" + summary.schema)
    print("\nRow Groups:")
    for rg in summary.row_groups:
        print(f"  - #{rg.index}: rows={rg.num_rows}, size_mb={rg.size_mb:.4f}")

    if args.preview:
        preview = preview_parquet(summary.path, columns=_parse_columns(args.columns), start=args.offset, limit=args.limit)
        print(f"\nPreview rows {preview.start}..{preview.start + len(preview.data)}")
        print(preview.data)
    return 0


def handle_gui(args: argparse.Namespace) -> int:
    return gui_app.run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parquet utility CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="Convert between CSV/Parquet/JSONL")
    convert.add_argument("input", help="Input CSV or Parquet path")
    convert.add_argument("--output", help="Output path (defaults based on input)")
    convert.add_argument("--delimiter", default=",", help="Field delimiter for CSV/Parquet->CSV")
    convert.add_argument("--encoding", default="utf-8", help="Text encoding for CSV I/O")
    convert.add_argument("--chunksize", type=int, default=200_000, help="CSV read chunk size")
    convert.add_argument("--compression", default="snappy", help="Parquet compression codec")
    convert.add_argument("--assume-missing", action="store_true", help="Cast integer columns to nullable during CSV read")
    convert.add_argument("--arrow-version", default="2.6", help="Parquet version string")
    convert.add_argument("--batch-size", type=int, default=50_000, help="Batch size for Parquet->text conversions")
    convert.add_argument("--columns", help="Comma-separated list of columns to include for Parquet->text conversions")
    convert.add_argument("--jsonl", action="store_true", help="Emit JSON Lines instead of CSV when converting Parquet")
    convert.set_defaults(func=handle_convert)

    inspect = sub.add_parser("inspect", help="Inspect Parquet metadata and preview rows")
    inspect.add_argument("input", help="Parquet file path")
    inspect.add_argument("--preview", action="store_true", help="Show a preview of the data")
    inspect.add_argument("--offset", type=int, default=0, help="Row offset for preview")
    inspect.add_argument("--limit", type=int, default=20, help="Number of preview rows")
    inspect.add_argument("--columns", help="Comma-separated list of columns for preview")
    inspect.set_defaults(func=handle_inspect)

    gui = sub.add_parser("gui", help="Launch the desktop viewer/converter")
    gui.set_defaults(func=handle_gui)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
