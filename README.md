<p align="center">
  <img src="https://upload.wikimedia.org/wikipedia/commons/4/47/Apache_Parquet_logo.svg" alt="Parquet Logo" width="360"/>
</p>

<p align="center">
  A lightweight application for working with Apache Parquet files. Fast, efficient, and designed for modern data workflows.
</p>

<p align="center">
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/python-3.9%2B-blue.svg" />
  </a>
  <a href="https://pypi.org/project/pyarrow/">
    <img src="https://img.shields.io/badge/pyarrow-enabled-ffca28.svg" />
  </a>
  <a href="#">
    <img src="https://img.shields.io/badge/platform-desktop%20%2B%20CLI-8e44ad.svg" />
  </a>
  <a href="#">
    <img src="https://img.shields.io/badge/status-active-success.svg" />
  </a>
  <a href="#">
    <img src="https://img.shields.io/badge/type-hybrid%20toolkit-orange.svg" />
  </a>
  <a href="#">
    <img src="https://img.shields.io/badge/parquet-optimized-2c3e50.svg" />
  </a>
  <a href="https://deepwiki.com/CagriCatik/Parquet">
    <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" />
  </a>
</p>

A unified desktop + CLI toolkit for viewing, converting, and inspecting Parquet data.

The app combines two major workflows:

1. **CSV to Parquet converter** with streaming writes, parity checks, and clear summaries
2. **Parquet viewer/editor** with live filtering and export to CSV, Excel, or Parquet

---

## Features

### Converter

- Chunked CSV to Parquet conversion using pyarrow.ParquetWriter
- Compression selection (snappy, zstd, gzip, brotli, lz4, none)
- Parity checks: row count equality and column order equality with human readable summaries
- Background worker thread with progress, log pane, and error reporting
- CLI conversions:
  - CSV to Parquet (streaming)
  - Parquet to CSV (streaming)
  - Parquet to JSON Lines

### Viewer

- Load Parquet files via file dialog
- Live search and filter rows
- Inline cell editing
- Delete rows via context menu
- Export filtered data to CSV, Excel (.xlsx), or back to Parquet

### Inspect

- CLI metadata explorer with schema, columns, row groups, and size
- Optional preview rows with offset, limit, and column selection

---

## Requirements

- Python 3.9+
- Install dependencies:

```bash
pip install -r requirements.txt
````

---

## Project Structure

```bash
├── src/parquet_app/
│   ├── __init__.py
│   ├── app.py           # Qt desktop UI (converter + viewer tabs)
│   ├── cli.py           # CLI entrypoint
│   ├── conversion.py    # Conversion and parity logic
│   ├── inspection.py    # Parquet metadata and preview helpers
│   └── utils.py         # Shared helpers
├── static/parser.ico    # Application icon
├── example.parquet      # Sample data for inspection
├── requirements.txt
└── README.md
```

---

## Usage

### CLI

```bash
python -m src.parquet_app.cli convert input.csv --compression zstd
python -m src.parquet_app.cli convert input.parquet --jsonl --output output.jsonl
python -m src.parquet_app.cli inspect example.parquet --preview --limit 5
```

Key options:

- --chunksize: CSV reader chunk size (default 200000)
- --compression: Parquet compression codec
- --columns: Comma separated column subset for Parquet to text conversions or previews
- --jsonl: Emit JSON Lines instead of CSV for Parquet to text

### Desktop App

```bash
python -m src.parquet_app.cli gui
```

1. Open the Converter tab to select CSV input and Parquet output paths.
2. Configure delimiter, encoding, chunk size, compression, and nullable integer handling.
3. Click Convert to start streaming conversion with parity checks and log output.
4. Switch to the Viewer tab to open any Parquet file, filter or search rows, edit values, delete rows, and export.

---

## Documentation

- See [overview](./docs/overview.md) for architecture, data flow diagrams, and supported workflows.
- See [usage](./docs/usage.md) for end to end CLI and GUI walkthroughs.
