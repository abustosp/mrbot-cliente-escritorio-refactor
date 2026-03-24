import concurrent.futures
import os
import glob
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, scrolledtext
import pandas as pd
from typing import Optional, Dict, Any, Callable, List

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

        self._stage_definitions = {
            "mc": {
                "title": "Descarga de Mis Comprobantes",
                "button": "Abrir log MC",
            },
            "rcel": {
                "title": "Descarga de RCEL",
                "button": "Abrir log RCEL",
            },
            "proc": {
                "title": "Procesamiento",
                "button": "Abrir log Procesamiento",
            },
        }

        self._stage_logs: Dict[str, List[str]] = {k: [] for k in self._stage_definitions}
        self._stage_log_windows: Dict[str, list[tk.Text]] = {k: [] for k in self._stage_definitions}
        self._stage_progress_bars: Dict[str, ttk.Progressbar] = {}
        self._stage_progress_labels: Dict[str, tk.StringVar] = {}

        self._build_stage_progress_section(container)
        self._build_stage_log_buttons(container)

    def _build_stage_progress_section(self, parent) -> None:
        progress_frame = ttk.LabelFrame(parent, text="Progreso por etapa")
        progress_frame.pack(fill="x", pady=(6, 0))
        progress_frame.columnconfigure(1, weight=1)

        rows = [
            ("mc", "Mis Comprobantes"),
            ("rcel", "RCEL"),
            ("proc", "Procesamiento"),
        ]

        for row_idx, (stage, label) in enumerate(rows):
            ttk.Label(progress_frame, text=label).grid(row=row_idx, column=0, sticky="w", padx=8, pady=4)
            bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
            bar.grid(row=row_idx, column=1, sticky="ew", padx=8, pady=4)
            count_var = tk.StringVar(value="0/0")
            ttk.Label(progress_frame, textvariable=count_var).grid(row=row_idx, column=2, sticky="e", padx=8, pady=4)

            self._stage_progress_bars[stage] = bar
            self._stage_progress_labels[stage] = count_var

    def _build_stage_log_buttons(self, parent) -> None:
        logs_frame = ttk.LabelFrame(parent, text="Logs")
        logs_frame.pack(fill="x", pady=(6, 0))

        ttk.Button(
            logs_frame,
            text=self._stage_definitions["mc"]["button"],
            command=lambda: self._open_stage_log_window("mc"),
        ).pack(side="left", padx=8, pady=6)

        ttk.Button(
            logs_frame,
            text=self._stage_definitions["rcel"]["button"],
            command=lambda: self._open_stage_log_window("rcel"),
        ).pack(side="left", padx=8, pady=6)

        ttk.Button(
            logs_frame,
            text=self._stage_definitions["proc"]["button"],
            command=lambda: self._open_stage_log_window("proc"),
        ).pack(side="left", padx=8, pady=6)

    def _open_stage_log_window(self, stage: str) -> None:
        stage_title = self._stage_definitions.get(stage, {}).get("title", "Logs")
        top = tk.Toplevel(self)
        top.title(f"Logs - {stage_title}")
        top.geometry("900x500")

        try:
            top.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass

        txt = scrolledtext.ScrolledText(top, wrap="word", background="#1b1b1b", foreground="#ffffff")
        txt.pack(fill="both", expand=True, padx=8, pady=8)

        txt.insert("1.0", "".join(self._stage_logs[stage]))
        txt.configure(state="disabled")

        self._stage_log_windows[stage].append(txt)

        def _on_close() -> None:
            if txt in self._stage_log_windows[stage]:
                self._stage_log_windows[stage].remove(txt)
            top.destroy()

        top.protocol("WM_DELETE_WINDOW", _on_close)

    def _set_stage_progress(self, stage: str, current: int, total: int) -> None:
        def _update() -> None:
            bar = self._stage_progress_bars.get(stage)
            label_var = self._stage_progress_labels.get(stage)
            if bar is None or label_var is None:
                return

            if total <= 0:
                bar.configure(maximum=1, value=0)
                label_var.set("0/0")
                return

            safe_current = max(0, min(int(current), int(total)))
            bar.configure(maximum=int(total), value=safe_current)
            label_var.set(f"{safe_current}/{int(total)}")

        self.after(0, _update)

    def _clear_stage_logs(self, stage: str) -> None:
        self._stage_logs[stage] = []
        for txt in list(self._stage_log_windows.get(stage, [])):
            try:
                txt.configure(state="normal")
                txt.delete("1.0", tk.END)
                txt.configure(state="disabled")
            except Exception:
                continue

    def _append_stage_log(self, stage: str, message: str) -> None:
        if not message:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = str(message).splitlines() or [""]
        formatted = "\n".join(
            f"[{timestamp}] {line}" if line else f"[{timestamp}]"
            for line in lines
        ) + "\n"

        self._stage_logs[stage].append(formatted)

        def _update_windows() -> None:
            for txt in list(self._stage_log_windows.get(stage, [])):
                try:
                    txt.configure(state="normal")
                    txt.insert(tk.END, formatted)
                    txt.see(tk.END)
                    txt.configure(state="disabled")
                except Exception:
                    continue

        self.after(0, _update_windows)

    def _log_info_stage(self, stage: str, message: str) -> None:
        self._append_stage_log(stage, f"INFO: {message}")

    def _log_error_stage(self, stage: str, message: str) -> None:
        self._append_stage_log(stage, f"ERROR: {message}")

    def _run_with_stage_log_block(self, stage: str, label: str, fn: Callable[..., Any], *args, **kwargs) -> Any:
        self._append_stage_log(stage, f"{'-' * 60}\nCONTRIBUYENTE: {label}\n{'-' * 60}")
        self._append_stage_log(stage, f"EJECUCION INICIO: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            self._log_error_stage(stage, f"Excepcion en bloque: {exc}")
            return None
        finally:
            self._append_stage_log(stage, f"EJECUCION FIN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
            self._append_stage_log(stage, "")

    def cargar_excel(self) -> None:
        super().cargar_excel()
        if self.excel_filename:
            self.lbl_excel.configure(text=f"Archivo: {os.path.basename(self.excel_filename)}", foreground="green")

    def _row_block_label(self, row: pd.Series, idx: int) -> str:
        cuit_representado = str(row.get("cuit_representado", "")).strip()
        if cuit_representado:
            return cuit_representado
        denominacion = str(row.get("denominacion_mc", "") or row.get("denominacion_rcel", "")).strip()
        if denominacion:
            return denominacion
        cuit_representante = str(row.get("cuit_representante", "")).strip()
        if cuit_representante:
            return cuit_representante
        return f"fila_{idx}"

    def descargar_mc(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            messagebox.showwarning("Advertencia", "Primero debes seleccionar un archivo Excel")
            return

        if messagebox.askyesno("Confirmar", "¿Iniciar descarga de Mis Comprobantes?"):
            self._clear_stage_logs("mc")
            self._set_stage_progress("mc", 0, 0)
            self._log_info_stage("mc", "INICIADOR: Control Monotributistas | accion=Descarga MC")
            self.run_in_thread(self._worker_mc)

    def _worker_mc(self):
        df = self.excel_df
        total = len(df)
        self._set_stage_progress("mc", 0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._run_with_stage_log_block,
                    "mc",
                    self._row_block_label(row, idx),
                    self._process_row_mc_control,
                    row,
                ): idx
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
                    self._log_error_stage("mc", f"Error en fila {idx}: {e}")

                self._set_stage_progress("mc", completed, total)

        self._log_info_stage("mc", "Descarga MC finalizada.")

    def _process_row_mc_control(self, row):
        if self._abort_event.is_set():
            return
        procesar_descarga_mc(row, log_fn=lambda msg: self._append_stage_log("mc", msg))

    def descargar_rcel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            messagebox.showwarning("Advertencia", "Primero debes seleccionar un archivo Excel")
            return

        if messagebox.askyesno("Confirmar", "¿Iniciar descarga de RCEL?"):
            self._clear_stage_logs("rcel")
            self._set_stage_progress("rcel", 0, 0)
            self._log_info_stage("rcel", "INICIADOR: Control Monotributistas | accion=Descarga RCEL")
            self.run_in_thread(self._worker_rcel)

    def _worker_rcel(self):
        df = self.excel_df
        total = len(df)
        self._set_stage_progress("rcel", 0, total)
        config = self._get_config()  # (url, api_key, email)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._run_with_stage_log_block,
                    "rcel",
                    self._row_block_label(row, idx),
                    self._process_row_rcel_control,
                    row,
                    config,
                ): idx
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
                    self._log_error_stage("rcel", f"Error en fila {idx}: {e}")

                self._set_stage_progress("rcel", completed, total)

        self._log_info_stage("rcel", "Descarga RCEL finalizada.")

    def _process_row_rcel_control(self, row, config):
        if self._abort_event.is_set():
            return
        procesar_descarga_rcel(row, config, log_fn=lambda msg: self._append_stage_log("rcel", msg))

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
            self._clear_stage_logs("proc")
            self._set_stage_progress("proc", 0, 1)
            self._log_info_stage("proc", "INICIADOR: Control Monotributistas | accion=Generar Reporte")

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
        self._log_info_stage("proc", f"Buscando archivos en: {search_path}")

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

        self._log_info_stage("proc", f"Encontrados: {len(archivos_mc)} CSVs (MC), {len(archivos_json)} JSONs (RCEL)")

        if not archivos_mc and not archivos_json:
            self._log_error_stage("proc", "No se encontraron archivos para procesar.")
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
            log_fn=lambda msg: self._append_stage_log("proc", msg)
        )

        self._set_stage_progress("proc", 1, 1)
        self._log_info_stage("proc", f"Reporte generado: {output_file}")
