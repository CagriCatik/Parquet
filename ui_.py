import sys
import pandas as pd

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QFileDialog, QTableView, QMessageBox,
    QLineEdit, QStatusBar, QMenu
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex, Slot

class PandasModel(QAbstractTableModel):
    def __init__(self, df=pd.DataFrame(), parent=None):
        super().__init__(parent)
        self._df = df

    def rowCount(self, parent=QModelIndex()):
        return self._df.shape[0]

    def columnCount(self, parent=QModelIndex()):
        return self._df.shape[1]

    def data(self, index, role=Qt.DisplayRole):
        # return value for both display and editing
        if index.isValid() and role in (Qt.DisplayRole, Qt.EditRole):
            value = self._df.iat[index.row(), index.column()]
            return "" if pd.isna(value) else str(value)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return super().headerData(section, orientation, role)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        # editable
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and role == Qt.EditRole:
            # write back to DataFrame, converting empty string to NaN
            self._df.iat[index.row(), index.column()] = value if value != "" else pd.NA
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            return True
        return False

    def update_data(self, df):
        self.beginResetModel()
        self._df = df
        self.endResetModel()

class ParquetViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parquet File Viewer")
        # set custom parser icon
        self.setWindowIcon(QIcon("parser.png"))
        self.resize(1000, 600)

        self.df = pd.DataFrame()
        self.filtered_df = pd.DataFrame()
        self.model = PandasModel(self.filtered_df)

        self._create_actions()
        self._create_menu()
        self._create_main_widget()
        self._create_status_bar()

    def _create_actions(self):
        self.open_action = QAction("Open", self)
        self.open_action.triggered.connect(self.load_parquet)

        self.export_csv_action = QAction("Export CSV", self)
        self.export_csv_action.triggered.connect(self.export_to_csv)

        self.export_excel_action = QAction("Export Excel", self)
        self.export_excel_action.triggered.connect(self.export_to_excel)

        self.save_parquet_action = QAction("Save Parquet", self)
        self.save_parquet_action.triggered.connect(self.save_parquet)

        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)

    def _create_menu(self):
        menubar = self.menuBar()
        menubar.addAction(self.open_action)
        menubar.addAction(self.export_csv_action)
        menubar.addAction(self.export_excel_action)
        menubar.addAction(self.save_parquet_action)
        menubar.addAction(self.exit_action)

    def _create_main_widget(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.search_bar)
        main_layout.addLayout(search_layout)

        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_row_menu)

        header = self.table_view.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_menu)

        main_layout.addWidget(self.table_view)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def _create_status_bar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)

    @Slot()
    def show_header_menu(self, pos):
        header = self.table_view.horizontalHeader()
        menu = QMenu(self)
        for i, col in enumerate(self.filtered_df.columns):
            action = QAction(col, self, checkable=True)
            action.setChecked(not self.table_view.isColumnHidden(i))
            action.toggled.connect(lambda checked, i=i: self.table_view.setColumnHidden(i, not checked))
            menu.addAction(action)
        menu.exec(header.mapToGlobal(pos))

    @Slot()
    def show_row_menu(self, pos):
        idx = self.table_view.indexAt(pos)
        if not idx.isValid():
            return
        menu = QMenu(self)
        delete = QAction("Delete Row", self)
        delete.triggered.connect(lambda: self.delete_row(idx.row()))
        menu.addAction(delete)
        menu.exec(self.table_view.mapToGlobal(pos))

    def delete_row(self, row):
        index_label = self.filtered_df.index[row]
        self.df = self.df.drop(index_label)
        self.filter_table(self.search_bar.text())
        self.status.showMessage(f"Deleted row {index_label}", 5000)

    @Slot()
    def load_parquet(self):
        last_dir = getattr(self, 'last_dir', '')
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Parquet File", last_dir, "Parquet Files (*.parquet);;All Files (*)")
        if file_path:
            try:
                self.df = pd.read_parquet(file_path, engine="pyarrow")
                self.filtered_df = self.df.copy()
                self.model.update_data(self.filtered_df)
                self.last_dir = __import__('os').path.dirname(file_path)
                self.status.showMessage(f"Loaded {file_path}", 5000)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load file:\n{e}")

    @Slot()
    def export_to_csv(self):
        if self.filtered_df.empty:
            QMessageBox.warning(self, "No Data", "There is no data to export.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save CSV", getattr(self, 'last_dir', ''), "CSV Files (*.csv);;All Files (*)")
        if file_path:
            try:
                self.filtered_df.to_csv(file_path, index=False)
                self.status.showMessage(f"Exported to {file_path}", 5000)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export file:\n{e}")

    @Slot()
    def export_to_excel(self):
        if self.filtered_df.empty:
            QMessageBox.warning(self, "No Data", "There is no data to export.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Excel", getattr(self, 'last_dir', ''), "Excel Files (*.xlsx);;All Files (*)")
        if file_path:
            try:
                self.filtered_df.to_excel(file_path, index=False, engine="openpyxl")
                self.status.showMessage(f"Exported to {file_path}", 5000)
            except ModuleNotFoundError as e:
                missing = e.name
                QMessageBox.critical(self, "Missing Dependency", f"Cannot export to Excel because the '{missing}' library is not installed.\nPlease install it with:\n\n    pip install {missing}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export file:\n{e}")

    @Slot()
    def save_parquet(self):
        if self.filtered_df.empty:
            QMessageBox.warning(self, "No Data", "There is no data to save.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Parquet", getattr(self, 'last_dir', ''), "Parquet Files (*.parquet);;All Files (*)")
        if file_path:
            try:
                self.filtered_df.to_parquet(file_path, index=False, engine="pyarrow")
                self.status.showMessage(f"Saved to {file_path}", 5000)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    @Slot(str)
    def filter_table(self, text):
        if self.df.empty:
            return
        if text:
            self.filtered_df = self.df[self.df.apply(lambda row: row.astype(str).str.contains(text, case=False).any(), axis=1)]
        else:
            self.filtered_df = self.df.copy()
        self.model.update_data(self.filtered_df)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = ParquetViewer()
    viewer.show()
    sys.exit(app.exec())
