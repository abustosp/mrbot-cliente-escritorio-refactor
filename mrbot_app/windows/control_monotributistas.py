import concurrent.futures
import os
import glob
import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
from typing import Optional, Dict

from mrbot_app.config import get_max_workers
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import ExcelHandlerMixin
from mrbot_app.control_monotributistas import (
    procesar_descarga_mc,
    procesar_descarga_rcel,
    generar_reporte_control
)
from mrbot_app.constants import EXAMPLE_DIR

class ControlMonotributistasWindow(BaseWindow, ExcelHandlerMixin):
    MODULE_DIR = "control_monotributistas"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Control Monotributistas", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.add_section_label(container, "Control de Monotributistas")
        self.add_info_label(
            container,
            "Automatiza el control y recategorización descargando comprobantes MC y RCEL.\n"
            "Requiere 'Categorias.xlsx' (escalas) y planilla de control.",
        )

        # Excel Selection
        file_frame = ttk.LabelFrame(container, text="Archivo de Planilla")
        file_frame.pack(fill="x", pady=8)

        btn_frame = ttk.Frame(file_frame)
        btn_frame.pack(fill="x", pady=4, padx=4)

        ttk.Button(btn_frame, text="Seleccionar Excel", command=self.cargar_excel).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Ver Ejemplo Planilla", command=lambda: self.abrir_ejemplo_key("control_monotributistas.xlsx")).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Ver Ejemplo Categorias", command=lambda: self.abrir_ejemplo_key("Categorias.xlsx")).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualización Control Monotributistas")).pack(side="left", padx=4)

        self.lbl_excel = ttk.Label(file_frame, text="Ningún archivo seleccionado")
        self.lbl_excel.pack(anchor="w", padx=8, pady=4)

        self.preview = self.add_preview(container, height=6, show=False)
        self.set_preview(self.preview, "Selecciona un Excel para ver la previsualización.")

        # Actions
        actions_frame = ttk.LabelFrame(container, text="Acciones")
        actions_frame.pack(fill="x", pady=8)

        ttk.Button(actions_frame, text="1. Descargar Mis Comprobantes", command=self.descargar_mc).pack(fill="x", padx=8, pady=4)
        ttk.Button(actions_frame, text="2. Descargar RCEL", command=self.descargar_rcel).pack(fill="x", padx=8, pady=4)
        ttk.Button(actions_frame, text="3. Procesar y Generar Reporte", command=self.procesar_datos).pack(fill="x", padx=8, pady=4)

        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=15, service="control_mono")

    def cargar_excel(self) -> None:
        super().cargar_excel()
        if self.excel_filename:
            self.lbl_excel.configure(text=f"Archivo: {os.path.basename(self.excel_filename)}", foreground="green")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_message(text)

    def descargar_mc(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            messagebox.showwarning("Advertencia", "Primero debes seleccionar un archivo Excel")
            return

        if messagebox.askyesno("Confirmar", "¿Iniciar descarga de Mis Comprobantes?"):
            self.clear_logs()
            self.log_start("Control Monotributistas", {"accion": "Descarga MC"})
            self.run_in_thread(self._worker_mc)

    def _worker_mc(self):
        df = self.excel_df
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._process_row_mc_control, row): idx
                for idx, (_, row) in enumerate(df.iterrows(), start=1)
            }

            completed = 0
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                completed += 1
                if self._abort_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    future.result()
                except Exception as e:
                    self.log_error(f"Error en fila {idx}: {e}")

                self.set_progress(completed, total)

        self.log_info("Descarga MC finalizada.")

    def _process_row_mc_control(self, row):
        if self._abort_event.is_set():
            return
        procesar_descarga_mc(row, log_fn=self.log_message)

    def descargar_rcel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            messagebox.showwarning("Advertencia", "Primero debes seleccionar un archivo Excel")
            return

        if messagebox.askyesno("Confirmar", "¿Iniciar descarga de RCEL?"):
            self.clear_logs()
            self.log_start("Control Monotributistas", {"accion": "Descarga RCEL"})
            self.run_in_thread(self._worker_rcel)

    def _worker_rcel(self):
        df = self.excel_df
        total = len(df)
        self.set_progress(0, total)
        config = self._get_config()  # (url, api_key, email)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._process_row_rcel_control, row, config): idx
                for idx, (_, row) in enumerate(df.iterrows(), start=1)
            }

            completed = 0
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                completed += 1
                if self._abort_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    future.result()
                except Exception as e:
                    self.log_error(f"Error en fila {idx}: {e}")

                self.set_progress(completed, total)

        self.log_info("Descarga RCEL finalizada.")

    def _process_row_rcel_control(self, row, config):
        if self._abort_event.is_set():
            return
        procesar_descarga_rcel(row, config, log_fn=self.log_message)

    def procesar_datos(self) -> None:
        # Check Categorias.xlsx
        # Prefer the one in examples/Categorias.xlsx if exists, else check root
        cat_path = self.example_paths.get("Categorias.xlsx", os.path.join(EXAMPLE_DIR, "Categorias.xlsx"))
        if not os.path.exists(cat_path):
            cat_path = "Categorias.xlsx" # Check root
            if not os.path.exists(cat_path):
                 messagebox.showerror("Error", "No se encontró 'Categorias.xlsx'.\nGenera los ejemplos primero.")
                 return

        if messagebox.askyesno("Confirmar", "¿Procesar datos descargados y generar reporte?"):
            self.clear_logs()
            self.log_start("Control Monotributistas", {"accion": "Generar Reporte"})

            # Use 'descargas/RCEL' and 'descargas' generally as search paths?
            # Or assume paths from Excel?
            # The control function expects list of files.
            # We need to find them.

            # We can scan the whole 'descargas' folder or use specific paths if we knew them.
            # Since `procesar_descarga_mc` defaults to `descargas/mis_compobantes` (fallback) or user defined.
            # And `procesar_descarga_rcel` to `descargas/RCEL`.
            # We'll scan recursively in 'descargas' or '.'?
            # External repo scans `DOWNLOADS_MC_PATH` and `DOWNLOADS_RCEL_PATH`.

            # Let's assume standard paths or ask user?
            # Better: Scan 'descargas' directory recursively.

            search_path = "descargas" if os.path.exists("descargas") else "."

            self.run_in_thread(self._worker_process, cat_path, search_path)

    def _worker_process(self, cat_path, search_path):
        self.log_info(f"Buscando archivos en: {search_path}")

        # MC: extraido/*.csv
        archivos_mc = glob.glob(f"{search_path}/**/extraido/*.csv", recursive=True)
        # RCEL: *.json
        archivos_json = glob.glob(f"{search_path}/**/RCEL/**/*.json", recursive=True)
        # Note: glob might be slow if many files.
        # External repo glob: f"{downloads_mc_path}/**/extraido/*.csv"

        # Fallback if RCEL is not in RCEL subfolder (user might have changed path)
        if not archivos_json:
             archivos_json = glob.glob(f"{search_path}/**/*.json", recursive=True)
             # Filter out non-RCEL jsons? Rcel jsons usually are named like the pdf.
             # We can rely on control logic to filter/match.

        self.log_info(f"Encontrados: {len(archivos_mc)} CSVs (MC), {len(archivos_json)} JSONs (RCEL)")

        if not archivos_mc and not archivos_json:
            self.log_error("No se encontraron archivos para procesar.")
            return

        # Output directory: descargas/Control_Monotributistas
        output_dir = os.path.join("descargas", "Control_Monotributistas")
        os.makedirs(output_dir, exist_ok=True)

        output_file = os.path.join(output_dir, "Reporte Recategorizaciones de Monotributistas.xlsx")

        generar_reporte_control(
            archivos_mc,
            archivos_json,
            cat_path,
            output_file,
            log_fn=self.log_message
        )
