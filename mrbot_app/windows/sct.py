import concurrent.futures
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.config import get_max_workers
from mrbot_app.consulta import descargar_archivo_minio
from mrbot_app.helpers import (
    build_headers,
    df_preview,
    ensure_trailing_slash,
    get_unique_filename,
    parse_bool_cell,
    safe_post,
)
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import prepare_download_dir
from mrbot_app.windows.mixins import ExcelHandlerMixin


class SctWindow(BaseWindow, ExcelHandlerMixin):
    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Sistema de Cuentas Tributarias (SCT)", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Sistema de Cuentas Tributarias (SCT)")
        self.add_info_label(container, "Consulta individual o masiva. Formatos disponibles: Excel/CSV/PDF en base64 o subida a MinIO.")

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT login").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.sct_login_var = tk.StringVar()
        self.sct_clave_var = tk.StringVar()
        self.sct_repr_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.sct_login_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.sct_clave_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.sct_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=2)
        self.opt_excel_minio = tk.BooleanVar(value=True)
        self.opt_excel_b64 = tk.BooleanVar(value=False)
        self.opt_csv_minio = tk.BooleanVar(value=False)
        self.opt_csv_b64 = tk.BooleanVar(value=False)
        self.opt_pdf_minio = tk.BooleanVar(value=False)
        self.opt_pdf_b64 = tk.BooleanVar(value=False)
        self.opt_proxy = tk.BooleanVar(value=False)
        self.opt_deuda = tk.BooleanVar(value=True)
        self.opt_vencimientos = tk.BooleanVar(value=True)
        self.opt_presentacion = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Excel MinIO", variable=self.opt_excel_minio).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Excel base64", variable=self.opt_excel_b64, state="disabled").grid(row=0, column=1, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="CSV MinIO", variable=self.opt_csv_minio).grid(row=1, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="CSV base64", variable=self.opt_csv_b64, state="disabled").grid(row=1, column=1, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="PDF MinIO", variable=self.opt_pdf_minio).grid(row=2, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="PDF base64", variable=self.opt_pdf_b64, state="disabled").grid(row=2, column=1, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="proxy_request", variable=self.opt_proxy).grid(row=3, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Incluir deuda", variable=self.opt_deuda).grid(row=4, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Incluir vencimientos", variable=self.opt_vencimientos).grid(row=4, column=1, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Incluir presentacion DDJJ", variable=self.opt_presentacion).grid(row=5, column=0, padx=4, pady=2, sticky="w")

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("sct.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=self.previsualizar_excel).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=12, service="sct")

    def clear_logs(self) -> None:
        if not hasattr(self, "log_text") or self.log_text is None:
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _format_log_line(self, text: str, prefix: str, style: Optional[str]) -> str:
        body = f"{prefix}{text}".rstrip("\n")
        main_sep = "=" * 64
        sub_sep = "-" * 64

        if style == "header":
            return f"\n{main_sep}\n{body}\n{main_sep}\n"
        if style == "section":
            return f"\n{sub_sep}\n{body}\n"
        if style == "bullet":
            return f"  - {body}\n"
        if style == "success":
            return f"  [OK] {body}\n"
        if style == "error":
            return f"  [ERROR] {body}\n{sub_sep}\n"
        if style == "raw":
            return body
        return body + ("\n" if not body.endswith("\n") else "")

    def append_log(self, text: str, prefix: str = "", style: Optional[str] = None) -> None:
        if not text:
            return
        formatted = self._format_log_line(text, prefix, style)
        self.log_message(formatted)

    def _redact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        safe = dict(payload)
        if "clave" in safe:
            safe["clave"] = "***"
        return safe

    def _ensure_extension(self, name: str, ext: str) -> str:
        clean = (name or "").strip()
        if not clean:
            clean = "reporte"
        if not clean.lower().endswith(f".{ext}"):
            clean = f"{clean}.{ext}"
        return clean

    def _sanitize_identifier(self, value: str, fallback: str = "desconocido") -> str:
        cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", (value or "").strip())
        cleaned = cleaned.strip("_")
        return cleaned or fallback

    def _download_variant(
        self,
        data: Dict[str, Any],
        outputs: Dict[str, bool],
        prefix: str,
        fmt: str,
        dest_dir: str,
        base_name: str,
        cuit_repr: str,
    ) -> Tuple[bool, Optional[str]]:
        ext_map = {"excel": "xls", "csv": "csv", "pdf": "pdf"}
        ext = ext_map[fmt]
        minio_flag = outputs.get(f"{prefix}_{fmt}_minio")
        if not minio_flag:
            return False, None

        minio_keys = [f"{prefix}_{fmt}_minio_url", f"{prefix}_{fmt}_url_minio"]
        url = None
        for key in minio_keys:
            candidate = data.get(key)
            if isinstance(candidate, str):
                candidate = candidate.strip()
            if candidate:
                url = candidate
                break
        if not url:
            return False, f"Link inexistente o vacío ({' / '.join(minio_keys)})"

        # Logic for filename fallback
        if not base_name or not base_name.strip():
             # Fallback to name from URL
             base_from_url = unquote(os.path.basename(urlparse(url).path))
             if not base_from_url:
                 base_from_url = f"{prefix}_{fmt}"
             filename = self._ensure_extension(base_from_url, ext)
        else:
             filename = self._ensure_extension(base_name, ext)

        target_dir = dest_dir or ""

        final_dir, dir_msgs = prepare_download_dir("SCT", target_dir, cuit_repr)

        if not final_dir:
             return False, "; ".join(dir_msgs)

        # Collision handling
        filename_unique = get_unique_filename(final_dir, filename)
        target_path = os.path.join(final_dir, filename_unique)

        res = descargar_archivo_minio(url, target_path)
        if res.get("success"):
            return True, None

        return False, res.get("error") or f"Error al descargar en {target_path}"

    def _process_downloads_per_block(
        self,
        data: Dict[str, Any],
        outputs: Dict[str, bool],
        block_config: Dict[str, Dict[str, str]],
        cuit_repr: str,
        cuit_login: str,
    ) -> Tuple[int, List[str]]:
        total_downloaded = 0
        errors: List[str] = []
        for prefix, cfg in block_config.items():
            if not cfg.get("enabled"):
                continue
            dest_dir = cfg.get("path", "")
            for fmt in ("excel", "csv", "pdf"):
                success, err = self._download_variant(data, outputs, prefix, fmt, dest_dir, cfg.get("name", prefix), cuit_repr)
                if success:
                    total_downloaded += 1
                elif err:
                    errors.append(f"{prefix}-{fmt}: {err}")
        return total_downloaded, errors

    def _row_format_flags(self, row: Optional[pd.Series] = None, prefer_row: bool = False,
                          default_excel: bool = False, default_csv: bool = False, default_pdf: bool = False) -> Tuple[bool, bool, bool]:
        """
        Calculates output flags based on row data or defaults.
        Pass defaults as arguments to ensure thread safety when running in worker.
        """
        excel_enabled = default_excel
        csv_enabled = default_csv
        pdf_enabled = default_pdf

        if row is not None:
            def pick(key: str, current: bool) -> bool:
                if key in row:
                    value = row.get(key)
                    if value is None or str(value).strip() == "":
                        return current if not prefer_row else False
                    return parse_bool_cell(value, default=current if not prefer_row else False)
                return current if not prefer_row else current

            excel_enabled = pick("excel", excel_enabled)
            csv_enabled = pick("csv", csv_enabled)
            pdf_enabled = pick("pdf", pdf_enabled)

        return excel_enabled, csv_enabled, pdf_enabled

    def build_output_flags(
        self,
        include_deuda: bool,
        include_vencimientos: bool,
        include_ddjj: bool,
        excel_enabled: bool,
        csv_enabled: bool,
        pdf_enabled: bool,
    ) -> Tuple[Dict[str, bool], bool]:
        outputs: Dict[str, bool] = {
            "vencimientos_excel_minio": False,
            "vencimientos_csv_minio": False,
            "vencimientos_pdf_minio": False,
            "deudas_excel_minio": False,
            "deudas_csv_minio": False,
            "deudas_pdf_minio": False,
            "ddjj_pendientes_excel_minio": False,
            "ddjj_pendientes_csv_minio": False,
            "ddjj_pendientes_pdf_minio": False,
        }

        selected = False

        def apply(prefix: str, enabled: bool) -> None:
            nonlocal selected
            if not enabled:
                return
            if excel_enabled:
                outputs[f"{prefix}_excel_minio"] = True
                selected = True
            if csv_enabled:
                outputs[f"{prefix}_csv_minio"] = True
                selected = True
            if pdf_enabled:
                outputs[f"{prefix}_pdf_minio"] = True
                selected = True

        apply("deudas", include_deuda)
        apply("vencimientos", include_vencimientos)
        apply("ddjj_pendientes", include_ddjj)

        return outputs, selected

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)

        # Capture current UI state
        include_deuda = bool(self.opt_deuda.get())
        include_vencimientos = bool(self.opt_vencimientos.get())
        include_ddjj = bool(self.opt_presentacion.get())

        # Defaults for individual query are based on checkboxes
        def_excel = bool(self.opt_excel_minio.get())
        def_csv = bool(self.opt_csv_minio.get())
        def_pdf = bool(self.opt_pdf_minio.get())

        excel_fmt, csv_fmt, pdf_fmt = self._row_format_flags(None, default_excel=def_excel, default_csv=def_csv, default_pdf=def_pdf)

        outputs, has_outputs = self.build_output_flags(include_deuda, include_vencimientos, include_ddjj, excel_fmt, csv_fmt, pdf_fmt)
        if not has_outputs:
            messagebox.showwarning(
                "Falta salida",
                "Selecciona un formato de salida (Excel/CSV/PDF) y habilita al menos un bloque (Deuda/Vencimientos/DDJJ).",
            )
            return
        payload = {
            "cuit_login": self.sct_login_var.get().strip(),
            "clave": self.sct_clave_var.get(),
            "cuit_representado": self.sct_repr_var.get().strip(),
            "proxy_request": bool(self.opt_proxy.get()),
        }
        payload.update(outputs)
        url = ensure_trailing_slash(base_url) + "api/v1/sct/consulta"
        self.clear_logs()

        self.run_in_thread(
            self.run_with_log_block,
            payload["cuit_representado"] or payload["cuit_login"] or "sin_cuit",
            self._worker_individual,
            url,
            headers,
            payload,
        )

    def _worker_individual(self, url, headers, payload):
        self.log_start("SCT", {"modo": "individual"})
        self.log_separator(payload["cuit_representado"])
        self.log_request_started(self._redact(payload))
        resp = safe_post(url, headers, payload)
        self.log_response_finished(resp.get("http_status"), resp.get("data"))
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
        url = ensure_trailing_slash(base_url) + "api/v1/sct/consulta"

        # Capture defaults for Excel processing
        defaults = {
            "deuda": bool(self.opt_deuda.get()),
            "vencimientos": bool(self.opt_vencimientos.get()),
            "presentacion": bool(self.opt_presentacion.get()),
            "proxy": bool(self.opt_proxy.get()),
            "excel": bool(self.opt_excel_minio.get()),
            "csv": bool(self.opt_csv_minio.get()),
            "pdf": bool(self.opt_pdf_minio.get()),
        }

        # Copy for thread safety
        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("SCT", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, url, headers, defaults)

    def _worker_excel(self, df, url, headers, defaults):
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.run_with_log_block,
                    str(row.get("cuit_representado", "")).strip()
                    or str(row.get("cuit_login", "")).strip()
                    or "sin_cuit",
                    self._process_row_sct,
                    row,
                    url,
                    headers,
                    defaults,
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

    def _process_row_sct(self, row, url, headers, defaults):
        if self._abort_event.is_set():
            return None

        include_deuda = parse_bool_cell(row.get("deuda"), default=defaults["deuda"]) if "deuda" in row else defaults["deuda"]
        include_venc = (
            parse_bool_cell(row.get("vencimientos"), default=defaults["vencimientos"]) if "vencimientos" in row else defaults["vencimientos"]
        )
        include_ddjj = (
            parse_bool_cell(row.get("presentacion_ddjj"), default=defaults["presentacion"])
            if "presentacion_ddjj" in row
            else defaults["presentacion"]
        )

        # Pass defaults to helper to avoid UI access
        excel_fmt, csv_fmt, pdf_fmt = self._row_format_flags(
            row, prefer_row=True,
            default_excel=defaults["excel"],
            default_csv=defaults["csv"],
            default_pdf=defaults["pdf"]
        )

        outputs, has_outputs = self.build_output_flags(include_deuda, include_venc, include_ddjj, excel_fmt, csv_fmt, pdf_fmt)
        if not has_outputs:
            self.log_separator(str(row.get("cuit_representado", "")).strip())
            self.log_error("Sin formato de salida seleccionado para esta fila")
            return {
                "cuit_representado": str(row.get("cuit_representado", "")).strip(),
                "http_status": None,
                "status": "sin_salida",
                "error_message": "Sin formato de salida seleccionado para esta fila",
            }

        block_config = {
            "deudas": {
                "enabled": include_deuda,
                "path": str(row.get("ubicacion_deuda") or row.get("ubicacion_deudas") or ""),
                "name": str(row.get("nombre_deuda") or row.get("nombre_deudas") or ""),
            },
            "vencimientos": {
                "enabled": include_venc,
                "path": str(row.get("ubicacion_vencimientos") or ""),
                "name": str(row.get("nombre_vencimientos") or ""),
            },
            "ddjj_pendientes": {
                "enabled": include_ddjj,
                "path": str(row.get("ubicacion_ddjj") or row.get("ubicacion_presentacion_ddjj") or ""),
                "name": str(row.get("nombre_ddjj") or row.get("nombre_presentacion_ddjj") or ""),
            },
        }
        proxy_request = None
        if "proxy_request" in row.index:
            proxy_request = parse_bool_cell(row.get("proxy_request"), default=defaults["proxy"])
        payload = {
            "cuit_login": str(row.get("cuit_login", "")).strip(),
            "clave": str(row.get("clave", "")),
            "cuit_representado": str(row.get("cuit_representado", "")).strip(),
        }
        if proxy_request is not None:
            payload["proxy_request"] = proxy_request
        payload.update(outputs)
        self.log_separator(payload["cuit_representado"])
        self.log_info(f"Bloques activos -> deuda={include_deuda}, vencimientos={include_venc}, ddjj={include_ddjj}")
        self.log_info(f"Salidas solicitadas -> {json.dumps(outputs, ensure_ascii=False)}")
        safe_payload = self._redact(payload)

        try:
            retry_val = int(row.get("retry", 0))
        except (ValueError, TypeError):
            retry_val = 0
        total_attempts = retry_val if retry_val > 1 else 1

        resp = {}
        data = {}
        for attempt in range(1, total_attempts + 1):
            self.log_request_started(safe_payload, attempt=attempt, total_attempts=total_attempts)

            resp = safe_post(url, headers, payload)
            data = resp.get("data", {})
            self.log_response_finished(resp.get("http_status"), data)
            if resp.get("http_status") == 200:
                break

        downloads = 0
        download_errors: List[str] = []
        if isinstance(data, dict):
            downloads, download_errors = self._process_downloads_per_block(
                data, outputs, block_config, payload["cuit_representado"], payload["cuit_login"]
            )
        if downloads:
            self.log_info(f"Descargas completadas: {downloads}")
        for err in download_errors:
            self.log_error(f"Descarga: {err}")

        return {
            "cuit_representado": payload["cuit_representado"],
            "http_status": resp.get("http_status"),
            "status": data.get("status") if isinstance(data, dict) else None,
            "error_message": data.get("error_message") if isinstance(data, dict) else None,
            "descargas": downloads,
            "errores_descarga": "; ".join(download_errors) if download_errors else None,
        }
