from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets

from .conversion import (
    CSVToParquetOptions,
    ConversionStats,
    convert_csv_to_parquet,
    summarize_stats,
)
from .utils import ensure_parent

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
ICON_PATH = STATIC_DIR / "parser.ico"

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

    def _build_ui(self) -> None:
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

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        act_lay.addWidget(self.run_btn)
        act_lay.addStretch(1)
        act_lay.addWidget(self.progress)

        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.parity_text = QtWidgets.QPlainTextEdit()
        self.parity_text.setReadOnly(True)
        self.parity_text.setMaximumBlockCount(10000)

        out_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        log_container = QtWidgets.QWidget()
        log_lay = QtWidgets.QVBoxLayout(log_container)
        log_lay.addWidget(QtWidgets.QLabel("Logs"))
        log_lay.addWidget(self.log_text)

        parity_container = QtWidgets.QWidget()
        parity_lay = QtWidgets.QVBoxLayout(parity_container)
        parity_lay.addWidget(QtWidgets.QLabel("Parity and summary"))
        parity_lay.addWidget(self.parity_text)

        out_split.addWidget(log_container)
        out_split.addWidget(parity_container)
        out_split.setStretchFactor(0, 1)
        out_split.setStretchFactor(1, 1)

        layout.addWidget(path_group)
        layout.addWidget(opt_group)
        layout.addLayout(act_lay)
        layout.addWidget(out_split, 1)

    # -----------------------
    # UI Handlers
    # -----------------------
    def _browse_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select CSV",
            str(ROOT_DIR),
            "CSV files (*.csv);;All files (*)",
        )
        if path:
            self.csv_edit.setText(path)
            base, _ = os.path.splitext(path)
            self.parquet_edit.setText(base + ".parquet")

    def _browse_parquet(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Select Parquet Output",
            str(ROOT_DIR),
            "Parquet files (*.parquet)",
        )
        if path:
            if not path.lower().endswith(".parquet"):
                path += ".parquet"
            self.parquet_edit.setText(path)

    def _run_conversion(self) -> None:
        csv_path = self.csv_edit.text().strip()
        pq_path = self.parquet_edit.text().strip()
        if not csv_path or not pq_path:
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                "CSV input and Parquet output paths are required.",
            )
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

        self.worker = ConverterWorker(opts)
        self.worker.log_line.connect(self._append_log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished_success.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.run_btn.setEnabled(False)
        self.worker.start()

    def _append_log(self, line: str) -> None:
        self.log_text.appendPlainText(line)

    def _on_finished(self, stats: ConversionStats) -> None:
        self.run_btn.setEnabled(True)

        summary = summarize_stats(stats)
        self.parity_text.setPlainText(summary)

        self._append_log("Done.")
        self.progress.setValue(100)

    def _on_failed(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self._append_log(f"Error: {msg}")
        QtWidgets.QMessageBox.critical(self, "Conversion failed", msg)


# ---------------------------
# Viewer tab
# ---------------------------
class PandasModel(QtCore.QAbstractTableModel):
    def __init__(self, df: pd.DataFrame = pd.DataFrame(), parent=None):
        super().__init__(parent)
        self._df = df

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # type: ignore[override]
        return self._df.shape[0]

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:  # type: ignore[override]
        return self._df.shape[1]

    def data(self, index, role=QtCore.Qt.DisplayRole):  # type: ignore[override]
        if index.isValid() and role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            value = self._df.iat[index.row(), index.column()]
            return "" if pd.isna(value) else str(value)
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):  # type: ignore[override]
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return str(self._df.columns[section])
        return super().headerData(section, orientation, role)

    def flags(self, index):  # type: ignore[override]
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        return (
            QtCore.Qt.ItemIsSelectable
            | QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsEditable
        )

    def setData(self, index, value, role=QtCore.Qt.EditRole):  # type: ignore[override]
        if index.isValid() and role == QtCore.Qt.EditRole:
            self._df.iat[index.row(), index.column()] = (
                value if value != "" else pd.NA
            )
            self.dataChanged.emit(
                index,
                index,
                [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole],
            )
            return True
        return False

    def update_data(self, df: pd.DataFrame) -> None:
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

    def _build_ui(self) -> None:
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
    def show_header_menu(self, pos) -> None:
        header = self.table_view.horizontalHeader()
        menu = QtWidgets.QMenu(self)
        for i, col in enumerate(self.filtered_df.columns):
            action = QtGui.QAction(col, self, checkable=True)
            action.setChecked(not self.table_view.isColumnHidden(i))
            action.toggled.connect(
                lambda checked, i=i: self.table_view.setColumnHidden(i, not checked)
            )
            menu.addAction(action)
        menu.exec(header.mapToGlobal(pos))

    @QtCore.Slot()
    def show_row_menu(self, pos) -> None:
        idx = self.table_view.indexAt(pos)
        if not idx.isValid():
            return
        menu = QtWidgets.QMenu(self)
        delete = QtGui.QAction("Delete Row", self)
        delete.triggered.connect(lambda: self.delete_row(idx.row()))
        menu.addAction(delete)
        menu.exec(self.table_view.mapToGlobal(pos))

    def delete_row(self, row: int) -> None:
        index_label = self.filtered_df.index[row]
        self.df = self.df.drop(index_label)
        self.filter_table(self.search_bar.text())

    @QtCore.Slot()
    def load_parquet(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Parquet File",
            self.last_dir,
            "Parquet Files (*.parquet);;All Files (*)",
        )
        if file_path:
            try:
                self.df = pd.read_parquet(file_path, engine="pyarrow")
                self.filtered_df = self.df.copy()
                self.model.update_data(self.filtered_df)
                self.last_dir = os.path.dirname(file_path)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to load file:\n{e}",
                )

    @QtCore.Slot()
    def export_to_csv(self) -> None:
        if self.filtered_df.empty:
            QtWidgets.QMessageBox.warning(
                self,
                "No Data",
                "There is no data to export.",
            )
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            self.last_dir,
            "CSV Files (*.csv);;All Files (*)",
        )
        if file_path:
            try:
                self.filtered_df.to_csv(file_path, index=False)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to export file:\n{e}",
                )

    @QtCore.Slot()
    def export_to_excel(self) -> None:
        if self.filtered_df.empty:
            QtWidgets.QMessageBox.warning(
                self,
                "No Data",
                "There is no data to export.",
            )
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Excel",
            self.last_dir,
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if file_path:
            try:
                self.filtered_df.to_excel(file_path, index=False, engine="openpyxl")
            except ModuleNotFoundError as e:
                missing = e.name
                QtWidgets.QMessageBox.critical(
                    self,
                    "Missing Dependency",
                    f"Cannot export to Excel because the '{missing}' "
                    f"library is not installed.\n"
                    f"Please install it with:\n\n    pip install {missing}",
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to export file:\n{e}",
                )

    @QtCore.Slot()
    def save_parquet(self) -> None:
        if self.filtered_df.empty:
            QtWidgets.QMessageBox.warning(
                self,
                "No Data",
                "There is no data to save.",
            )
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Parquet",
            self.last_dir,
            "Parquet Files (*.parquet);;All Files (*)",
        )
        if file_path:
            try:
                self.filtered_df.to_parquet(file_path, index=False, engine="pyarrow")
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to save file:\n{e}",
                )

    @QtCore.Slot(str)
    def filter_table(self, text: str) -> None:
        if self.df.empty:
            return
        if text:
            self.filtered_df = self.df[
                self.df.apply(
                    lambda row: row.astype(str)
                    .str.contains(text, case=False)
                    .any(),
                    axis=1,
                )
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

        print("Icon path:", ICON_PATH, "exists:", ICON_PATH.exists())
        if ICON_PATH.exists():
            self.setWindowIcon(QtGui.QIcon(str(ICON_PATH)))

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(ConverterTab(), "Converter")
        tabs.addTab(ViewerTab(), "Viewer")
        self.setCentralWidget(tabs)


# ---------------------------
# Entrypoint
# ---------------------------
def run() -> int:
    app = QtWidgets.QApplication(sys.argv)

    if ICON_PATH.exists():
        app.setWindowIcon(QtGui.QIcon(str(ICON_PATH)))

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
