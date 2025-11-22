#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
csv2parquet_gui.py

Convert CSV to Parquet, verify parity, show size comparison, and visualize CSV vs Parquet
on a 4x4 grid (top 2 rows CSV, bottom 2 rows Parquet). Automatically saves:
  - plots/<basename>_size.png            (size bar chart)
  - plots/<basename>_compare_4x4.png     (4x4 comparison grid)

Folder rules (enforced):
  - CSV files are read from ./csv
  - Parquet files are written to ./parquet
  - Plots are written to ./plots

Requirements:
  Python 3.9+
  pip install PySide6 pandas pyarrow matplotlib numpy

Run:
  python ui.py
"""

from __future__ import annotations

import os
import math
import sys
from dataclasses import dataclass
from typing import Optional, List, Tuple, Callable

from PySide6 import QtCore, QtGui, QtWidgets

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg


# ---------------------------
# Project paths (enforced)
# ---------------------------

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
CSV_DIR = os.path.join(ROOT_DIR, "csv")
PARQUET_DIR = os.path.join(ROOT_DIR, "parquet")
PLOTS_DIR = os.path.join(ROOT_DIR, "plots")

for _d in (CSV_DIR, PARQUET_DIR, PLOTS_DIR):
    os.makedirs(_d, exist_ok=True)


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


def plot_output_path(parquet_path: str, suffix: str) -> str:
    """
    Always write plots to the top-level ./plots folder:
      plots/<basename>_<suffix>.png
    <basename> is derived from the Parquet output filename (without extension).
    """
    base_name = os.path.splitext(os.path.basename(parquet_path))[0]
    return os.path.join(PLOTS_DIR, f"{base_name}_{suffix}.png")


def parse_time_and_cast_numeric(df: pd.DataFrame, time_unit: str = "s") -> pd.DataFrame:
    out = df.copy()
    if "Time" not in out.columns:
        raise ValueError("Column 'Time' is required.")
    t = out["Time"]
    if np.issubdtype(t.dtype, np.number):
        out["Time"] = pd.to_timedelta(t, unit=time_unit)
    else:
        out["Time"] = pd.to_datetime(t, errors="coerce")
    for c in ["Voltage", "Current", "Temperature", "SOC"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def autosave_figure(fig: Figure, path: str, log: Callable[[str], None]) -> None:
    try:
        ensure_parent_dir(path)
        fig.savefig(path, dpi=150)
        log(f"Plot saved: {path}")
    except Exception as e:
        log(f"Error saving plot '{path}': {e}")


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
    compression: str = "snappy"
    assume_missing: bool = False
    arrow_version: Optional[str] = "2.6"
    na_values: Optional[List[str]] = None


class ConverterWorker(QtCore.QThread):
    log_line = QtCore.Signal(str)
    progress = QtCore.Signal(int)
    finished_success = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, opts: ConvertOptions):
        super().__init__()
        self.opts = opts

    def run(self) -> None:
        try:
            self.progress.emit(1)
            if not os.path.exists(self.opts.csv_path):
                raise FileNotFoundError("Input CSV does not exist.")
            self.log_line.emit("Starting conversion...")
            self._convert_csv_to_parquet()
            self.progress.emit(70)
            self.log_line.emit("Conversion finished. Verifying parity...")
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
                if chunks <= 10:
                    self.progress.emit(min(60, 5 + chunks * 5))
        finally:
            if writer is not None:
                writer.close()
        self.log_line.emit(f"Wrote {total_rows} rows to Parquet.")

    def _verify_and_sizes(self) -> dict:
        o = self.opts
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

        csv_head = pd.read_csv(o.csv_path, sep=o.delimiter, encoding=o.encoding, nrows=0)
        csv_cols = list(csv_head.columns)

        parquet_head = pq.read_table(o.parquet_path, columns=None).to_pandas().head(0)
        parquet_cols = list(parquet_head.columns)

        csv_bytes = file_size(o.csv_path)
        pq_bytes = file_size(o.parquet_path)

        return {
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


# ---------------------------
# Matplotlib canvases
# ---------------------------

class SizeCanvas(FigureCanvasQTAgg):
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


class Grid4x4Canvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=7, height=6):
        self.fig = Figure(figsize=(width, height), tight_layout=True)
        super().__init__(self.fig)
        self.axes = self.fig.subplots(4, 4)
        self.fig.suptitle("CSV vs Parquet Comparison (4x4 Grid)", fontsize=12)

    def plot_4x4(self, df_csv: pd.DataFrame, df_parquet: pd.DataFrame, time_unit: str = "s"):
        self.fig.subplots_adjust(top=0.92)
        for row in self.axes:
            for ax in row:
                ax.clear()

        dfc = parse_time_and_cast_numeric(df_csv, time_unit=time_unit)
        dfp = parse_time_and_cast_numeric(df_parquet, time_unit=time_unit)

        pairs: List[Tuple[str, str]] = [
            ("Voltage", "Voltage (V)"),
            ("Current", "Current (A)"),
            ("Temperature", "Temperature (C)"),
            ("SOC", "State of Charge (%)"),
        ]

        for col_idx, (col, label) in enumerate(pairs):
            for row_idx in (0, 1):
                ax = self.axes[row_idx][col_idx]
                ax.plot(dfc["Time"], dfc[col], linewidth=0.9, label=f"{col} CSV")
                ax.set_ylabel(label if col_idx == 0 else "")
                if row_idx == 1:
                    ax.set_xlabel("Time")
                ax.set_title(f"{label} (CSV)")
                ax.grid(True, linestyle="--", alpha=0.3)
                ax.legend(loc="best", fontsize=8)

        for col_idx, (col, label) in enumerate(pairs):
            for row_idx in (2, 3):
                ax = self.axes[row_idx][col_idx]
                ax.plot(dfp["Time"], dfp[col], linewidth=0.9, label=f"{col} Parquet")
                ax.set_ylabel(label if col_idx == 0 else "")
                if row_idx == 3:
                    ax.set_xlabel("Time")
                ax.set_title(f"{label} (Parquet)")
                ax.grid(True, linestyle="--", alpha=0.3)
                ax.legend(loc="best", fontsize=8)

        for row in self.axes:
            for ax in row:
                ax.tick_params(axis="x", labelrotation=25)

        self.draw()


# ---------------------------
# Main Window
# ---------------------------

class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CSV to Parquet Converter")
        self.setMinimumSize(1100, 720)
        self.worker: Optional[ConverterWorker] = None

        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

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

        act_lay = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Convert")
        self.run_btn.clicked.connect(self._run_conversion)

        self.plot4x4_btn = QtWidgets.QPushButton("Plot 4x4 Compare")
        self.plot4x4_btn.clicked.connect(self._plot_4x4)
        self.plot4x4_btn.setEnabled(False)

        self.save_plot_btn = QtWidgets.QPushButton("Save Current Plot")
        self.save_plot_btn.clicked.connect(self._save_plot)
        self.save_plot_btn.setEnabled(False)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        act_lay.addWidget(self.run_btn)
        act_lay.addWidget(self.plot4x4_btn)
        act_lay.addWidget(self.save_plot_btn)
        act_lay.addStretch(1)
        act_lay.addWidget(self.progress)

        out_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        plot_tabs = QtWidgets.QTabWidget()
        self.size_canvas = SizeCanvas(self, width=6, height=4)
        self.grid_canvas = Grid4x4Canvas(self, width=8, height=7)

        size_tab = QtWidgets.QWidget()
        size_lay = QtWidgets.QVBoxLayout(size_tab)
        size_lay.addWidget(self.size_canvas)

        grid_tab = QtWidgets.QWidget()
        grid_lay = QtWidgets.QVBoxLayout(grid_tab)
        grid_lay.addWidget(self.grid_canvas)

        plot_tabs.addTab(size_tab, "Size Comparison")
        plot_tabs.addTab(grid_tab, "4x4 CSV vs Parquet")

        out_split.addWidget(plot_tabs)

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
        out_split.setStretchFactor(0, 2)
        out_split.setStretchFactor(1, 1)

        layout.addWidget(path_group)
        layout.addWidget(opt_group)
        layout.addLayout(act_lay)
        layout.addWidget(out_split, 1)

    # -----------------------
    # UI Handlers
    # -----------------------

    def _browse_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select CSV", CSV_DIR, "CSV files (*.csv);;All files (*)"
        )
        if path:
            self.csv_edit.setText(path)
            base = os.path.splitext(os.path.basename(path))[0]
            enforced_pq = os.path.join(PARQUET_DIR, f"{base}.parquet")
            self.parquet_edit.setText(enforced_pq)

    def _browse_parquet(self):
        # Always enforce writing to ./parquet, regardless of user browse target
        suggested = os.path.join(PARQUET_DIR, "output.parquet")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select Parquet Output (saved in ./parquet)", suggested, "Parquet files (*.parquet)"
        )
        if path:
            base = os.path.splitext(os.path.basename(path))[0]
            enforced = os.path.join(PARQUET_DIR, f"{base}.parquet")
            self.parquet_edit.setText(enforced)

    def _run_conversion(self):
        csv_path = self.csv_edit.text().strip()
        pq_path = self.parquet_edit.text().strip()
        if not csv_path or not pq_path:
            QtWidgets.QMessageBox.warning(self, "Error", "CSV input and Parquet output paths are required.")
            return

        # Enforce folders
        csv_base = os.path.basename(csv_path)
        if os.path.dirname(os.path.abspath(csv_path)) != os.path.abspath(CSV_DIR):
            QtWidgets.QMessageBox.warning(self, "Warning", "CSV will be read from outside ./csv.")
        pq_base = os.path.splitext(os.path.basename(pq_path))[0]
        pq_path = os.path.join(PARQUET_DIR, f"{pq_base}.parquet")
        self.parquet_edit.setText(pq_path)

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

        self.progress.setValue(0)
        self.log_text.clear()
        self.parity_text.clear()
        self.save_plot_btn.setEnabled(False)
        self.plot4x4_btn.setEnabled(False)
        self.size_canvas.plot_sizes(float("nan"), float("nan"))

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

        self.size_canvas.plot_sizes(payload.get("csv_mb"), payload.get("parquet_mb"))
        self.save_plot_btn.setEnabled(True)
        self.plot4x4_btn.setEnabled(True)

        # Auto-save size comparison plot to ./plots
        pq_path = self.parquet_edit.text().strip()
        size_out = plot_output_path(pq_path, "size")
        autosave_figure(self.size_canvas.fig, size_out, self._append_log)

        self._append_log("Done.")

    def _on_failed(self, msg: str):
        self.run_btn.setEnabled(True)
        self._append_log(f"Error: {msg}")
        QtWidgets.QMessageBox.critical(self, "Conversion failed", msg)

    def _plot_4x4(self):
        csv_path = self.csv_edit.text().strip()
        pq_path = self.parquet_edit.text().strip()
        if not (os.path.exists(csv_path) and os.path.exists(pq_path)):
            QtWidgets.QMessageBox.warning(self, "Error", "CSV and Parquet files must exist.")
            return

        df_csv = pd.read_csv(csv_path, sep=self.delim_edit.text() or ",", encoding=self.enc_edit.text() or "utf-8")
        df_parquet = pd.read_parquet(pq_path)

        self._append_log(f"CSV columns: {df_csv.columns.tolist()}")
        self._append_log(f"Parquet columns: {df_parquet.columns.tolist()}")

        self.grid_canvas.plot_4x4(df_csv, df_parquet, time_unit="s")  # change to "ms" if needed

        # Auto-save 4x4 comparison plot to ./plots
        comp_out = plot_output_path(pq_path, "compare_4x4")
        autosave_figure(self.grid_canvas.fig, comp_out, self._append_log)

    def _save_plot(self):
        """
        Manual save: default into the top-level ./plots folder.
        """
        ensure_parent_dir(os.path.join(PLOTS_DIR, "dummy.png"))  # ensure folder exists

        default_path = os.path.join(PLOTS_DIR, "plot.png")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Plot", default_path, "PNG files (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            parent = self.grid_canvas.parent()
            use_grid = False
            if isinstance(parent, QtWidgets.QWidget):
                tabw = parent.parent()
                if isinstance(tabw, QtWidgets.QTabWidget):
                    use_grid = (tabw.currentIndex() == 1)
            fig = self.grid_canvas.fig if use_grid else self.size_canvas.fig
            fig.savefig(path, dpi=150)
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
