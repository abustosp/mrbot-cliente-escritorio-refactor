import concurrent.futures
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse, unquote

from mrbot_app.config import get_max_workers
from mrbot_app.ret_per_provinciales import consulta_misiones, FALLBACK_BASE_DIR
from mrbot_app.helpers import (
    build_headers,
    df_preview,
    ensure_trailing_slash,
    safe_get,
    parse_bool_cell,
    get_unique_filename,
)
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import (
    ExcelHandlerMixin,
    DownloadHandlerMixin,
)


class RetPerMisionesWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "ret_per_misiones"

    def __init__(self, master=None, config_provider=None, example_paths=None):
        super().__init__(master, title="Descarga Ret-Per Misiones", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Retenciones/Percepciones IIBB Misiones")
        self.add_info_label(
            container,
            "Descarga de retenciones y percepciones de DGR Misiones. "
            "Consulta individual o masiva via Excel.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT Representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT Representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Denominacion").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Desde (AAAAMM)").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Hasta (AAAAMM)").grid(row=5, column=0, sticky="w", padx=4, pady=2)

        self.cuit_rep_var = tk.StringVar()
        self.clave_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        self.denominacion_var = tk.StringVar()
        self.desde_var = tk.StringVar()
        self.hasta_var = tk.StringVar()

        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.denominacion_var, width=25).grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.desde_var, width=15).grid(row=4, column=1, padx=4, pady=2, sticky="w")
        ttk.Entry(inputs, textvariable=self.hasta_var, width=15).grid(row=5, column=1, padx=4, pady=2, sticky="w")

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=4)
        self.carga_minio_var = tk.BooleanVar(value=True)
        self.proxy_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Carga MinIO", variable=self.carga_minio_var).grid(
            row=0, column=0, padx=4, pady=2, sticky="w"
        )
        ttk.Checkbutton(opts, text="proxy_request", variable=self.proxy_var).grid(
            row=0, column=1, padx=4, pady=2, sticky="w"
        )

        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Consulta Individual", command=self.consulta_individual).grid(
            row=0, column=0, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(
            row=0, column=1, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Ver ejemplo", command=lambda: self.abrir_ejemplo_key("ret_per_provinciales_misiones.xlsx")).grid(
            row=0, column=2, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Previsualizar Excel", command=self.previsualizar_excel).grid(
            row=1, column=0, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(
            row=1, column=1, padx=4, pady=2, sticky="ew"
        )
        btns.columnconfigure((0, 1, 2), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.set_preview(
            self.preview, "Selecciona un Excel y presiona 'Previsualizar Excel' para ver los datos."
        )
        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=16, service="ret_per_misiones")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _get_success_and_error(self, data: Dict[str, Any]) -> tuple[bool, str]:
        detail = data.get("detail")
        if isinstance(detail, dict):
            success = detail.get("success", data.get("success", False))
            messages = detail.get("message", [])
            if isinstance(messages, list):
                error_text = "; ".join(str(m) for m in messages if m)
            else:
                error_text = str(messages) if messages else ""
            return success, error_text
        success = data.get("success", False)
        error_text = str(
            data.get("error") or data.get("message") or data.get("detail") or ""
        )
        if isinstance(error_text, list):
            error_text = "; ".join(str(e) for e in error_text) if error_text else ""
        return success, error_text

    def _extract_archivos(self, data: Dict[str, Any]) -> List[Dict[str, str]]:
        archivos = data.get("archivos", [])
        if not isinstance(archivos, list):
            return []
        result = []
        for item in archivos:
            if isinstance(item, dict) and item.get("url_minio"):
                result.append({
                    "tipo": item.get("tipo", "archivo"),
                    "archivo": item.get("archivo", "archivo"),
                    "url": item["url_minio"],
                })
        return result

    def _build_payload_from_ui(self) -> Dict[str, Any]:
        return {
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave_representante": self.clave_var.get(),
            "cuit_representado": self.cuit_repr_var.get().strip() or self.cuit_rep_var.get().strip(),
            "denominacion": self.denominacion_var.get().strip(),
            "desde": self.desde_var.get().strip(),
            "hasta": self.hasta_var.get().strip(),
            "carga_minio": bool(self.carga_minio_var.get()),
            "proxy_request": bool(self.proxy_var.get()),
        }

    def _process_single_response(self, response: Dict[str, Any], download_root: str) -> tuple[int, List[str]]:
        downloads_total = 0
        errors = []
        success, error_text = self._get_success_and_error(response)
        if not success:
            msg = error_text or "Error desconocido"
            self.log_error(f"Error en API: {msg}")
            return 0, [msg]

        archivos = self._extract_archivos(response)
        for item in archivos:
            url = item["url"]
            self.log_info(f"{item['tipo']} URL: {url[:50]}...")
            os.makedirs(download_root, exist_ok=True)
            link_obj = {"url": url, "filename": item["archivo"]}
            downloads, errs = self._download_links_direct([link_obj], download_root)
            downloads_total += downloads
            if downloads:
                self.log_info(f"{item['tipo']} descargado en: {download_root}")
            errors.extend(errs)
        return downloads_total, errors

    def _process_response_excel(self, response: Dict[str, Any], ubicacion: str, fallback_root: str) -> tuple[int, List[str]]:
        downloads_total = 0
        errors = []
        success, error_text = self._get_success_and_error(response)
        if not success:
            msg = error_text or "Error desconocido"
            self.log_error(f"Error en API: {msg}")
            return 0, [msg]

        archivos = self._extract_archivos(response)
        target_dir = ubicacion if ubicacion else fallback_root
        for item in archivos:
            url = item["url"]
            self.log_info(f"{item['tipo']} URL: {url[:50]}...")
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as e:
                errors.append(f"Error creando directorio {target_dir}: {e}")
                continue
            final_filename = get_unique_filename(target_dir, item["archivo"])
            link_obj = {"url": url, "filename": final_filename}
            downloads, errs = self._download_links_direct([link_obj], target_dir)
            downloads_total += downloads
            if errs:
                errors.extend(errs)
            if downloads:
                self.log_info(f"{item['tipo']} descargado en: {os.path.join(target_dir, final_filename)}")
        return downloads_total, errors

    def _download_links_direct(self, links: List[Dict[str, str]], dest_dir: str) -> tuple[int, List[str]]:
        from mrbot_app.windows.minio_helpers import download_links
        return download_links(links, dest_dir)

    def consulta_individual(self) -> None:
        payload = self._build_payload_from_ui()
        if not payload["cuit_representante"] or not payload["clave_representante"]:
            messagebox.showerror("Error", "Faltan CUIT Representante y/o Clave.")
            return
        self.clear_logs()
        self.log_start("Ret-Per Misiones", {"modo": "individual"})
        self.run_in_thread(
            self.run_with_log_block,
            payload["cuit_representado"] or payload["cuit_representante"] or "sin_cuit",
            self._worker_individual,
            payload,
        )

    def _worker_individual(self, payload: Dict[str, Any]) -> None:
        cuit = payload["cuit_representado"]
        self.log_separator(f"{payload['denominacion']} ({cuit})")
        target_dir = self.download_dir_var.get().strip()
        final_dir = target_dir if target_dir else os.path.join(FALLBACK_BASE_DIR, "misiones", cuit)
        try:
            os.makedirs(final_dir, exist_ok=True)
        except Exception:
            final_dir = "Descargas"
        self.log_info(f"Directorio descarga: {final_dir}")
        response = consulta_misiones(
            cuit_representante=payload["cuit_representante"],
            clave_representante=payload["clave_representante"],
            cuit_representado=cuit,
            denominacion=payload["denominacion"],
            desde=payload["desde"], hasta=payload["hasta"],
            carga_minio=payload["carga_minio"], proxy_request=payload["proxy_request"],
            log_fn=self.log_message,
        )
        self._process_single_response(response, final_dir)
        self.log_info("Proceso individual finalizado.")

    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            messagebox.showerror("Error", "Carga un Excel primero.")
            return
        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            messagebox.showwarning("Sin filas", "No hay filas con procesar=SI")
            return
        default_proxy = bool(self.proxy_var.get())
        df_copy = df_to_process.copy()
        self.clear_logs()
        self.log_start("Ret-Per Misiones", {"modo": "masivo", "filas": len(df_copy)})
        self.run_in_thread(self._worker_excel, df_copy, default_proxy)

    def _worker_excel(self, df: pd.DataFrame, default_proxy: bool) -> None:
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.run_with_log_block,
                    str(row.get("cuit_representado", "sin_cuit")).strip(),
                    self._process_row,
                    row, default_proxy,
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
                except Exception as exc:
                    self.log_error(f"Error en fila {completed}: {exc}")
                self.set_progress(completed, total)
        self.set_preview(self.preview, df_preview(pd.DataFrame(rows), rows=min(20, len(rows))))
        self.set_execution_summary(self.build_download_execution_summary("Ret-Per Misiones", rows, total_expected=total))
        self.log_info("Procesamiento masivo finalizado.")

    def _process_row(self, row, default_proxy: bool) -> Optional[Dict[str, Any]]:
        if self._abort_event.is_set():
            return None
        cuit_rep = str(row.get("cuit_representante", "")).strip()
        clave = str(row.get("clave_representante", "") or row.get("clave", "")).strip()
        cuit_repr = str(row.get("cuit_representado", "")).strip() or cuit_rep
        denominacion = str(row.get("denominacion", "")).strip()
        desde = str(row.get("desde", "")).strip()
        hasta = str(row.get("hasta", "")).strip()
        ubicacion = str(row.get("ubicacion_descarga", "")).strip()
        proxy_request = parse_bool_cell(row.get("proxy_request"), default=default_proxy) if "proxy_request" in row.index else default_proxy
        try:
            retry_val = int(row.get("retry", 0))
        except (ValueError, TypeError):
            retry_val = 0
        total_attempts = retry_val if retry_val > 1 else 1

        self.log_separator(f"{denominacion} ({cuit_repr})")
        fallback_dir = ubicacion if ubicacion else os.path.join(FALLBACK_BASE_DIR, "misiones", cuit_rep)
        try:
            os.makedirs(fallback_dir, exist_ok=True)
        except Exception:
            pass
        self.log_info(f"Periodo: {desde} - {hasta}")

        response = {}
        for attempt in range(1, total_attempts + 1):
            if attempt > 1:
                self.log_info(f"Reintentando... (Intento {attempt}/{total_attempts})")
            response = consulta_misiones(
                cuit_representante=cuit_rep, clave_representante=clave,
                cuit_representado=cuit_repr, denominacion=denominacion,
                desde=desde, hasta=hasta,
                carga_minio=True, proxy_request=proxy_request, log_fn=self.log_message,
            )
            if response.get("success", False) or response.get("detail", {}).get("success", False):
                break
        downloads, errors = self._process_response_excel(response, ubicacion, fallback_dir)
        success, error_text = self._get_success_and_error(response)
        return {
            "cuit_representado": cuit_repr or cuit_rep,
            "success": success,
            "message": error_text or None,
            "descarga_esperada": True,
            "descargas": downloads,
            "errores_descarga": "; ".join(errors) if errors else None,
        }
