import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.consulta import descargar_archivo_minio
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, format_date_str, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import (
    DateRangeHandlerMixin,
    DownloadHandlerMixin,
    ExcelHandlerMixin,
)


class RcelWindow(BaseWindow, ExcelHandlerMixin, DateRangeHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "RCEL"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Comprobantes en Linea (RCEL)", config_provider=config_provider)
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

        self.add_section_label(container, "Descarga de Comprobantes en Linea (RCEL)")
        self.add_info_label(
            container,
            "Permite consultas individuales o masivas basadas en un Excel. "
            "Debe incluir cuit_representante, nombre_rcel, representado_cuit y clave. "
            "Opcionalmente, puedes agregar columnas desde y hasta (DD/MM/AAAA) por fila, procesar (SI/NO) y "
            "ubicacion_descarga para indicar la carpeta destino. Si no se define, se usará descargas/RCEL/{CUIT representado}.",
        )

        # Dates
        self.add_date_range_frame(container)

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Nombre RCEL").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave fiscal").grid(row=3, column=0, sticky="w", padx=4, pady=2)

        self.cuit_rep_var = tk.StringVar()
        self.nombre_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        self.clave_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.nombre_var, width=25).grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=4)
        self.b64_var = tk.BooleanVar(value=False)
        self.minio_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="PDF en base64", variable=self.b64_var).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Subir a MinIO", variable=self.minio_var).grid(row=0, column=1, padx=4, pady=2, sticky="w")

        # Download Path
        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("rcel.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualización RCEL")).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=10, service="rcel")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_message(text)

    def _sanitize_identifier(self, value: str, fallback: str = "desconocido") -> str:
        cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", (value or "").strip())
        cleaned = cleaned.strip("_")
        return cleaned or fallback

    def _is_pdf_url(self, url: Any) -> bool:
        if not isinstance(url, str):
            return False
        clean = url.strip()
        if not clean.lower().startswith("http"):
            return False
        lowered = clean.lower()
        if "minio" in lowered:
            return True
        return lowered.split("?")[0].endswith(".pdf")

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        """Overrides mixin method to extract PDF links specifically."""
        links: List[Dict[str, str]] = []
        seen: set[Tuple[str, str]] = set()

        def add_link(url: str) -> None:
            if not self._is_pdf_url(url):
                return
            url = url.strip()
            filename = os.path.basename(urlparse(url).path) or "factura.pdf"
            key = (url, filename)
            if key in seen:
                return
            seen.add(key)
            links.append({"url": url, "filename": filename})

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for _, val in obj.items():
                    if isinstance(val, (dict, list)):
                        walk(val)
                    elif isinstance(val, str):
                        add_link(val)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)
        return links

    def _extract_item_pdf_url(self, item: Dict[str, Any]) -> Optional[str]:
        for key in ("URL_MINIO", "url_minio", "url_pdf", "link_pdf", "url", "link"):
            url = item.get(key)
            if self._is_pdf_url(url):
                return str(url).strip()
        for value in item.values():
            if self._is_pdf_url(value):
                return str(value).strip()
        return None

    def _collect_pdf_items(self, data: Any) -> List[Tuple[str, Dict[str, Any]]]:
        if not isinstance(data, dict):
            return []
        collected: List[Tuple[str, Dict[str, Any]]] = []
        for key in ("facturas_emitidas", "facturas_recibidas", "comprobantes", "facturas"):
            items = data.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = self._extract_item_pdf_url(item)
                if url:
                    collected.append((url, item))
        return collected

    def _save_pdf_jsons(self, items: List[Tuple[str, Dict[str, Any]]], dest_dir: Optional[str]) -> Tuple[int, List[str]]:
        if not dest_dir:
            return 0, ["No hay ruta de descarga disponible."]
        saved = 0
        errors: List[str] = []
        seen: set[str] = set()
        for idx, (url, payload) in enumerate(items, start=1):
            filename = os.path.basename(urlparse(url).path) or f"factura_{idx}.pdf"
            if filename in seen:
                continue
            seen.add(filename)
            pdf_path = os.path.join(dest_dir, filename)
            if not os.path.exists(pdf_path):
                errors.append(f"{filename}: PDF no encontrado para guardar JSON")
                continue
            json_name = os.path.splitext(filename)[0] + ".json"
            json_path = os.path.join(dest_dir, json_name)
            try:
                with open(json_path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
                saved += 1
            except Exception as exc:
                errors.append(f"{json_name}: {exc}")
        return saved, errors

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
            "nombre_rcel": self.nombre_var.get().strip(),
            "representado_cuit": self.cuit_repr_var.get().strip(),
            "clave": self.clave_var.get(),
            "b64_pdf": bool(self.b64_var.get()),
            "minio_upload": bool(self.minio_var.get()),
        }
        url = ensure_trailing_slash(base_url) + "api/v1/rcel/consulta"
        self.clear_logs()
        self.log_start("RCEL", {"modo": "individual"})
        self.log_separator(payload["representado_cuit"])
        self.log_request(self._redact(payload))
        resp = safe_post(url, headers, payload)
        data = resp.get("data")
        self.log_response(resp.get("http_status"), data)

        cuit_folder = payload["representado_cuit"]
        downloads, download_errors, download_dir = self._process_downloads(
            data, self.MODULE_DIR, cuit_folder
        )
        if downloads:
             self.log_info(f"Descargas completadas ({downloads}) en {download_dir}")
        elif isinstance(data, dict):
             self.log_info("No se encontraron links de PDF para descargar.")

        if isinstance(data, dict):
            pdf_items = self._collect_pdf_items(data)
            if pdf_items:
                saved_json, json_errors = self._save_pdf_jsons(pdf_items, download_dir)
                if saved_json:
                    self.log_info(f"JSON guardados: {saved_json} -> {download_dir}")
                for err in json_errors:
                    self.log_error(f"JSON: {err}")

        for err in download_errors:
            self.log_error(f"Descarga: {err}")
        self.set_preview(self.result_box, json.dumps(resp, indent=2, ensure_ascii=False))

    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/rcel/consulta"
        rows: List[Dict[str, Any]] = []
        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        self.clear_logs()
        self.log_start("RCEL", {"modo": "masivo", "filas": len(df_to_process)})
        total = len(df_to_process)
        self.set_progress(0, total)
        for idx, (_, row) in enumerate(df_to_process.iterrows(), start=1):
            desde = format_date_str(row.get("desde", "")) or format_date_str(self.desde_var.get().strip())
            hasta = format_date_str(row.get("hasta", "")) or format_date_str(self.hasta_var.get().strip())
            row_download = str(
                row.get("ubicacion_descarga")
                or row.get("path_descarga")
                or row.get("carpeta_descarga")
                or ""
            ).strip()
            cuit_repr = str(row.get("representado_cuit", "")).strip()
            self.log_separator(cuit_repr)
            payload = {
                "desde": desde,
                "hasta": hasta,
                "cuit_representante": str(row.get("cuit_representante", "")).strip(),
                "nombre_rcel": str(row.get("nombre_rcel", "")).strip(),
                "representado_cuit": cuit_repr,
                "clave": str(row.get("clave", "")),
                "b64_pdf": bool(self.b64_var.get()),
                "minio_upload": bool(self.minio_var.get()),
            }
            self.log_request(self._redact(payload))
            resp = safe_post(url, headers, payload)
            data = resp.get("data", {})
            self.log_response(resp.get("http_status"), data)

            downloads, download_errors, download_dir_used = self._process_downloads(
                data, self.MODULE_DIR, cuit_repr, override_dir=row_download
            )

            if downloads:
                self.log_info(f"Descargas completadas: {downloads} -> {download_dir_used}")
            elif isinstance(data, dict):
                 self.log_info("Sin links de PDF para descargar")

            if isinstance(data, dict):
                pdf_items = self._collect_pdf_items(data)
                if pdf_items:
                    saved_json, json_errors = self._save_pdf_jsons(pdf_items, download_dir_used)
                    if saved_json:
                        self.log_info(f"JSON guardados: {saved_json} -> {download_dir_used}")
                    for err in json_errors:
                        self.log_error(f"JSON: {err}")

            for err in download_errors:
                self.log_error(f"Descarga: {err}")

            rows.append(
                {
                    "representado_cuit": payload["representado_cuit"],
                    "http_status": resp.get("http_status"),
                    "success": data.get("success") if isinstance(data, dict) else None,
                    "message": data.get("message") if isinstance(data, dict) else None,
                    "descargas": downloads,
                    "errores_descarga": "; ".join(download_errors) if download_errors else None,
                    "carpeta_descarga": download_dir_used,
                }
            )
            self.set_progress(idx, total)
        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
