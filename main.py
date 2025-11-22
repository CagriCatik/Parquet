#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
csv2parquet_gui.py

GUI tool to convert CSV to Parquet and compare results with a plot and parity checks.

Features:
- Choose CSV input and Parquet output paths
- Options: delimiter, encoding, chunksize, compression, assume-missing, Arrow version
- Chunked conversion using ParquetWriter to keep memory bounded
- Parity checks: row counts and column order equality
- Embedded Matplotlib bar chart comparing file sizes (CSV vs Parquet)
- Background worker thread with progress and log output

Requirements:
  Python 3.9+
  pip install PySide6 pandas pyarrow matplotlib

Run:
  python csv2parquet_gui.py
"""

from __future__ import annotations

import os
import math
import sys
from dataclasses import dataclass
from typing import Optional, List

from PySide6 import QtCore, QtGui, QtWidgets

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Use non-interactive backend; FigureCanvasQTAgg embeds the figure.
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg


# ---------------------------
# Utility functions
# ---------------------------

def human_mb(nbytes: int) -> float:
    if nbytes is None or nbytes <= 0:
        return float("nan")
    return nbytes / (1024.0 * 1024.0)


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def ensure_parent_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


# ---------------------------
# Conversion logic
# ---------------------------

@dataclass
class ConvertOptions:
    csv_path: str
    parquet_path: str
    delimiter: str = ","
    encoding: str = "utf-8"
    chunksize: int = 200_000
    compression: str = "snappy"  # snappy, zstd, gzip, brotli, lz4, none
    assume_missing: bool = False
    arrow_version: Optional[str] = "2.6"  # None means library default
    na_values: Optional[List[str]] = None


class ConverterWorker(QtCore.QThread):
    """
    Runs the conversion and verification in a background thread.
    Emits signals for logging, progress, completion, and the size/verification stats.
    """

    log_line = QtCore.Signal(str)
    progress = QtCore.Signal(int)  # 0..100 (best effort)
    finished_success = QtCore.Signal(dict)  # payload includes sizes and parity
    failed = QtCore.Signal(str)

    def __init__(self, opts: ConvertOptions):
        super().__init__()
        self.opts = opts

    def run(self) -> None:
        try:
            self.progress.emit(1)
            if not os.path.exists(self.opts.csv_path):
                raise FileNotFoundError("Input CSV does not exist.")

            # Convert CSV to Parquet using chunked streaming
            self.log_line.emit("Starting conversion...")
            self._convert_csv_to_parquet()
            self.progress.emit(70)
            self.log_line.emit("Conversion finished. Verifying parity...")

            # Verify parity and sizes
            payload = self._verify_and_sizes()
            self.progress.emit(100)
            self.finished_success.emit(payload)
        except Exception as e:
            self.failed.emit(str(e))

    def _convert_csv_to_parquet(self) -> None:
        o = self.opts
        na_values = o.na_values or ["", "NA", "N/A", "NaN", "nan", "null", "NULL"]

        ensure_parent_dir(o.parquet_path)

        reader = pd.read_csv(
            o.csv_path,
            sep=o.delimiter,
            encoding=o.encoding,
            chunksize=o.chunksize,
            iterator=True,
            low_memory=False,
            na_values=na_values,
            keep_default_na=True,
        )

        writer: Optional[pq.ParquetWriter] = None
        total_rows = 0
        chunks = 0

        try:
            for df in reader:
                if o.assume_missing:
                    for c in df.select_dtypes(include=["int32", "int64"]).columns:
                        df[c] = df[c].astype("Int64")

                table = pa.Table.from_pandas(df, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(
                        o.parquet_path,
                        table.schema,
                        compression=None if o.compression == "none" else o.compression,
                        use_dictionary=True,
                        version=o.arrow_version if o.arrow_version else "2.6",
                    )
                    self.log_line.emit("Initialized ParquetWriter.")
                writer.write_table(table)
                total_rows += len(df)
                chunks += 1

                # Heuristic progress update
                if chunks <= 10:
                    self.progress.emit(min(60, 5 + chunks * 5))
        finally:
            if writer is not None:
                writer.close()

        self.log_line.emit(f"Wrote {total_rows} rows to Parquet.")

    def _verify_and_sizes(self) -> dict:
        o = self.opts

        # Row count for CSV
        csv_rows = 0
        for chunk in pd.read_csv(
            o.csv_path,
            sep=o.delimiter,
            encoding=o.encoding,
            chunksize=500_000,
            iterator=True,
            low_memory=False,
        ):
            csv_rows += len(chunk)

        pq_file = pq.ParquetFile(o.parquet_path)
        pq_rows = sum(pq_file.metadata.row_group(i).num_rows for i in range(pq_file.metadata.num_row_groups))

        # Column order check using headers only
        csv_head = pd.read_csv(o.csv_path, sep=o.delimiter, encoding=o.encoding, nrows=0)
        csv_cols = list(csv_head.columns)

        parquet_head = pq.read_table(o.parquet_path, columns=None).to_pandas().head(0)
        parquet_cols = list(parquet_head.columns)

        csv_bytes = file_size(o.csv_path)
        pq_bytes = file_size(o.parquet_path)

        payload = {
            "csv_rows": int(csv_rows),
            "parquet_rows": int(pq_rows),
            "row_count_equal": bool(csv_rows == pq_rows),
            "csv_cols": csv_cols,
            "parquet_cols": parquet_cols,
            "column_order_equal": bool(csv_cols == parquet_cols),
            "csv_bytes": csv_bytes,
            "parquet_bytes": pq_bytes,
            "csv_mb": human_mb(csv_bytes),
            "parquet_mb": human_mb(pq_bytes),
        }
        return payload


# ---------------------------
# Matplotlib canvas widget
# ---------------------------

class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=5, height=3):
        self.fig = Figure(figsize=(width, height), tight_layout=True)
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)

    def plot_sizes(self, csv_mb: float, pq_mb: float):
        self.ax.clear()
        labels = ["CSV", "Parquet"]
        sizes = [csv_mb, pq_mb]
        self.ax.bar(labels, sizes)
        self.ax.set_ylabel("Size (MB)")
        self.ax.set_title("File Size Comparison")
        for i, v in enumerate(sizes):
            if not math.isnan(v):
                self.ax.text(i, v, f"{v:.2f} MB", ha="center", va="bottom")
        self.draw()


# ---------------------------
# Main Window
# ---------------------------

class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CSV to Parquet Converter")
        self.setMinimumSize(900, 600)
        self.worker: Optional[ConverterWorker] = None

        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Paths row
        path_group = QtWidgets.QGroupBox("Paths")
        path_lay = QtWidgets.QGridLayout(path_group)

        self.csv_edit = QtWidgets.QLineEdit()
        self.csv_btn = QtWidgets.QPushButton("Browse CSV")
        self.csv_btn.clicked.connect(self._browse_csv)

        self.parquet_edit = QtWidgets.QLineEdit()
        self.parquet_btn = QtWidgets.QPushButton("Browse Parquet")
        self.parquet_btn.clicked.connect(self._browse_parquet)

        path_lay.addWidget(QtWidgets.QLabel("CSV input"), 0, 0)
        path_lay.addWidget(self.csv_edit, 0, 1)
        path_lay.addWidget(self.csv_btn, 0, 2)
        path_lay.addWidget(QtWidgets.QLabel("Parquet output"), 1, 0)
        path_lay.addWidget(self.parquet_edit, 1, 1)
        path_lay.addWidget(self.parquet_btn, 1, 2)

        # Options
        opt_group = QtWidgets.QGroupBox("Options")
        opt_lay = QtWidgets.QGridLayout(opt_group)

        self.delim_edit = QtWidgets.QLineEdit(",")
        self.enc_edit = QtWidgets.QLineEdit("utf-8")
        self.chunk_spin = QtWidgets.QSpinBox()
        self.chunk_spin.setRange(1_000, 5_000_000)
        self.chunk_spin.setSingleStep(50_000)
        self.chunk_spin.setValue(200_000)

        self.comp_combo = QtWidgets.QComboBox()
        self.comp_combo.addItems(["snappy", "zstd", "gzip", "brotli", "lz4", "none"])

        self.assume_missing = QtWidgets.QCheckBox("Assume missing in integer columns")
        self.arrow_edit = QtWidgets.QLineEdit("2.6")

        opt_lay.addWidget(QtWidgets.QLabel("Delimiter"), 0, 0)
        opt_lay.addWidget(self.delim_edit, 0, 1)
        opt_lay.addWidget(QtWidgets.QLabel("Encoding"), 0, 2)
        opt_lay.addWidget(self.enc_edit, 0, 3)

        opt_lay.addWidget(QtWidgets.QLabel("Chunksize"), 1, 0)
        opt_lay.addWidget(self.chunk_spin, 1, 1)
        opt_lay.addWidget(QtWidgets.QLabel("Compression"), 1, 2)
        opt_lay.addWidget(self.comp_combo, 1, 3)

        opt_lay.addWidget(QtWidgets.QLabel("Arrow version"), 2, 0)
        opt_lay.addWidget(self.arrow_edit, 2, 1)
        opt_lay.addWidget(self.assume_missing, 2, 2, 1, 2)

        # Actions
        act_lay = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Convert")
        self.run_btn.clicked.connect(self._run_conversion)
        self.save_plot_btn = QtWidgets.QPushButton("Save Plot")
        self.save_plot_btn.clicked.connect(self._save_plot)
        self.save_plot_btn.setEnabled(False)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        act_lay.addWidget(self.run_btn)
        act_lay.addWidget(self.save_plot_btn)
        act_lay.addStretch(1)
        act_lay.addWidget(self.progress)

        # Output panel: plot + log + parity
        out_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # Left: plot
        plot_container = QtWidgets.QWidget()
        plot_lay = QtWidgets.QVBoxLayout(plot_container)
        self.canvas = MplCanvas(self, width=5, height=4)
        plot_lay.addWidget(self.canvas)
        out_split.addWidget(plot_container)

        # Right: logs and parity
        right_container = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right_container)

        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.parity_text = QtWidgets.QPlainTextEdit()
        self.parity_text.setReadOnly(True)
        self.parity_text.setMaximumBlockCount(10000)

        right_lay.addWidget(QtWidgets.QLabel("Logs"))
        right_lay.addWidget(self.log_text, 1)
        right_lay.addWidget(QtWidgets.QLabel("Parity"))
        right_lay.addWidget(self.parity_text, 1)

        out_split.addWidget(right_container)
        out_split.setStretchFactor(0, 1)
        out_split.setStretchFactor(1, 1)

        # Assemble
        layout.addWidget(path_group)
        layout.addWidget(opt_group)
        layout.addLayout(act_lay)
        layout.addWidget(out_split, 1)

    # -----------------------
    # UI Handlers
    # -----------------------

    def _browse_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV files (*.csv);;All files (*)")
        if path:
            self.csv_edit.setText(path)
            # Pre-fill output path
            base, _ = os.path.splitext(path)
            self.parquet_edit.setText(base + ".parquet")

    def _browse_parquet(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select Parquet Output", "", "Parquet files (*.parquet)")
        if path:
            if not path.lower().endswith(".parquet"):
                path += ".parquet"
            self.parquet_edit.setText(path)

    def _run_conversion(self):
        csv_path = self.csv_edit.text().strip()
        pq_path = self.parquet_edit.text().strip()
        if not csv_path or not pq_path:
            QtWidgets.QMessageBox.warning(self, "Error", "CSV input and Parquet output paths are required.")
            return

        opts = ConvertOptions(
            csv_path=csv_path,
            parquet_path=pq_path,
            delimiter=self.delim_edit.text() or ",",
            encoding=self.enc_edit.text() or "utf-8",
            chunksize=int(self.chunk_spin.value()),
            compression=self.comp_combo.currentText(),
            assume_missing=self.assume_missing.isChecked(),
            arrow_version=(self.arrow_edit.text().strip() or None),
        )

        # Reset UI
        self.progress.setValue(0)
        self.log_text.clear()
        self.parity_text.clear()
        self.save_plot_btn.setEnabled(False)
        self.canvas.plot_sizes(float("nan"), float("nan"))

        # Start worker
        self.worker = ConverterWorker(opts)
        self.worker.log_line.connect(self._append_log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished_success.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.run_btn.setEnabled(False)
        self.worker.start()

    def _append_log(self, line: str):
        self.log_text.appendPlainText(line)

    def _on_finished(self, payload: dict):
        self.run_btn.setEnabled(True)
        # Update parity panel
        lines = []
        lines.append(f"CSV rows           : {payload.get('csv_rows')}")
        lines.append(f"Parquet rows       : {payload.get('parquet_rows')}")
        lines.append(f"Row count equal    : {payload.get('row_count_equal')}")
        lines.append(f"Column order equal : {payload.get('column_order_equal')}")
        if not payload.get("column_order_equal", True):
            lines.append("Warning: column orders differ.")
            lines.append(f"CSV columns    : {payload.get('csv_cols')}")
            lines.append(f"Parquet columns: {payload.get('parquet_cols')}")
        lines.append("")
        lines.append(f"CSV size MB        : {payload.get('csv_mb'):.4f}")
        lines.append(f"Parquet size MB    : {payload.get('parquet_mb'):.4f}")
        self.parity_text.setPlainText("\n".join(lines))

        # Plot sizes
        self.canvas.plot_sizes(payload.get("csv_mb"), payload.get("parquet_mb"))
        self.save_plot_btn.setEnabled(True)
        self._append_log("Done.")

    def _on_failed(self, msg: str):
        self.run_btn.setEnabled(True)
        self._append_log(f"Error: {msg}")
        QtWidgets.QMessageBox.critical(self, "Conversion failed", msg)

    def _save_plot(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Plot", "", "PNG files (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            self.canvas.fig.savefig(path, dpi=150)
            self._append_log(f"Plot saved: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(e))


# ---------------------------
# Entry point
# ---------------------------

def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
