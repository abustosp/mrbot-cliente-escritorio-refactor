import concurrent.futures
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.config import get_max_workers
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, format_date_str, parse_bool_cell, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import build_link, collect_minio_links
from mrbot_app.windows.mixins import (
    DateRangeHandlerMixin,
    DownloadHandlerMixin,
    ExcelHandlerMixin,
)


class LiquidacionGranosWindow(BaseWindow, ExcelHandlerMixin, DateRangeHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "Liquidacion_Granos"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Liquidacion Primaria de Granos", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DateRangeHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Consulta de Liquidacion Primaria de Granos")
        self.add_info_label(
            container,
            "Consulta individual o masiva por Excel para /api/v1/liquidacion_granos/consulta. "
            "Debe incluir cuit_representante, clave y denominacion. "
            "cuit_representado es opcional. minio_upload se envia siempre en True para descargar archivos.",
        )

        self.add_date_range_frame(container)

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave fiscal").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Denominacion").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado (opcional)").grid(row=3, column=0, sticky="w", padx=4, pady=2)

        self.cuit_rep_var = tk.StringVar()
        self.clave_var = tk.StringVar()
        self.denominacion_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.denominacion_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=2)
        self.proxy_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="proxy_request", variable=self.proxy_var).grid(row=0, column=0, padx=4, pady=2, sticky="w")

        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("liquidacion_granos.xlsx")).grid(
            row=0, column=2, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(
            btns,
            text="Previsualizar Excel",
            command=lambda: self.previsualizar_excel("Previsualizacion Liquidacion de Granos"),
        ).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=10, service="liquidacion_granos")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_message(text)

    def _optional_value(self, value: Any) -> Optional[str]:
        clean = str(value or "").strip()
        return clean if clean else None

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        links: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        if isinstance(data, dict):
            comprobantes = data.get("comprobantes")
            if isinstance(comprobantes, list):
                for idx, item in enumerate(comprobantes, start=1):
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url_minio")
                    name_hint = item.get("archivo") or item.get("tipo") or item.get("consulta")
                    link = build_link(url, name_hint, "liquidacion_granos", idx)
                    if link:
                        key = (link["url"], link["filename"])
                        if key not in seen:
                            seen.add(key)
                            links.append(link)
        if not links:
            links = collect_minio_links(data, "liquidacion_granos")
        return links

    def _redact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        safe = dict(payload)
        if "clave" in safe:
            safe["clave"] = "***"
        return safe

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        payload = {
            "desde": format_date_str(self.desde_var.get().strip()),
            "hasta": format_date_str(self.hasta_var.get().strip()),
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave": self.clave_var.get(),
            "denominacion": self.denominacion_var.get().strip(),
            "cuit_representado": self._optional_value(self.cuit_repr_var.get()),
            "minio_upload": True,
            "proxy_request": bool(self.proxy_var.get()),
        }
        url = ensure_trailing_slash(base_url) + "api/v1/liquidacion_granos/consulta"
        self.clear_logs()
        self.run_in_thread(
            self.run_with_log_block,
            payload.get("cuit_representado") or payload.get("cuit_representante") or "sin_cuit",
            self._worker_individual,
            url,
            headers,
            payload,
        )

    def _worker_individual(self, url, headers, payload):
        cuit_folder = payload.get("cuit_representado") or payload.get("cuit_representante")
        self.log_start("Liquidacion Granos", {"modo": "individual"})
        self.log_separator(cuit_folder or "sin_cuit")
        self.log_request_started(self._redact(payload))
        resp = safe_post(url, headers, payload)
        data = resp.get("data", {})
        self.log_response_finished(resp.get("http_status"), data)

        downloads, errors, download_dir = self._process_downloads(
            data, self.MODULE_DIR, cuit_folder or "desconocido", service_key="liquidacion_granos"
        )
        if downloads:
            self.log_info(f"Descargas completadas: {downloads} -> {download_dir}")
        elif data:
            self.log_info("Sin links de descarga en la respuesta.")
        for err in errors:
            self.log_error(f"Descarga: {err}")

        self.set_preview(self.result_box, json.dumps(resp, indent=2, ensure_ascii=False))

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
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/liquidacion_granos/consulta"

        default_desde = format_date_str(self.desde_var.get().strip())
        default_hasta = format_date_str(self.hasta_var.get().strip())
        default_proxy = bool(self.proxy_var.get())

        df_copy = df_to_process.copy()
        self.clear_logs()
        self.log_start("Liquidacion Granos", {"modo": "masivo", "filas": len(df_copy)})
        self.run_in_thread(self._worker_excel, df_copy, url, headers, default_desde, default_hasta, default_proxy)

    def _worker_excel(self, df, url, headers, default_desde, default_hasta, default_proxy):
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.run_with_log_block,
                    str(row.get("cuit_representado") or row.get("representado_cuit") or row.get("cuit_representante") or "").strip()
                    or "sin_cuit",
                    self._process_row_granos,
                    row,
                    url,
                    headers,
                    default_desde,
                    default_hasta,
                    default_proxy,
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
                except Exception:
                    pass

                self.set_progress(completed, total)

        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
        self.log_info("Procesamiento masivo finalizado.")

    def _process_row_granos(self, row, url, headers, default_desde, default_hasta, default_proxy):
        if self._abort_event.is_set():
            return None

        cuit_rep = str(row.get("cuit_representante", "")).strip()
        cuit_repr = self._optional_value(row.get("cuit_representado") or row.get("representado_cuit"))
        desde = format_date_str(row.get("desde", "")) or default_desde
        hasta = format_date_str(row.get("hasta", "")) or default_hasta
        proxy_request = None
        if "proxy_request" in row.index:
            proxy_request = parse_bool_cell(row.get("proxy_request"), default=default_proxy)
        row_download = str(row.get("ubicacion_descarga") or row.get("path_descarga") or row.get("carpeta_descarga") or "").strip()

        payload = {
            "desde": desde,
            "hasta": hasta,
            "cuit_representante": cuit_rep,
            "clave": str(row.get("clave", "")),
            "denominacion": str(row.get("denominacion", "")).strip(),
            "cuit_representado": cuit_repr,
            "minio_upload": True,
        }
        if proxy_request is not None:
            payload["proxy_request"] = proxy_request
        self.log_separator(cuit_repr or cuit_rep or "sin_cuit")
        safe_payload = self._redact(payload)

        try:
            retry_val = int(row.get("retry", 0))
        except (TypeError, ValueError):
            retry_val = 0
        total_attempts = retry_val if retry_val > 1 else 1

        resp: Dict[str, Any] = {}
        data: Dict[str, Any] = {}
        for attempt in range(1, total_attempts + 1):
            self.log_request_started(safe_payload, attempt=attempt, total_attempts=total_attempts)

            resp = safe_post(url, headers, payload)
            data = resp.get("data", {})
            self.log_response_finished(resp.get("http_status"), data)
            if resp.get("http_status") == 200:
                break

        cuit_folder = cuit_repr or cuit_rep or "desconocido"
        downloads, errors, download_dir = self._process_downloads(
            data, self.MODULE_DIR, cuit_folder, override_dir=row_download, service_key="liquidacion_granos"
        )
        if downloads:
            self.log_info(f"Descargas completadas: {downloads} -> {download_dir}")
        elif data:
            self.log_info("Sin links de descarga")
        for err in errors:
            self.log_error(f"Descarga: {err}")

        return {
            "cuit_representado": cuit_folder,
            "http_status": resp.get("http_status"),
            "success": data.get("success") if isinstance(data, dict) else None,
            "message": data.get("message") if isinstance(data, dict) else None,
            "descargas": downloads,
            "errores_descarga": "; ".join(errors) if errors else None,
            "carpeta_descarga": download_dir,
        }
