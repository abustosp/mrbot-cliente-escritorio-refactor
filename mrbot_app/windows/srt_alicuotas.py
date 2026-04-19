import concurrent.futures
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.config import get_max_workers
from mrbot_app.helpers import df_preview, parse_bool_cell
from mrbot_app.srt_alicuotas import (
    consultar_srt_alicuotas,
    normalize_srt_consulta_rows,
    parse_cuits_input,
    save_consultas_json_by_cuit,
    save_consolidated_excel,
)
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import DownloadHandlerMixin, ExcelHandlerMixin


class SrtAlicuotasWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "SRT"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="SRT - Alicuotas ART", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.add_section_label(container, "SRT - Alicuotas ART")
        self.add_info_label(
            container,
            "Consulta individual o masiva. Guarda JSON individual por contribuyente y genera Excel consolidado.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT login").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUITs consulta (coma, ; o salto de linea)").grid(row=2, column=0, sticky="nw", padx=4, pady=2)

        self.cuit_login_var = tk.StringVar()
        self.clave_var = tk.StringVar()
        self.proxy_var = tk.BooleanVar(value=False)

        ttk.Entry(inputs, textvariable=self.cuit_login_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")

        self.cuits_text = tk.Text(inputs, height=4, width=40, background="#1e1e1e", foreground="#ffffff")
        self.cuits_text.grid(row=2, column=1, padx=4, pady=2, sticky="ew")

        inputs.columnconfigure(1, weight=1)

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=2)
        ttk.Checkbutton(opts, text="proxy_request", variable=self.proxy_var).grid(row=0, column=0, padx=4, pady=2, sticky="w")

        self.add_download_path_frame(container, label="Carpeta de salida (opcional)")

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("srt_alicuotas.xlsx")).grid(
            row=0, column=2, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualizacion SRT"),).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=10, service="srt_alicuotas")

    def _get_output_dir(self, override: str = "") -> str:
        target = (override or "").strip() or self.download_dir_var.get().strip()
        if target:
            return target
        return os.path.join("descargas", self.MODULE_DIR)

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _cuits_from_widget(self) -> List[str]:
        raw = self.cuits_text.get("1.0", tk.END)
        return parse_cuits_input(raw)

    def _build_row_payload(self, row: Any, default_proxy: bool) -> Dict[str, Any]:
        proxy_request = None
        if "proxy_request" in row.index:
            proxy_request = parse_bool_cell(row.get("proxy_request"), default=default_proxy)

        cuits_raw = row.get("cuits_consulta", "")
        if not str(cuits_raw).strip() and "cuits" in row.index:
            cuits_raw = row.get("cuits", "")
        if not str(cuits_raw).strip() and "cuit_consulta" in row.index:
            cuits_raw = row.get("cuit_consulta", "")
        if not str(cuits_raw).strip() and "cuit_representado" in row.index:
            cuits_raw = row.get("cuit_representado", "")

        return {
            "cuit_login": str(row.get("cuit_login", "")).strip(),
            "clave": str(row.get("clave", "")),
            "cuits_consulta": parse_cuits_input(cuits_raw),
            "proxy_request": proxy_request,
            "output_dir": str(
                row.get("ubicacion_descarga")
                or row.get("path_descarga")
                or row.get("carpeta_descarga")
                or ""
            ).strip(),
            "retry": row.get("retry", 0),
        }

    def consulta_individual(self) -> None:
        cuit_login = self.cuit_login_var.get().strip()
        clave = self.clave_var.get()
        cuits_consulta = self._cuits_from_widget()

        if not cuit_login or not clave:
            messagebox.showerror("Error", "Completa CUIT login y clave.")
            return
        if not cuits_consulta:
            messagebox.showerror("Error", "Ingresa al menos un CUIT en 'cuits_consulta'.")
            return

        base_url, api_key, email = self._get_config()
        output_dir = self._get_output_dir()
        proxy_request = bool(self.proxy_var.get())

        self.clear_logs()
        self.log_start("SRT Alicuotas", {"modo": "individual", "cuits": len(cuits_consulta)})

        self.run_in_thread(
            self.run_with_log_block,
            cuit_login,
            self._worker_individual,
            base_url,
            api_key,
            email,
            cuit_login,
            clave,
            cuits_consulta,
            proxy_request,
            output_dir,
        )

    def _worker_individual(
        self,
        base_url: str,
        api_key: str,
        email: str,
        cuit_login: str,
        clave: str,
        cuits_consulta: List[str],
        proxy_request: bool,
        output_dir: str,
    ) -> None:
        response = consultar_srt_alicuotas(
            base_url=base_url,
            api_key=api_key,
            email=email,
            cuit_login=cuit_login,
            clave=clave,
            cuits_consulta=cuits_consulta,
            proxy_request=proxy_request,
        )

        self.log_request_started(response.get("request_payload_safe"))
        self.log_response_finished(response.get("http_status"), response.get("data"))

        data = response.get("data", {})
        consultas = data.get("consultas") if isinstance(data, dict) else []

        json_paths = save_consultas_json_by_cuit(consultas, output_dir)
        detail_rows = normalize_srt_consulta_rows(consultas)
        excel_path = save_consolidated_excel(detail_rows, output_dir)

        if json_paths:
            self.log_info(f"JSON individuales guardados: {len(json_paths)}")
        else:
            self.log_info("No se guardaron JSON individuales.")

        if excel_path:
            self.log_info(f"Excel consolidado: {excel_path}")
        else:
            self.log_info("No se genero Excel consolidado.")

        self.set_preview(self.result_box, json.dumps(response, indent=2, ensure_ascii=False, default=str))

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

        base_url, api_key, email = self._get_config()
        default_proxy = bool(self.proxy_var.get())
        output_dir = self._get_output_dir()

        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("SRT Alicuotas", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, base_url, api_key, email, default_proxy, output_dir)

    def _worker_excel(
        self,
        df: pd.DataFrame,
        base_url: str,
        api_key: str,
        email: str,
        default_proxy: bool,
        output_dir: str,
    ) -> None:
        summaries: List[Dict[str, Any]] = []
        all_detail_rows: List[Dict[str, Any]] = []

        total = len(df)
        self.set_progress(0, total)

        max_workers = get_max_workers()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.run_with_log_block,
                    str(row.get("cuit_login", "")).strip() or f"fila_{idx}",
                    self._process_row,
                    row,
                    base_url,
                    api_key,
                    email,
                    default_proxy,
                    output_dir,
                ): idx
                for idx, (_, row) in enumerate(df.iterrows(), start=1)
            }

            completed = 0
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                if self._abort_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    result = future.result()
                    if result:
                        summaries.append(result["summary"])
                        all_detail_rows.extend(result["rows"])
                except Exception as exc:
                    self.log_error(f"Error en fila {futures[future]}: {exc}")

                self.set_progress(completed, total)

        excel_path = save_consolidated_excel(all_detail_rows, output_dir)
        if excel_path:
            self.log_info(f"Excel consolidado final: {excel_path}")
        else:
            self.log_info("Sin datos para consolidado final.")

        out_df = pd.DataFrame(summaries)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(50, len(out_df))))

    def _process_row(
        self,
        row: Any,
        base_url: str,
        api_key: str,
        email: str,
        default_proxy: bool,
        default_output_dir: str,
    ) -> Optional[Dict[str, Any]]:
        payload = self._build_row_payload(row, default_proxy)

        if not payload["cuit_login"] or not payload["clave"]:
            self.log_error("Fila omitida: faltan cuit_login o clave.")
            return {
                "summary": {
                    "cuit_login": payload["cuit_login"],
                    "http_status": None,
                    "consultas_ok": 0,
                    "consultas_error": 0,
                    "json_guardados": 0,
                    "error": "faltan credenciales",
                },
                "rows": [],
            }

        if not payload["cuits_consulta"]:
            self.log_error("Fila omitida: cuits_consulta vacio.")
            return {
                "summary": {
                    "cuit_login": payload["cuit_login"],
                    "http_status": None,
                    "consultas_ok": 0,
                    "consultas_error": 0,
                    "json_guardados": 0,
                    "error": "cuits_consulta vacio",
                },
                "rows": [],
            }

        try:
            retry_val = int(payload.get("retry", 0))
        except (TypeError, ValueError):
            retry_val = 0
        total_attempts = retry_val if retry_val > 1 else 1

        resp: Dict[str, Any] = {}
        for attempt in range(1, total_attempts + 1):
            resp = consultar_srt_alicuotas(
                base_url=base_url,
                api_key=api_key,
                email=email,
                cuit_login=payload["cuit_login"],
                clave=payload["clave"],
                cuits_consulta=payload["cuits_consulta"],
                proxy_request=payload["proxy_request"],
            )
            self.log_request_started(
                resp.get("request_payload_safe"),
                attempt=attempt,
                total_attempts=total_attempts,
            )
            self.log_response_finished(resp.get("http_status"), resp.get("data"))
            if resp.get("http_status") == 200:
                break

        data = resp.get("data", {})
        consultas = data.get("consultas") if isinstance(data, dict) else []

        row_output_dir = (payload.get("output_dir", "") or "").strip() or default_output_dir

        json_paths = save_consultas_json_by_cuit(consultas, row_output_dir)
        detail_rows = normalize_srt_consulta_rows(consultas)

        consultas_ok = data.get("consultas_ok") if isinstance(data, dict) else None
        consultas_error = data.get("consultas_error") if isinstance(data, dict) else None

        summary = {
            "cuit_login": payload["cuit_login"],
            "http_status": resp.get("http_status"),
            "consultas_solicitadas": len(payload["cuits_consulta"]),
            "consultas_ok": consultas_ok,
            "consultas_error": consultas_error,
            "json_guardados": len(json_paths),
            "error": "; ".join(data.get("errors", [])) if isinstance(data, dict) and isinstance(data.get("errors"), list) else None,
        }

        return {"summary": summary, "rows": detail_rows}
