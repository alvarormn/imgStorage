"""Aplicación GUI para buscar imágenes en unidades de almacenamiento.

Requisitos:
- Python 3.9+
- PyQt6

El script es multiplataforma y permite seleccionar una unidad o punto de montaje,
escanearla en segundo plano y listar las imágenes encontradas con su tamaño.
"""

from __future__ import annotations

import os
import sys
import platform
from pathlib import Path
from typing import List

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"}


def human_readable_size(size_bytes: int) -> str:
    """Convierte un tamaño en bytes a un formato legible (KB/MB/GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    size_kb = size_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.1f} KB"
    size_mb = size_kb / 1024
    if size_mb < 1024:
        return f"{size_mb:.1f} MB"
    size_gb = size_mb / 1024
    return f"{size_gb:.2f} GB"


class ImageScanner(QObject):
    """Escáner que busca imágenes recursivamente en un directorio."""

    progress = pyqtSignal(int)  # Progreso aproximado 0-100
    found_image = pyqtSignal(str, int)  # Ruta, tamaño en bytes
    finished = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, root_path: Path):
        super().__init__()
        self.root_path = root_path
        self._cancelled = False

    def cancel(self) -> None:
        """Marca el escaneo como cancelado."""
        self._cancelled = True

    def run(self) -> None:
        total_checked = 0
        last_progress = 0
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            if self._cancelled:
                self.cancelled.emit()
                return

            # Elimina directorios inaccesibles para evitar errores de permisos.
            dirnames[:] = [d for d in dirnames if self._is_accessible(Path(dirpath) / d)]

            for filename in filenames:
                if self._cancelled:
                    self.cancelled.emit()
                    return

                total_checked += 1
                file_path = Path(dirpath) / filename
                if file_path.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        size = file_path.stat().st_size
                        self.found_image.emit(str(file_path), size)
                    except OSError:
                        # Ignorar archivos inaccesibles
                        pass

                # Progreso aproximado: incrementa cada 100 archivos inspeccionados.
                if total_checked % 100 == 0:
                    last_progress = (last_progress + 5) % 100
                    self.progress.emit(last_progress)

        self.progress.emit(100)
        self.finished.emit()

    @staticmethod
    def _is_accessible(path: Path) -> bool:
        """Comprueba si el directorio es accesible."""
        try:
            path.iterdir()
            return True
        except (PermissionError, OSError):
            return False


class ScannerThread(QThread):
    """Hilo dedicado a ejecutar el escáner sin bloquear la UI."""

    def __init__(self, scanner: ImageScanner):
        super().__init__()
        self.scanner = scanner

    def run(self) -> None:
        self.scanner.run()


class MainWindow(QMainWindow):
    """Ventana principal de la aplicación."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Buscador de Imágenes – Multiplataforma")
        self.setMinimumSize(900, 600)
        self._scanner_thread: ScannerThread | None = None
        self._scanner: ImageScanner | None = None

        self._setup_ui()
        self._apply_styles()
        self._populate_drives()

    def _setup_ui(self) -> None:
        container = QWidget()
        self.setCentralWidget(container)

        self.drive_label = QLabel("Unidad/Punto de montaje:")
        self.drive_combo = QComboBox()
        self.scan_button = QPushButton("Escanear unidad")
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)

        self.counter_label = QLabel("Imágenes encontradas: 0")

        self.results_table = QTableWidget(0, 2)
        self.results_table.setHorizontalHeaderLabels(["Ruta completa", "Tamaño"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.drive_label)
        controls_layout.addWidget(self.drive_combo, 1)
        controls_layout.addWidget(self.scan_button)
        controls_layout.addWidget(self.cancel_button)

        layout = QVBoxLayout()
        layout.addLayout(controls_layout)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.counter_label)
        layout.addWidget(self.results_table, 1)

        container.setLayout(layout)

        self.scan_button.clicked.connect(self.start_scan)
        self.cancel_button.clicked.connect(self.cancel_scan)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-size: 14px; }
            QMainWindow { background-color: #f5f6fa; }
            QLabel { color: #2d3436; }
            QComboBox, QPushButton { padding: 8px 12px; border-radius: 6px; }
            QComboBox { border: 1px solid #dfe6e9; background: #ffffff; }
            QPushButton { background-color: #0984e3; color: white; border: none; }
            QPushButton:hover { background-color: #74b9ff; }
            QPushButton:disabled { background-color: #b2bec3; }
            QProgressBar { border: 1px solid #dfe6e9; border-radius: 6px; text-align: center; }
            QProgressBar::chunk { background-color: #00b894; }
            QTableWidget { background: #ffffff; border: 1px solid #dfe6e9; }
            QHeaderView::section { background: #dfe6e9; padding: 6px; border: none; }
            """
        )

    def _populate_drives(self) -> None:
        """Detecta y lista las unidades según el sistema operativo."""
        self.drive_combo.clear()
        system = platform.system().lower()
        drives: List[Path] = []

        if system == "windows":
            from string import ascii_uppercase

            for letter in ascii_uppercase:
                drive = Path(f"{letter}:\\")
                if drive.exists():
                    drives.append(drive)
        else:
            possible_mounts = [Path("/"), Path("/Volumes"), Path("/media"), Path("/mnt")]
            seen = set()
            for mount in possible_mounts:
                if mount.exists():
                    drives.append(mount)
                    if mount.is_dir():
                        for child in mount.iterdir():
                            if child.is_dir() and child.exists():
                                if str(child) not in seen:
                                    drives.append(child)
                                    seen.add(str(child))

        # Eliminar duplicados conservando el orden
        unique_drives = []
        seen_paths = set()
        for drive in drives:
            drive_str = str(drive)
            if drive_str not in seen_paths:
                unique_drives.append(drive)
                seen_paths.add(drive_str)

        if not unique_drives:
            self.drive_combo.addItem("No se encontraron unidades")
            self.scan_button.setEnabled(False)
            return

        for drive in unique_drives:
            self.drive_combo.addItem(drive.as_posix(), userData=drive)

    def start_scan(self) -> None:
        if self._scanner_thread and self._scanner_thread.isRunning():
            QMessageBox.warning(self, "Escaneo en curso", "Ya hay un escaneo en ejecución.")
            return

        data = self.drive_combo.currentData()
        if not isinstance(data, Path):
            QMessageBox.warning(self, "Seleccione una unidad", "Seleccione una unidad válida para escanear.")
            return

        if not data.exists():
            QMessageBox.warning(self, "Unidad no disponible", "La unidad seleccionada no existe o no está accesible.")
            return

        self.results_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.counter_label.setText("Imágenes encontradas: 0")

        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._scanner = ImageScanner(data)
        self._scanner_thread = ScannerThread(self._scanner)

        self._scanner.found_image.connect(self._add_result)
        self._scanner.progress.connect(self.progress_bar.setValue)
        self._scanner.finished.connect(self._scan_finished)
        self._scanner.cancelled.connect(self._scan_cancelled)

        self._scanner_thread.finished.connect(self._cleanup_thread)

        self._scanner_thread.start()

    def cancel_scan(self) -> None:
        if self._scanner:
            self._scanner.cancel()

    def _add_result(self, file_path: str, size: int) -> None:
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(file_path))
        self.results_table.setItem(row, 1, QTableWidgetItem(human_readable_size(size)))
        self.counter_label.setText(f"Imágenes encontradas: {row + 1}")

    def _scan_finished(self) -> None:
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "Escaneo finalizado", "El escaneo ha finalizado.")
        self._reset_buttons()

    def _scan_cancelled(self) -> None:
        QMessageBox.information(self, "Escaneo cancelado", "El escaneo fue cancelado.")
        self._reset_buttons()

    def _reset_buttons(self) -> None:
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def _cleanup_thread(self) -> None:
        if self._scanner_thread:
            self._scanner_thread.deleteLater()
            self._scanner_thread = None
        self._scanner = None


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.setWindowIcon(QIcon())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
