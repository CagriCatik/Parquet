import pandas as pd

from parquet_app.conversion import (
    CSVToParquetOptions,
    ParquetToTextOptions,
    convert_csv_to_parquet,
    convert_parquet_to_csv,
)
from parquet_app.inspection import summarize_parquet


def test_csv_to_parquet_and_back(tmp_path):
    df = pd.DataFrame({
        "Time": [0, 1, 2],
        "Voltage": [3.3, 3.4, 3.5],
        "Current": [1.0, 1.1, 1.2],
        "Temperature": [20.0, 21.0, 22.0],
        "SOC": [50, 51, 52],
    })
    csv_path = tmp_path / "input.csv"
    pq_path = tmp_path / "output.parquet"
    roundtrip_csv = tmp_path / "roundtrip.csv"

    df.to_csv(csv_path, index=False)

    stats = convert_csv_to_parquet(
        CSVToParquetOptions(csv_path=str(csv_path), parquet_path=str(pq_path), chunksize=2)
    )
    assert stats.row_counts_match
    assert stats.column_order_equal

    back_stats = convert_parquet_to_csv(
        ParquetToTextOptions(parquet_path=str(pq_path), output_path=str(roundtrip_csv), batch_size=2)
    )
    assert back_stats.row_counts_match

    df_back = pd.read_csv(roundtrip_csv)
    pd.testing.assert_frame_equal(df, df_back)


def test_summarize_parquet(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    pq_path = tmp_path / "sample.parquet"
    df.to_parquet(pq_path, engine="pyarrow")

    summary = summarize_parquet(str(pq_path))
    assert summary.num_rows == 2
    assert summary.num_row_groups == 1
    assert summary.columns == ["a", "b"]
    assert summary.size_bytes > 0
