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


class SifereWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "SIFERE"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="SIFERE consultas", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "SIFERE consultas")
        self.add_info_label(
            container,
            "Consulta individual o masiva. Descarga automatica desde MinIO (carga_minio=True) "
            "con proxy_request=False fijo.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave representante").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Periodo (AAAAMM)").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Representado nombre").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Jurisdicciones (901-924, sep: , ; |)").grid(row=5, column=0, sticky="w", padx=4, pady=2)
        self.cuit_rep_var = tk.StringVar()
        self.clave_rep_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        self.periodo_var = tk.StringVar()
        self.nombre_repr_var = tk.StringVar()
        self.jurisdicciones_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_rep_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.periodo_var, width=25).grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.nombre_repr_var, width=25).grid(row=4, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.jurisdicciones_var, width=25).grid(row=5, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        # Download Path
        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("sifere.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualizacion SIFERE")).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=10, service="sifere")

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

    def _coerce_jurisdiccion(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]
        if text.isdigit():
            return int(text)
        return None

    def _parse_jurisdicciones(self, value: Any) -> tuple[List[int], Optional[str]]:
        if value is None:
            return [], None
        if isinstance(value, list):
            items = value
        else:
            text = str(value).strip()
            if not text:
                return [], None
            if text.lower() in {"todas", "todas las", "todas_las", "all"}:
                return list(range(901, 925)), None
            text = text.replace(";", ",").replace("|", ",")
            items = [part.strip() for part in text.split(",") if part.strip()]
        jurisdicciones: List[int] = []
        invalid: List[str] = []
        for item in items:
            if str(item).strip().lower() in {"todas", "todas las", "todas_las", "all"}:
                return list(range(901, 925)), None
            num = self._coerce_jurisdiccion(item)
            if num is None or not (901 <= num <= 924):
                invalid.append(str(item).strip())
                continue
            jurisdicciones.append(num)
        if invalid:
            invalid_text = ", ".join(invalid)
            return [], f"Jurisdicciones invalidas: {invalid_text}. Deben ser enteros entre 901 y 924."
        return jurisdicciones, None

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        links: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        if isinstance(data, dict):
            archivos_minio = data.get("archivos_minio")
            if isinstance(archivos_minio, list):
                for idx, item in enumerate(archivos_minio, start=1):
                    if not isinstance(item, dict):
                        continue
                    for key, value in item.items():
                        if isinstance(value, str) and value.strip().lower().startswith("http"):
                            hint = key if isinstance(key, str) and "." in key else None
                            link = build_link(value, hint, "sifere", idx)
                            if link:
                                link_key = (link["url"], link["filename"])
                                if link_key not in seen:
                                    seen.add(link_key)
                                    links.append(link)
        if not links:
            links = collect_minio_links(data, "sifere")
        return links

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        jurisdicciones, error = self._parse_jurisdicciones(self.jurisdicciones_var.get())
        if error:
            messagebox.showerror("Error", error)
            return
        payload = {
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave_representante": self.clave_rep_var.get(),
            "cuit_representado": self.cuit_repr_var.get().strip(),
            "periodo": self.periodo_var.get().strip(),
            "representado_nombre": self._optional_value(self.nombre_repr_var.get()),
            "jurisdicciones": jurisdicciones,
            "carga_minio": True,
            "proxy_request": False,
        }
        url = ensure_trailing_slash(base_url) + "api/v1/sifere/consulta"
        self.clear_logs()

        self.run_in_thread(self._worker_individual, url, headers, payload)

    def _worker_individual(self, url, headers, payload):
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        self.log_start("SIFERE", {"modo": "individual"})
        self.log_separator(payload["cuit_representado"])
        self.log_request(safe_payload)
        resp = safe_post(url, headers, payload)
        data = resp.get("data", {})
        self.log_response(resp.get("http_status"), data)
        cuit_folder = payload["cuit_representado"]
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
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/sifere/consulta"

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        # Copy for thread safety
        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("SIFERE", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, url, headers)

    def _worker_excel(self, df, url, headers):
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._process_row_sifere, row, url, headers): idx
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
                except Exception as e:
                    self.log_error(f"Error en fila {idx}: {e}")

                self.set_progress(completed, total)

        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))

    def _process_row_sifere(self, row, url, headers):
        if self._abort_event.is_set():
            return None

        cuit_rep = str(row.get("cuit_representante", "")).strip()
        cuit_repr = str(row.get("cuit_representado", "")).strip()
        row_download = str(row.get("ubicacion_descarga") or row.get("path_descarga") or row.get("carpeta_descarga") or "").strip()
        jurisdicciones, error = self._parse_jurisdicciones(row.get("jurisdicciones", ""))
        self.log_separator(cuit_repr)
        if error:
            self.log_error(error)
            return {
                "cuit_representado": cuit_repr,
                "http_status": None,
                "success": False,
                "message": error,
                "descargas": 0,
                "errores_descarga": None,
                "carpeta_descarga": None,
            }

        payload = {
            "cuit_representante": cuit_rep,
            "clave_representante": str(row.get("clave_representante", "")),
            "cuit_representado": cuit_repr,
            "periodo": str(row.get("periodo", "")).strip(),
            "representado_nombre": self._optional_value(str(row.get("representado_nombre", ""))),
            "jurisdicciones": jurisdicciones,
            "carga_minio": True,
            "proxy_request": False,
        }
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
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
        downloads, errors, download_dir = self._process_downloads(
            data, self.MODULE_DIR, cuit_repr, override_dir=row_download
        )
        if downloads:
            self.log_info(f"Descargas completadas: {downloads} -> {download_dir}")
        elif data:
            self.log_info("Sin links de descarga")
        for err in errors:
            self.log_error(f"Descarga: {err}")

        return {
            "cuit_representado": cuit_repr,
            "http_status": resp.get("http_status"),
            "success": data.get("success") if isinstance(data, dict) else None,
            "message": data.get("message") if isinstance(data, dict) else None,
            "descargas": downloads,
            "errores_descarga": "; ".join(errors) if errors else None,
            "carpeta_descarga": download_dir,
        }
