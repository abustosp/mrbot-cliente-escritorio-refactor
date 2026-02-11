import os
import tkinter as tk
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd
from tkinter import filedialog, messagebox, ttk

from mrbot_app.files import open_with_default_app
from mrbot_app.helpers import df_preview, make_today_str
from mrbot_app.windows.minio_helpers import (
    collect_minio_links,
    download_links,
    prepare_download_dir,
)


class ExcelHandlerMixin:
    """
    Mixin para manejo de archivos Excel (carga, previsualización, ejemplo).
    Requiere que la clase base tenga:
    - self.example_paths: Dict[str, str]
    - self.bring_to_front()
    - self.set_preview(widget, text)
    - self.preview: widget de texto para mensajes cortos
    - self.open_df_preview(df, title)
    """

    def __init__(self, *args, **kwargs):
        self.excel_df: Optional[pd.DataFrame] = None
        self.excel_filename: Optional[str] = None
        super().__init__(*args, **kwargs)

    def abrir_ejemplo_key(self, key: str) -> None:
        """Abre el archivo de ejemplo asociado a la key en self.example_paths."""
        path = getattr(self, "example_paths", {}).get(key)
        if not path:
            messagebox.showerror("Error", "No se encontró el Excel de ejemplo.")
            return
        if not open_with_default_app(path):
            messagebox.showerror("Error", "No se pudo abrir el Excel de ejemplo.")

    def cargar_excel(self) -> None:
        """Carga un Excel y lo asigna a self.excel_df."""
        filename = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if hasattr(self, "bring_to_front"):
            self.bring_to_front()
        if not filename:
            return
        self.excel_filename = filename
        try:
            df = pd.read_excel(filename, dtype=str).fillna("")
            df.columns = [c.strip().lower() for c in df.columns]
            self.excel_df = df

            # Preview automático
            processed = self._filter_procesar(df)
            preview_text = df_preview(processed if processed is not None else df)

            if hasattr(self, "set_preview") and hasattr(self, "preview"):
                self.set_preview(self.preview, preview_text)

        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo leer el Excel: {exc}")
            self.excel_df = None

    def previsualizar_excel(self, title: str = "Previsualización") -> None:
        """Abre la ventana emergente con el dataframe cargado."""
        if self.excel_df is None:
            messagebox.showwarning("Aviso", "No hay Excel cargado.")
            return
        filtered = self._filter_procesar(self.excel_df)
        if hasattr(self, "open_df_preview"):
            self.open_df_preview(filtered if filtered is not None else self.excel_df, title)

    def _filter_procesar(self, df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Filtra las filas donde la columna 'procesar' es afirmativa."""
        if df is None:
            return None
        filtered = df
        if "procesar" in filtered.columns:
            procesar_series = filtered["procesar"].astype(str).str.strip().str.lower()
            filtered = filtered[procesar_series.isin(["si", "sí", "yes", "y", "1"])]
        return filtered


class DateRangeHandlerMixin:
    """
    Mixin para manejo de fechas Desde/Hasta.
    """
    def __init__(self, *args, **kwargs):
        self.desde_var = tk.StringVar(value=f"01/01/{date.today().year}")
        self.hasta_var = tk.StringVar(value=make_today_str())
        super().__init__(*args, **kwargs)

    def add_date_range_frame(self, parent, label_desde="Desde (DD/MM/AAAA)", label_hasta="Hasta (DD/MM/AAAA)"):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)

        ttk.Label(frame, text=label_desde).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Label(frame, text=label_hasta).grid(row=1, column=0, padx=4, pady=2, sticky="w")

        ttk.Entry(frame, textvariable=self.desde_var, width=15).grid(row=0, column=1, padx=4, pady=2, sticky="w")
        ttk.Entry(frame, textvariable=self.hasta_var, width=15).grid(row=1, column=1, padx=4, pady=2, sticky="w")

        return frame


class DownloadHandlerMixin:
    """
    Mixin para manejo de directorio de descarga y descargas MinIO.
    """
    def __init__(self, *args, **kwargs):
        self.download_dir_var = tk.StringVar()
        super().__init__(*args, **kwargs)

    def add_download_path_frame(self, parent, label="Carpeta descargas (opcional)"):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)

        ttk.Label(frame, text=label).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(frame, textvariable=self.download_dir_var, width=45).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(frame, text="Elegir carpeta", command=self.seleccionar_carpeta_descarga).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        frame.columnconfigure(1, weight=1)
        return frame

    def seleccionar_carpeta_descarga(self) -> None:
        folder = filedialog.askdirectory()
        if hasattr(self, "bring_to_front"):
            self.bring_to_front()
        if folder:
            self.download_dir_var.set(folder)

    def _extract_links_generic(self, data: Any, service_key: str) -> List[Dict[str, str]]:
        """
        Extracción genérica usando collect_minio_links.
        Las clases hijas pueden sobreescribir _extract_links si necesitan lógica específica.
        """
        return collect_minio_links(data, service_key)

    def _process_downloads(self, data: Any, module_name: str, cuit_repr: str, override_dir: Optional[str] = None, service_key: str = "archivo") -> tuple[int, List[str], Optional[str]]:
        """
        Procesa la descarga de archivos desde la respuesta data.
        """
        # Intentar usar método específico de la clase si existe, sino genérico
        if hasattr(self, "_extract_links"):
            links = self._extract_links(data)
        else:
            links = self._extract_links_generic(data, service_key)

        if not links:
            return 0, [], None

        target_dir = override_dir or self.download_dir_var.get()
        download_dir, dir_msgs = prepare_download_dir(module_name, target_dir, cuit_repr)

        # Loggear mensajes de directorio si existe log_info
        if hasattr(self, "log_info"):
            for msg in dir_msgs:
                self.log_info(msg)

        downloads, errors = download_links(links, download_dir)
        return downloads, errors, download_dir
