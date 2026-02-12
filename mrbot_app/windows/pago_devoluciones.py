import concurrent.futures
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.config import get_max_workers
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import build_link, collect_minio_links
from mrbot_app.windows.mixins import DownloadHandlerMixin, ExcelHandlerMixin


class PagoDevolucionesWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "Pago_Devoluciones"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Pago Devoluciones", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Pago Devoluciones")
        self.add_info_label(
            container,
            "Consulta individual o masiva por CUIT. Endpoint: /api/v1/pago_devoluciones/consulta. "
            "Permite descarga automática desde MinIO cuando carga_minio=True.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave representante").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.cuit_rep_var = tk.StringVar()
        self.clave_rep_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_rep_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=2)
        self.proxy_var = tk.BooleanVar(value=False)
        self.carga_minio_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Proxy request", variable=self.proxy_var).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Carga MinIO", variable=self.carga_minio_var).grid(row=0, column=1, padx=4, pady=2, sticky="w")

        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("pago_devoluciones.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(
            btns,
            text="Previsualizar Excel",
            command=lambda: self.previsualizar_excel("Previsualizacion Pago Devoluciones"),
        ).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=10, service="pago_devoluciones")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_message(text)

    def _optional_value(self, value: str) -> Optional[str]:
        clean = (value or "").strip()
        return clean if clean else None

    def _bool_cell(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in {"si", "sí", "1", "true", "yes", "y"}:
            return True
        if text in {"no", "0", "false", "n"}:
            return False
        return default

    def _extract_api_error(self, data: Any) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        raw = data.get("error")
        if raw is None:
            return None
        if isinstance(raw, list):
            parts = [str(item).strip() for item in raw if str(item).strip()]
            return "; ".join(parts) if parts else None
        if isinstance(raw, dict):
            return json.dumps(raw, ensure_ascii=False)
        text = str(raw).strip()
        return text if text else None

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        links: List[Dict[str, str]] = []
        if isinstance(data, dict):
            archivo = data.get("archivo")
            if isinstance(archivo, dict):
                link = build_link(
                    archivo.get("url_minio"),
                    archivo.get("nombre"),
                    "pago_devoluciones",
                    1,
                )
                if link:
                    links.append(link)
        if not links:
            links = collect_minio_links(data, "pago_devoluciones")
        return links

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        cuit_repr = self._optional_value(self.cuit_repr_var.get())
        payload = {
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave_representante": self.clave_rep_var.get(),
            "cuit_representado": cuit_repr,
            "proxy_request": bool(self.proxy_var.get()),
            "carga_minio": bool(self.carga_minio_var.get()),
        }
        url = ensure_trailing_slash(base_url) + "api/v1/pago_devoluciones/consulta"
        self.clear_logs()

        self.run_in_thread(
            self.run_with_log_block,
            cuit_repr or payload["cuit_representante"] or "sin_cuit",
            self._worker_individual,
            url,
            headers,
            payload,
        )

    def _worker_individual(self, url, headers, payload):
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        cuit_repr = payload.get("cuit_representado")

        self.log_start("Pago Devoluciones", {"modo": "individual"})
        self.log_separator(cuit_repr or payload["cuit_representante"])
        self.log_request_started(safe_payload)
        resp = safe_post(url, headers, payload)
        data = resp.get("data", {})
        self.log_response_finished(resp.get("http_status"), data)

        api_error = self._extract_api_error(data)
        if api_error:
            self.log_error(api_error)

        cuit_folder = cuit_repr or payload["cuit_representante"]
        downloads, errors, download_dir = self._process_downloads(
            data,
            self.MODULE_DIR,
            cuit_folder,
            service_key="pago_devoluciones",
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
            messagebox.showerror("Error", "Carga un Excel primero.")
            return

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/pago_devoluciones/consulta"

        df_copy = df_to_process.copy()
        default_proxy = bool(self.proxy_var.get())
        default_carga_minio = bool(self.carga_minio_var.get())

        self.clear_logs()
        self.log_start("Pago Devoluciones", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, url, headers, default_proxy, default_carga_minio)

    def _worker_excel(self, df, url, headers, default_proxy, default_carga_minio):
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.run_with_log_block,
                    str(row.get("cuit_representado", "")).strip()
                    or str(row.get("cuit_representante", "")).strip()
                    or "sin_cuit",
                    self._process_row_pago_devoluciones,
                    row,
                    url,
                    headers,
                    default_proxy,
                    default_carga_minio,
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
                        rows.append(result)
                except Exception:
                    pass

                self.set_progress(completed, total)

        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
        self.log_info("Procesamiento masivo finalizado.")

    def _process_row_pago_devoluciones(self, row, url, headers, default_proxy, default_carga_minio):
        if self._abort_event.is_set():
            return None

        cuit_rep = str(row.get("cuit_representante", "")).strip()
        cuit_repr = self._optional_value(str(row.get("cuit_representado", "")))
        row_download = str(row.get("ubicacion_descarga") or row.get("path_descarga") or row.get("carpeta_descarga") or "").strip()
        proxy_request = self._bool_cell(row.get("proxy_request", ""), default_proxy)
        carga_minio = self._bool_cell(row.get("carga_minio", ""), default_carga_minio)

        payload = {
            "cuit_representante": cuit_rep,
            "clave_representante": str(row.get("clave_representante", "")),
            "cuit_representado": cuit_repr,
            "proxy_request": proxy_request,
            "carga_minio": carga_minio,
        }
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        self.log_separator(cuit_repr or cuit_rep)

        try:
            retry_val = int(row.get("retry", 0))
        except (ValueError, TypeError):
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

        api_error = self._extract_api_error(data)
        if api_error:
            self.log_error(api_error)

        cuit_folder = cuit_repr or cuit_rep or "desconocido"
        downloads, errors, download_dir = self._process_downloads(
            data,
            self.MODULE_DIR,
            cuit_folder,
            override_dir=row_download,
            service_key="pago_devoluciones",
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
            "error": api_error,
            "descargas": downloads,
            "errores_descarga": "; ".join(errors) if errors else None,
            "carpeta_descarga": download_dir,
        }
