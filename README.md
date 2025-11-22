# Parquet App

A unified desktop + CLI toolkit for viewing, converting, and inspecting Parquet data. The app combines two major workflows:

1. **CSV ➜ Parquet converter** with streaming writes, parity checks, and clear summaries
2. **Parquet viewer/editor** with live filtering and export to CSV, Excel, or Parquet

---

## Features

### Converter
- Chunked CSV ➜ Parquet conversion using `pyarrow.ParquetWriter`
- Compression selection (`snappy`, `zstd`, `gzip`, `brotli`, `lz4`, `none`)
- Parity checks: row-count equality and column-order equality with human-readable summaries
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
3. Click **Convert** to start streaming conversion with parity checks and log output.
4. Switch to the **Viewer** tab to open any Parquet file, filter/search rows, edit values, delete rows, and export.

---

## Documentation

- See `docs/overview.md` for architecture, data flow diagrams, and supported workflows.
- See `docs/usage.md` for end-to-end CLI and GUI walkthroughs.
