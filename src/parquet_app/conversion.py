from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.json as pajson
import pyarrow.parquet as pq

from .utils import ensure_parent, file_size, human_mb

LogFn = Optional[Callable[[str], None]]


@dataclass
class CSVToParquetOptions:
    csv_path: str
    parquet_path: str
    delimiter: str = ","
    encoding: str = "utf-8"
    chunksize: int = 200_000
    compression: str = "snappy"
    assume_missing: bool = False
    arrow_version: Optional[str] = "2.6"
    na_values: Optional[List[str]] = None


@dataclass
class ParquetToTextOptions:
    parquet_path: str
    output_path: str
    columns: Optional[List[str]] = None
    batch_size: int = 50_000
    delimiter: str = ","
    encoding: str = "utf-8"


@dataclass
class ConversionStats:
    input_rows: int
    output_rows: int
    input_bytes: int
    output_bytes: int
    column_order_equal: Optional[bool] = None
    csv_columns: Optional[List[str]] = None
    parquet_columns: Optional[List[str]] = None

    @property
    def input_mb(self) -> float:
        return human_mb(self.input_bytes)

    @property
    def output_mb(self) -> float:
        return human_mb(self.output_bytes)

    @property
    def row_counts_match(self) -> bool:
        return self.input_rows == self.output_rows


def _emit(log: LogFn, message: str) -> None:
    if log:
        log(message)


def _iter_csv_chunks(opts: CSVToParquetOptions) -> Iterable[pd.DataFrame]:
    na_values = opts.na_values or ["", "NA", "N/A", "NaN", "nan", "null", "NULL"]
    reader = pd.read_csv(
        opts.csv_path,
        sep=opts.delimiter,
        encoding=opts.encoding,
        chunksize=opts.chunksize,
        iterator=True,
        low_memory=False,
        na_values=na_values,
        keep_default_na=True,
    )
    for df in reader:
        yield df


def convert_csv_to_parquet(opts: CSVToParquetOptions, log: LogFn = None) -> ConversionStats:
    """
    Stream a CSV file into Parquet using a ParquetWriter to bound memory usage.
    The function converts integer columns to nullable integers when requested
    and returns summary statistics for parity checks.
    """

    ensure_parent(opts.parquet_path)

    writer: Optional[pq.ParquetWriter] = None
    total_rows = 0

    for chunk_index, df in enumerate(_iter_csv_chunks(opts)):
        if opts.assume_missing:
            for col in df.select_dtypes(include=["int32", "int64"]).columns:
                df[col] = df[col].astype("Int64")

        table = pa.Table.from_pandas(df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(
                opts.parquet_path,
                table.schema,
                compression=None if opts.compression == "none" else opts.compression,
                use_dictionary=True,
                version=opts.arrow_version or "2.6",
            )
            _emit(log, "Initialized ParquetWriter.")

        writer.write_table(table)
        total_rows += len(df)
        if chunk_index < 5:
            _emit(log, f"Wrote chunk {chunk_index + 1} ({len(df)} rows)...")

    if writer is not None:
        writer.close()

    stats = verify_csv_parquet(opts, log=log)
    _emit(log, f"Finished writing {total_rows} rows.")
    return stats


def verify_csv_parquet(opts: CSVToParquetOptions, log: LogFn = None) -> ConversionStats:
    csv_rows = 0
    for chunk in pd.read_csv(
        opts.csv_path,
        sep=opts.delimiter,
        encoding=opts.encoding,
        chunksize=max(1, opts.chunksize),
        iterator=True,
        low_memory=False,
    ):
        csv_rows += len(chunk)

    pq_file = pq.ParquetFile(opts.parquet_path)
    pq_rows = sum(pq_file.metadata.row_group(i).num_rows for i in range(pq_file.metadata.num_row_groups))

    csv_head = pd.read_csv(opts.csv_path, sep=opts.delimiter, encoding=opts.encoding, nrows=0)
    parquet_head = pq.read_table(opts.parquet_path, columns=None).to_pandas().head(0)

    csv_cols = list(csv_head.columns)
    parquet_cols = list(parquet_head.columns)

    stats = ConversionStats(
        input_rows=int(csv_rows),
        output_rows=int(pq_rows),
        input_bytes=file_size(opts.csv_path),
        output_bytes=file_size(opts.parquet_path),
        column_order_equal=csv_cols == parquet_cols,
        csv_columns=csv_cols,
        parquet_columns=parquet_cols,
    )

    _emit(log, f"CSV rows: {stats.input_rows}; Parquet rows: {stats.output_rows}")
    _emit(log, f"Column order equal: {stats.column_order_equal}")
    return stats


def convert_parquet_to_csv(opts: ParquetToTextOptions, log: LogFn = None) -> ConversionStats:
    ensure_parent(opts.output_path)

    pq_file = pq.ParquetFile(opts.parquet_path)
    csv_path = Path(opts.output_path)
    first = True
    total_rows = 0
    for batch in pq_file.iter_batches(batch_size=opts.batch_size, columns=opts.columns):
        df = batch.to_pandas()
        df.to_csv(csv_path, mode="w" if first else "a", header=first, index=False, sep=opts.delimiter, encoding=opts.encoding)
        first = False
        total_rows += len(df)
        _emit(log, f"Wrote {len(df)} rows to CSV (total {total_rows}).")

    stats = ConversionStats(
        input_rows=pq_file.metadata.num_rows,
        output_rows=total_rows,
        input_bytes=file_size(opts.parquet_path),
        output_bytes=file_size(opts.output_path),
        column_order_equal=True,
    )
    return stats


def convert_parquet_to_jsonl(opts: ParquetToTextOptions, log: LogFn = None) -> ConversionStats:
    ensure_parent(opts.output_path)
    pq_file = pq.ParquetFile(opts.parquet_path)
    out_path = Path(opts.output_path)
    total_rows = 0

    with out_path.open("w", encoding=opts.encoding) as fh:
        for batch in pq_file.iter_batches(batch_size=opts.batch_size, columns=opts.columns):
            table = pa.Table.from_batches([batch])
            for json_line in pajson.write_json(table, use_b64=False).decode().splitlines():
                fh.write(json_line + "\n")
            total_rows += batch.num_rows
            _emit(log, f"Wrote {batch.num_rows} rows to JSONL (total {total_rows}).")

    stats = ConversionStats(
        input_rows=pq_file.metadata.num_rows,
        output_rows=total_rows,
        input_bytes=file_size(opts.parquet_path),
        output_bytes=file_size(opts.output_path),
        column_order_equal=True,
    )
    return stats


def summarize_stats(stats: ConversionStats) -> str:
    lines = [
        f"Input rows        : {stats.input_rows}",
        f"Output rows       : {stats.output_rows}",
        f"Row counts equal  : {stats.row_counts_match}",
        f"Input size (MB)   : {stats.input_mb:.4f}",
        f"Output size (MB)  : {stats.output_mb:.4f}",
    ]
    if stats.column_order_equal is not None:
        lines.append(f"Column order equal: {stats.column_order_equal}")
    if stats.csv_columns is not None:
        lines.append(f"CSV columns       : {stats.csv_columns}")
    if stats.parquet_columns is not None:
        lines.append(f"Parquet columns   : {stats.parquet_columns}")
    return "\n".join(lines)


def size_ratio(stats: ConversionStats) -> Optional[float]:
    if stats.output_bytes <= 0:
        return None
    return math.nan if stats.input_bytes <= 0 else stats.output_bytes / stats.input_bytes
