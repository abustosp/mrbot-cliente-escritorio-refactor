import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import (
    build_link,
    collect_minio_links,
    sanitize_identifier,
)
from mrbot_app.windows.mixins import DownloadHandlerMixin, ExcelHandlerMixin


class DeclaracionEnLineaWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "Declaracion_en_linea"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="DDJJ en Linea", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Declaracion en Linea (DDJJ)")
        self.add_info_label(
            container,
            "Consulta individual o masiva por periodo. Descarga automatica desde MinIO (carga_minio=True) "
            "con proxy_request=False fijo.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave representante").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Representado nombre").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Periodo desde (AAAAMM)").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Periodo hasta (AAAAMM)").grid(row=5, column=0, sticky="w", padx=4, pady=2)
        self.cuit_rep_var = tk.StringVar()
        self.clave_rep_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        self.nombre_repr_var = tk.StringVar()
        self.periodo_desde_var = tk.StringVar()
        self.periodo_hasta_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_rep_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.nombre_repr_var, width=25).grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.periodo_desde_var, width=25).grid(row=4, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.periodo_hasta_var, width=25).grid(row=5, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        # Download Path
        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("declaracion_en_linea.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualizacion DDJJ")).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=10, service="declaracion_en_linea")

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
        seen: set[tuple[str, str]] = set()
        if isinstance(data, dict):
            archivos = data.get("archivos")
            if isinstance(archivos, list):
                for idx, item in enumerate(archivos, start=1):
                    if not isinstance(item, dict):
                        continue
                    candidates = {
                        "ddjj_excel": item.get("link_minio_ddjj_excel"),
                        "dj": item.get("link_minio_dj"),
                        "vep": item.get("link_minio_vep"),
                    }
                    for label, url in candidates.items():
                        link = build_link(url, label, "ddjj", idx)
                        if link:
                            key = (link["url"], link["filename"])
                            if key not in seen:
                                seen.add(key)
                                links.append(link)
        if not links:
            links = collect_minio_links(data, "ddjj")
        return links

    def _json_filename_from_item(
        self,
        item: Dict[str, Any],
        index: int,
        header: Dict[str, Any],
        cuit_repr: str,
    ) -> str:
        for key in ("link_minio_ddjj_excel", "link_minio_dj", "link_minio_vep"):
            url = item.get(key)
            if isinstance(url, str) and url.strip():
                link = build_link(url, None, "ddjj", index)
                if link:
                    base = os.path.splitext(link["filename"][0] if isinstance(link["filename"], list) else link["filename"])[0]
                    return f"{base}.json"
        periodo = None
        datos = item.get("datos")
        if isinstance(datos, dict):
            periodo = datos.get("periodo")
            if not periodo:
                datos_base = datos.get("datos")
                if isinstance(datos_base, dict):
                    periodo = datos_base.get("Mes - Año")
        cuit = cuit_repr
        if not cuit and isinstance(header, dict):
            representado = header.get("Representado")
            if isinstance(representado, dict):
                cuit = representado.get("cuit")
        parts = ["ddjj"]
        if cuit:
            parts.append(str(cuit))
        if periodo:
            parts.append(str(periodo))
        parts.append(str(index))
        name = "_".join(sanitize_identifier(p) for p in parts if p)
        return f"{name}.json" if name else f"ddjj_{index}.json"

    def _json_fallback_name(self, header: Dict[str, Any], cuit_repr: str) -> str:
        periodo = None
        if isinstance(header, dict):
            periodo_info = header.get("Periodo")
            if isinstance(periodo_info, dict):
                periodo = periodo_info.get("periodo") or periodo_info.get("desde") or periodo_info.get("hasta")
        parts = ["ddjj"]
        if cuit_repr:
            parts.append(str(cuit_repr))
        if periodo:
            parts.append(str(periodo))
        name = "_".join(sanitize_identifier(p) for p in parts if p)
        return f"{name}.json" if name else "ddjj.json"

    def _save_json_from_data(self, data: Any, download_dir: Optional[str], cuit_repr: str) -> tuple[int, List[str]]:
        if not download_dir:
            return 0, ["No hay ruta de descarga disponible."]
        if not isinstance(data, dict) or not data:
            return 0, []
        header = data.get("header") if isinstance(data.get("header"), dict) else {}
        archivos = data.get("archivos")
        saved = 0
        errors: List[str] = []
        if isinstance(archivos, list) and archivos:
            for idx, item in enumerate(archivos, start=1):
                if not isinstance(item, dict):
                    continue
                payload = item.get("datos")
                if not isinstance(payload, dict) or not payload:
                    continue
                filename = self._json_filename_from_item(item, idx, header, cuit_repr)
                target = os.path.join(download_dir, filename)
                try:
                    with open(target, "w", encoding="utf-8") as fh:
                        json.dump(
                            {"header": header, "declaracion": payload},
                            fh,
                            ensure_ascii=False,
                            indent=2,
                        )
                    saved += 1
                except Exception as exc:
                    errors.append(f"{filename}: {exc}")
            if saved or errors:
                return saved, errors
        fallback_name = self._json_fallback_name(header, cuit_repr)
        try:
            with open(os.path.join(download_dir, fallback_name), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            saved += 1
        except Exception as exc:
            errors.append(f"{fallback_name}: {exc}")
        return saved, errors

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        cuit_repr = self._optional_value(self.cuit_repr_var.get())
        payload = {
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave_representante": self.clave_rep_var.get(),
            "cuit_representado": cuit_repr,
            "representado_nombre": self._optional_value(self.nombre_repr_var.get()),
            "periodo_desde": self.periodo_desde_var.get().strip(),
            "periodo_hasta": self.periodo_hasta_var.get().strip(),
            "carga_minio": True,
            "proxy_request": False,
        }
        url = ensure_trailing_slash(base_url) + "api/v1/declaracion-en-linea/consulta"

        self.clear_logs()
        self.log_start("Declaracion en Linea", {"modo": "individual"})

        self.run_in_thread(self._worker_individual, url, headers, payload)

    def _worker_individual(self, url, headers, payload):
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        cuit_repr = payload.get("cuit_representado")

        self.log_separator(cuit_repr or payload["cuit_representante"])
        self.log_request(safe_payload)

        resp = safe_post(url, headers, payload)
        data = resp.get("data", {})
        self.log_response(resp.get("http_status"), data)
        cuit_folder = cuit_repr or payload["cuit_representante"]

        downloads, errors, download_dir = self._process_downloads(data, self.MODULE_DIR, cuit_folder)

        if downloads:
            self.log_info(f"Descargas completadas: {downloads} -> {download_dir}")
        elif data:
            self.log_info("Sin links de descarga en la respuesta.")
        for err in errors:
            self.log_error(f"Descarga: {err}")

        json_saved, json_errors = self._save_json_from_data(data, download_dir, cuit_folder)
        if json_saved:
            self.log_info(f"JSON guardados: {json_saved} -> {download_dir}")
        for err in json_errors:
            self.log_error(f"JSON: {err}")
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
        url = ensure_trailing_slash(base_url) + "api/v1/declaracion-en-linea/consulta"

        # Copy for thread safety
        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("Declaracion en Linea", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, url, headers)

    def _worker_excel(self, df, url, headers):
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)

        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            if self._abort_event.is_set():
                break

            cuit_rep = str(row.get("cuit_representante", "")).strip()
            cuit_repr = self._optional_value(str(row.get("cuit_representado", "")))
            row_download = str(row.get("ubicacion_descarga") or row.get("path_descarga") or row.get("carpeta_descarga") or "").strip()
            self.log_separator(cuit_repr or cuit_rep)
            payload = {
                "cuit_representante": cuit_rep,
                "clave_representante": str(row.get("clave_representante", "")),
                "cuit_representado": cuit_repr,
                "representado_nombre": self._optional_value(str(row.get("representado_nombre", ""))),
                "periodo_desde": str(row.get("periodo_desde", "")).strip(),
                "periodo_hasta": str(row.get("periodo_hasta", "")).strip(),
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
            cuit_folder = cuit_repr or cuit_rep

            downloads, errors, download_dir = self._process_downloads(
                data, self.MODULE_DIR, cuit_folder, override_dir=row_download
            )

            if downloads:
                self.log_info(f"Descargas completadas: {downloads} -> {download_dir}")
            elif data:
                self.log_info("Sin links de descarga")
            for err in errors:
                self.log_error(f"Descarga: {err}")

            json_saved, json_errors = self._save_json_from_data(data, download_dir, cuit_folder)
            if json_saved:
                self.log_info(f"JSON guardados: {json_saved} -> {download_dir}")
            for err in json_errors:
                self.log_error(f"JSON: {err}")
            rows.append(
                {
                    "cuit_representado": cuit_folder,
                    "http_status": resp.get("http_status"),
                    "success": data.get("success") if isinstance(data, dict) else None,
                    "message": data.get("message") if isinstance(data, dict) else None,
                    "descargas": downloads,
                    "errores_descarga": "; ".join(errors) if errors else None,
                    "carpeta_descarga": download_dir,
                }
            )
            self.set_progress(idx, total)

        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
