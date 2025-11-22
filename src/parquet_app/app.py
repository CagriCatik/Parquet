from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import pandas as pd
import pyarrow as pa
from PySide6 import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from .conversion import (
    CSVToParquetOptions,
    ConversionStats,
    convert_csv_to_parquet,
    summarize_stats,
)
from .utils import ensure_parent

ROOT_DIR = Path(__file__).resolve().parent.parent
PLOTS_DIR = ROOT_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------
# Matplotlib canvases
# ---------------------------
class SizeCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width: float = 5, height: float = 3):
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
    def __init__(self, parent=None, width: float = 7, height: float = 6):
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

        pairs = [
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
# Utilities
# ---------------------------
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


def autosave_figure(fig: Figure, path: Path, log: Callable[[str], None]):
    try:
        ensure_parent(path)
        fig.savefig(path, dpi=150)
        log(f"Plot saved: {path}")
    except Exception as e:
        log(f"Error saving plot '{path}': {e}")


# ---------------------------
# Converter worker
# ---------------------------
class ConverterWorker(QtCore.QThread):
    log_line = QtCore.Signal(str)
    progress = QtCore.Signal(int)
    finished_success = QtCore.Signal(ConversionStats)
    failed = QtCore.Signal(str)

    def __init__(self, opts: CSVToParquetOptions):
        super().__init__()
        self.opts = opts

    def run(self) -> None:
        try:
            self.progress.emit(1)
            if not os.path.exists(self.opts.csv_path):
                raise FileNotFoundError("Input CSV does not exist.")
            self.log_line.emit("Starting conversion...")
            stats = convert_csv_to_parquet(self.opts, log=self.log_line.emit)
            self.progress.emit(100)
            self.finished_success.emit(stats)
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------
# Converter tab
# ---------------------------
class ConverterTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
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
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select CSV", str(ROOT_DIR), "CSV files (*.csv);;All files (*)")
        if path:
            self.csv_edit.setText(path)
            base, _ = os.path.splitext(path)
            self.parquet_edit.setText(base + ".parquet")

    def _browse_parquet(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select Parquet Output", str(ROOT_DIR), "Parquet files (*.parquet)")
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

        opts = CSVToParquetOptions(
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

    def _on_finished(self, stats: ConversionStats):
        self.run_btn.setEnabled(True)

        summary = summarize_stats(stats)
        self.parity_text.setPlainText(summary)

        self.size_canvas.plot_sizes(stats.input_mb, stats.output_mb)
        self.save_plot_btn.setEnabled(True)
        self.plot4x4_btn.setEnabled(True)

        pq_path = Path(self.parquet_edit.text().strip())
        base_name = pq_path.stem
        size_out = PLOTS_DIR / f"{base_name}_size.png"
        autosave_figure(self.size_canvas.fig, size_out, self._append_log)

        self._append_log("Done.")
        self.progress.setValue(100)

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

        self.grid_canvas.plot_4x4(df_csv, df_parquet, time_unit="s")

        comp_out = PLOTS_DIR / f"{Path(pq_path).stem}_compare_4x4.png"
        autosave_figure(self.grid_canvas.fig, comp_out, self._append_log)

    def _save_plot(self):
        default_path = PLOTS_DIR / "plot.png"
        ensure_parent(default_path)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Plot", str(default_path), "PNG files (*.png)")
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
                    use_grid = tabw.currentIndex() == 1
            fig = self.grid_canvas.fig if use_grid else self.size_canvas.fig
            fig.savefig(path, dpi=150)
            self._append_log(f"Plot saved: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(e))


# ---------------------------
# Viewer tab
# ---------------------------
class PandasModel(QtCore.QAbstractTableModel):
    def __init__(self, df: pd.DataFrame = pd.DataFrame(), parent=None):
        super().__init__(parent)
        self._df = df

    def rowCount(self, parent=QtCore.QModelIndex()):
        return self._df.shape[0]

    def columnCount(self, parent=QtCore.QModelIndex()):
        return self._df.shape[1]

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if index.isValid() and role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            value = self._df.iat[index.row(), index.column()]
            return "" if pd.isna(value) else str(value)
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return str(self._df.columns[section])
        return super().headerData(section, orientation, role)

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        return QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if index.isValid() and role == QtCore.Qt.EditRole:
            self._df.iat[index.row(), index.column()] = value if value != "" else pd.NA
            self.dataChanged.emit(index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
            return True
        return False

    def update_data(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df
        self.endResetModel()


class ViewerTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()
        self.filtered_df = pd.DataFrame()
        self.model = PandasModel(self.filtered_df)
        self.last_dir = str(ROOT_DIR)
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        button_row = QtWidgets.QHBoxLayout()
        open_btn = QtWidgets.QPushButton("Open Parquet")
        open_btn.clicked.connect(self.load_parquet)
        export_csv = QtWidgets.QPushButton("Export CSV")
        export_csv.clicked.connect(self.export_to_csv)
        export_excel = QtWidgets.QPushButton("Export Excel")
        export_excel.clicked.connect(self.export_to_excel)
        save_parquet = QtWidgets.QPushButton("Save Parquet")
        save_parquet.clicked.connect(self.save_parquet)
        button_row.addWidget(open_btn)
        button_row.addWidget(export_csv)
        button_row.addWidget(export_excel)
        button_row.addWidget(save_parquet)
        button_row.addStretch(1)

        search_layout = QtWidgets.QHBoxLayout()
        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.search_bar)

        self.table_view = QtWidgets.QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_row_menu)

        header = self.table_view.horizontalHeader()
        header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_menu)

        layout.addLayout(button_row)
        layout.addLayout(search_layout)
        layout.addWidget(self.table_view)

    # -----------------------
    # Handlers
    # -----------------------
    @QtCore.Slot()
    def show_header_menu(self, pos):
        header = self.table_view.horizontalHeader()
        menu = QtWidgets.QMenu(self)
        for i, col in enumerate(self.filtered_df.columns):
            action = QtGui.QAction(col, self, checkable=True)
            action.setChecked(not self.table_view.isColumnHidden(i))
            action.toggled.connect(lambda checked, i=i: self.table_view.setColumnHidden(i, not checked))
            menu.addAction(action)
        menu.exec(header.mapToGlobal(pos))

    @QtCore.Slot()
    def show_row_menu(self, pos):
        idx = self.table_view.indexAt(pos)
        if not idx.isValid():
            return
        menu = QtWidgets.QMenu(self)
        delete = QtGui.QAction("Delete Row", self)
        delete.triggered.connect(lambda: self.delete_row(idx.row()))
        menu.addAction(delete)
        menu.exec(self.table_view.mapToGlobal(pos))

    def delete_row(self, row):
        index_label = self.filtered_df.index[row]
        self.df = self.df.drop(index_label)
        self.filter_table(self.search_bar.text())

    @QtCore.Slot()
    def load_parquet(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Parquet File", self.last_dir, "Parquet Files (*.parquet);;All Files (*)"
        )
        if file_path:
            try:
                self.df = pd.read_parquet(file_path, engine="pyarrow")
                self.filtered_df = self.df.copy()
                self.model.update_data(self.filtered_df)
                self.last_dir = os.path.dirname(file_path)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load file:\n{e}")

    @QtCore.Slot()
    def export_to_csv(self):
        if self.filtered_df.empty:
            QtWidgets.QMessageBox.warning(self, "No Data", "There is no data to export.")
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save CSV", self.last_dir, "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            try:
                self.filtered_df.to_csv(file_path, index=False)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to export file:\n{e}")

    @QtCore.Slot()
    def export_to_excel(self):
        if self.filtered_df.empty:
            QtWidgets.QMessageBox.warning(self, "No Data", "There is no data to export.")
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Excel", self.last_dir, "Excel Files (*.xlsx);;All Files (*)"
        )
        if file_path:
            try:
                self.filtered_df.to_excel(file_path, index=False, engine="openpyxl")
            except ModuleNotFoundError as e:
                missing = e.name
                QtWidgets.QMessageBox.critical(
                    self,
                    "Missing Dependency",
                    f"Cannot export to Excel because the '{missing}' library is not installed.\n"
                    f"Please install it with:\n\n    pip install {missing}",
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to export file:\n{e}")

    @QtCore.Slot()
    def save_parquet(self):
        if self.filtered_df.empty:
            QtWidgets.QMessageBox.warning(self, "No Data", "There is no data to save.")
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Parquet", self.last_dir, "Parquet Files (*.parquet);;All Files (*)"
        )
        if file_path:
            try:
                self.filtered_df.to_parquet(file_path, index=False, engine="pyarrow")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    @QtCore.Slot(str)
    def filter_table(self, text):
        if self.df.empty:
            return
        if text:
            self.filtered_df = self.df[
                self.df.apply(lambda row: row.astype(str).str.contains(text, case=False).any(), axis=1)
            ]
        else:
            self.filtered_df = self.df.copy()
        self.model.update_data(self.filtered_df)


# ---------------------------
# Main window
# ---------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parquet App")
        icon_path = ROOT_DIR / "static" / "parser.png"
        if icon_path.exists():
            self.setWindowIcon(QtGui.QIcon(str(icon_path)))

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(ConverterTab(), "Converter")
        tabs.addTab(ViewerTab(), "Viewer")
        self.setCentralWidget(tabs)


# ---------------------------
# Entrypoint
# ---------------------------
def run() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
