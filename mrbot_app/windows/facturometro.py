import concurrent.futures
import json
import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional

import pandas as pd

from mrbot_app.config import get_max_workers
from mrbot_app.facturometro import (
    MODULE_DIR,
    consultar_facturometro,
    descargar_screenshot,
    guardar_resultado_json,
    generar_reporte_excel,
)
from mrbot_app.helpers import df_preview, format_date_str, parse_bool_cell
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import ExcelHandlerMixin


class FacturometroWindow(BaseWindow, ExcelHandlerMixin):
    MODULE_DIR = MODULE_DIR

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Facturómetro", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.add_section_label(container, "Control Monotributistas - Facturómetro")
        self.add_info_label(
            container,
            "Consulta el facturómetro de ARCA/ AFIP para uno o más contribuyentes.\n"
            "Descarga capturas de pantalla y genera un reporte consolidado en Excel.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT login").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave fiscal").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.cuit_var = tk.StringVar()
        self.clave_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("facturometro.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualización Facturómetro")).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=2, padx=4, pady=6, sticky="ew")
        ttk.Button(btns, text="Generar Reporte", command=self.generar_reporte).grid(row=1, column=2, columnspan=2, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=10, service="facturometro")
        self._resultados: List[Dict[str, Any]] = []

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_message(text)

    def _redact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        safe = dict(payload)
        if "clave" in safe:
            safe["clave"] = "***"
        return safe

    def _downloads_dir(self) -> str:
        return os.path.join("descargas", self.MODULE_DIR)

    def consulta_individual(self) -> None:
        cuit = self.cuit_var.get().strip()
        clave = self.clave_var.get()
        if not cuit:
            messagebox.showwarning("Advertencia", "Ingresa un CUIT")
            return

        self.clear_logs()
        self.log_start("Facturómetro", {"modo": "individual", "cuit": cuit})
        self.run_in_thread(self._worker_individual, cuit, clave)

    def _worker_individual(self, cuit: str, clave: str) -> None:
        config = self._get_config()
        self.log_separator(cuit)
        resultado = consultar_facturometro(cuit, clave, config, log_fn=self.append_log)

        base_dir = self._downloads_dir()

        json_path = guardar_resultado_json(resultado, base_dir, log_fn=self.append_log)

        if resultado["success"]:
            url = resultado.get("screenshot_url")
            if url:
                ss_path = descargar_screenshot(url, cuit, base_dir, log_fn=self.append_log)
                resultado["screenshot_path"] = ss_path

        self._resultados.append(resultado)
        self.set_preview(self.result_box, json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        self.log_info("Consulta individual finalizada.")

    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        config = self._get_config()

        df_copy = df_to_process.copy()
        self.clear_logs()
        self.log_start("Facturómetro", {"modo": "masivo", "filas": len(df_copy)})
        self.run_in_thread(self._worker_excel, df_copy, config)

    def _worker_excel(self, df: pd.DataFrame, config: tuple) -> None:
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.run_with_log_block,
                    str(row.get("cuit_login") or "").strip() or "sin_cuit",
                    self._process_row,
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
                    result = future.result()
                    if result:
                        rows.append(result)
                except Exception as exc:
                    self.log_error(f"Error en fila {idx}: {exc}")

                self.set_progress(completed, total)

        self._resultados = rows

        out_df = pd.DataFrame(rows) if rows else pd.DataFrame()
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
        self.set_execution_summary(self.build_download_execution_summary("Facturómetro", rows, total_expected=total))
        self.log_info("Procesamiento masivo finalizado.")

        self._generar_reporte_automatico()

    def _generar_reporte_automatico(self) -> None:
        base_dir = self._downloads_dir()
        report_dir = base_dir
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(report_dir, f"facturometro_report_{timestamp}.xlsx")

        generar_reporte_excel(base_dir, output_path, log_fn=self.append_log)
        self.log_info(f"Reporte generado automáticamente: {output_path}")

    def _process_row(self, row: pd.Series, config: tuple) -> Optional[Dict[str, Any]]:
        if self._abort_event.is_set():
            return None

        cuit_login = str(row.get("cuit_login", "")).strip()
        clave = str(row.get("clave", ""))

        if not cuit_login:
            self.log_warning("Fila sin CUIT login, saltando.")
            return None

        resultado = consultar_facturometro(cuit_login, clave, config, log_fn=self.append_log)

        base_dir = self._downloads_dir()
        guardar_resultado_json(resultado, base_dir, log_fn=self.append_log)

        if resultado["success"]:
            url = resultado.get("screenshot_url")
            if url:
                ss_path = descargar_screenshot(url, cuit_login, base_dir, log_fn=self.append_log)
                resultado["screenshot_path"] = ss_path

        return resultado

    def generar_reporte(self) -> None:
        base_dir = self._downloads_dir()
        report_dir = base_dir
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(report_dir, f"facturometro_report_{timestamp}.xlsx")

        self.clear_logs()
        self.log_start("Facturómetro", {"accion": "generar_reporte"})
        self.run_in_thread(self._worker_generar_reporte, base_dir, output_path)

    def _worker_generar_reporte(self, base_dir: str, output_path: str) -> None:
        generar_reporte_excel(base_dir, output_path, log_fn=self.append_log)
        self.log_info(f"Reporte generado manualmente: {output_path}")
