import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import build_link, collect_minio_links
from mrbot_app.windows.mixins import DownloadHandlerMixin, ExcelHandlerMixin


class AportesEnLineaWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "Aportes_en_linea"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Aportes en Linea", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Aportes en Linea")
        self.add_info_label(
            container,
            "Consulta individual o masiva. Descarga automatica desde MinIO (archivo_historico_minio=True) "
            "con proxy_request=False fijo.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT login").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.cuit_login_var = tk.StringVar()
        self.clave_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_login_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        # Download Path
        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("aportes_en_linea.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualizacion Aportes")).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=10, service="aportes_en_linea")

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

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        links: List[Dict[str, str]] = []
        if isinstance(data, dict):
            url = data.get("archivo_historico_minio_url")
            link = build_link(url, "aportes_historico", "aportes", 1)
            if link:
                links.append(link)
        if not links:
            links = collect_minio_links(data, "aportes")
        return links

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        cuit_repr = self._optional_value(self.cuit_repr_var.get())
        payload = {
            "cuit_login": self.cuit_login_var.get().strip(),
            "clave": self.clave_var.get(),
            "cuit_representado": cuit_repr,
            "archivo_historico_b64": False,
            "archivo_historico_minio": True,
            "proxy_request": False,
        }
        url = ensure_trailing_slash(base_url) + "api/v1/aportes-en-linea/consulta"
        self.clear_logs()

        self.run_in_thread(self._worker_individual, url, headers, payload)

    def _worker_individual(self, url, headers, payload):
        safe_payload = dict(payload)
        safe_payload["clave"] = "***"
        self.log_start("Aportes en Linea", {"modo": "individual"})
        self.log_separator(payload["cuit_representado"] or payload["cuit_login"])
        self.log_request(safe_payload)
        resp = safe_post(url, headers, payload)
        data = resp.get("data", {})
        self.log_response(resp.get("http_status"), data)
        cuit_folder = payload["cuit_representado"] or payload["cuit_login"]
        downloads, errors, download_dir = self._process_downloads(data, self.MODULE_DIR, cuit_folder)
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
        url = ensure_trailing_slash(base_url) + "api/v1/aportes-en-linea/consulta"

        # Copy for thread safety
        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("Aportes en Linea", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, url, headers)

    def _worker_excel(self, df, url, headers):
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)

        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            if self._abort_event.is_set():
                break

            cuit_login = str(row.get("cuit_login", "")).strip()
            cuit_repr = self._optional_value(str(row.get("cuit_representado", "")))
            row_download = str(row.get("ubicacion_descarga") or row.get("path_descarga") or row.get("carpeta_descarga") or "").strip()
            self.log_separator(cuit_repr or cuit_login)
            payload = {
                "cuit_login": cuit_login,
                "clave": str(row.get("clave", "")),
                "cuit_representado": cuit_repr,
                "archivo_historico_b64": False,
                "archivo_historico_minio": True,
                "proxy_request": False,
            }
            safe_payload = dict(payload)
            safe_payload["clave"] = "***"
            self.log_request(safe_payload)

            try:
                retry_val = int(row.get("retry", 0))
            except (ValueError, TypeError):
                retry_val = 0
            total_attempts = retry_val if retry_val > 1 else 1

            resp = {}
            data = {}
            for attempt in range(1, total_attempts + 1):
                if attempt > 1:
                    self.log_info(f"Reintentando... (Intento {attempt}/{total_attempts})")

                resp = safe_post(url, headers, payload)
                data = resp.get("data", {})
                if resp.get("http_status") == 200:
                    break

            self.log_response(resp.get("http_status"), data)
            cuit_folder = cuit_repr or cuit_login
            downloads, errors, download_dir = self._process_downloads(
                data, self.MODULE_DIR, cuit_folder, override_dir=row_download
            )
            if downloads:
                self.log_info(f"Descargas completadas: {downloads} -> {download_dir}")
            elif data:
                self.log_info("Sin links de descarga")
            for err in errors:
                self.log_error(f"Descarga: {err}")
            rows.append(
                {
                    "cuit_representado": cuit_folder,
                    "http_status": resp.get("http_status"),
                    "status": data.get("status") if isinstance(data, dict) else None,
                    "error_message": data.get("error_message") if isinstance(data, dict) else None,
                    "descargas": downloads,
                    "errores_descarga": "; ".join(errors) if errors else None,
                    "carpeta_descarga": download_dir,
                }
            )
            self.set_progress(idx, total)
        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
