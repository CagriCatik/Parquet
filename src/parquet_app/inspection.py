from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from .utils import file_size, human_mb


@dataclass
class RowGroupInfo:
    index: int
    num_rows: int
    total_byte_size: int

    @property
    def size_mb(self) -> float:
        return human_mb(self.total_byte_size)


@dataclass
class ParquetSummary:
    path: str
    num_rows: int
    num_row_groups: int
    schema: str
    columns: List[str]
    row_groups: List[RowGroupInfo]
    size_bytes: int

    @property
    def size_mb(self) -> float:
        return human_mb(self.size_bytes)


@dataclass
class Preview:
    data: pd.DataFrame
    start: int
    limit: int


@dataclass
class SearchResult:
    data: pd.DataFrame
    total_rows: int


def summarize_parquet(path: str) -> ParquetSummary:
    pq_file = pq.ParquetFile(path)
    row_groups = [
        RowGroupInfo(
            index=i,
            num_rows=pq_file.metadata.row_group(i).num_rows,
            total_byte_size=pq_file.metadata.row_group(i).total_byte_size,
        )
        for i in range(pq_file.metadata.num_row_groups)
    ]

    arrow_schema = pq_file.schema_arrow
    schema_lines = arrow_schema.to_string().rstrip()

    return ParquetSummary(
        path=path,
        num_rows=pq_file.metadata.num_rows,
        num_row_groups=pq_file.metadata.num_row_groups,
        schema=schema_lines,
        columns=list(arrow_schema.names),
        row_groups=row_groups,
        size_bytes=file_size(path),
    )


def preview_parquet(path: str, columns: Optional[List[str]] = None, start: int = 0, limit: int = 50) -> Preview:
    dataset = ds.dataset(path, format="parquet")
    table = dataset.to_table(columns=columns, limit=limit, offset=start)
    df = table.to_pandas()
    return Preview(data=df, start=start, limit=limit)


def search_parquet(path: str, query: str, columns: Optional[List[str]] = None, limit: int = 200) -> SearchResult:
    dataset = ds.dataset(path, format="parquet")
    table = dataset.to_table(columns=columns)
    df = table.to_pandas()
    mask = df.apply(lambda row: row.astype(str).str.contains(query, case=False, regex=True).any(), axis=1)
    result_df = df.loc[mask].head(limit)
    return SearchResult(data=result_df, total_rows=mask.sum())
