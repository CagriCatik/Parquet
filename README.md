# Parquet App

A unified desktop + CLI toolkit for viewing, converting, and inspecting Parquet data. The app combines two major workflows:

1. **CSV ➜ Parquet converter** with streaming writes, parity checks, and visualization
2. **Parquet viewer/editor** with live filtering and export to CSV, Excel, or Parquet

---

## Features

### Converter
- Chunked CSV ➜ Parquet conversion using `pyarrow.ParquetWriter`
- Compression selection (`snappy`, `zstd`, `gzip`, `brotli`, `lz4`, `none`)
- Parity checks: row-count equality and column-order equality
- Size comparison plot (CSV vs Parquet) auto-saved to `plots/<name>_size.png`
- Optional 4x4 CSV vs Parquet comparison grid for columns `Time`, `Voltage`, `Current`, `Temperature`, `SOC` saved to `plots/<name>_compare_4x4.png`
- Background worker thread with progress, log pane, and error reporting
- CLI conversions:
  - CSV ➜ Parquet (streaming)
  - Parquet ➜ CSV (streaming)
  - Parquet ➜ JSON Lines

### Viewer
- Load Parquet files via file dialog
- Live search/filter rows
- Inline cell editing
- Delete rows via context menu
- Export filtered data to CSV, Excel (`.xlsx`), or back to Parquet

### Inspect
- CLI metadata explorer with schema, columns, row groups, and size
- Optional preview rows with offset/limit and column selection

---

## Requirements

- Python 3.9+
- Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Project Structure

```
├── src/parquet_app/
│   ├── __init__.py
│   ├── app.py           # Qt desktop UI (converter + viewer tabs)
│   ├── cli.py           # CLI entrypoint
│   ├── conversion.py    # Conversion/parity logic
│   ├── inspection.py    # Parquet metadata and preview helpers
│   └── utils.py         # Shared helpers
├── static/parser.png    # Application icon
├── example.parquet      # Sample data for inspection
├── requirements.txt
└── README.md
```

---

## Usage

### CLI

```bash
python -m parquet_app.cli convert input.csv --compression zstd
python -m parquet_app.cli convert input.parquet --jsonl --output output.jsonl
python -m parquet_app.cli inspect example.parquet --preview --limit 5
```

Key options:
- `--chunksize`: CSV reader chunk size (default 200000)
- `--compression`: Parquet compression codec
- `--columns`: Comma-separated column subset for Parquet ➜ text conversions or previews
- `--jsonl`: Emit JSON Lines instead of CSV for Parquet ➜ text

### Desktop App

```bash
python -m parquet_app.cli gui
```

1. Open the **Converter** tab to select CSV input and Parquet output paths.
2. Configure delimiter, encoding, chunk size, compression, and nullable-integer handling.
3. Click **Convert** to start streaming conversion with parity checks and a size bar chart.
4. Use **Plot 4x4 Compare** after conversion to visualize CSV vs Parquet for the four battery columns.
5. Switch to the **Viewer** tab to open any Parquet file, filter/search rows, edit values, delete rows, and export.

---

## Why Parquet Is Better Than CSV for ML Training

Parquet reduces both I/O and CPU overhead while preserving schema integrity:

1. **Columnar layout**: read only required columns instead of full rows.
2. **Strong schema**: data types and nullability are preserved, avoiding CSV parsing ambiguity.
3. **Compression & encoding**: column-wise compression (Snappy, ZSTD, Brotli) and dictionary/RLE encodings reduce size and speed up reads.
4. **Predicate pushdown**: row-group statistics let engines skip irrelevant chunks.
5. **Vectorized reads**: fast Arrow-to-pandas/NumPy hand-offs with minimal copies.
6. **Consistency**: stable schemas prevent silent column-order drift or type changes.
7. **Cloud-friendly**: works with partitioned datasets and distributed engines (Spark, Dask, Polars).

For structured ML data, Parquet yields faster, cheaper, and more consistent training due to columnar I/O, compression, and schema enforcement.
