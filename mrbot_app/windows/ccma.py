import concurrent.futures
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.config import get_max_workers
from mrbot_app.formatos import aplicar_formato_encabezado, agregar_filtros, autoajustar_columnas
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, parse_bool_cell, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import build_link
from mrbot_app.windows.mixins import DownloadHandlerMixin, ExcelHandlerMixin


def _parse_amount(value: Any) -> Optional[float]:
    """
    Convierte strings con separador de miles y decimal a float.
    Admite formatos tipo 22,307.22 (coma miles, punto decimal) y 22.307,22.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if text == "":
        return None
    try:
        if "," in text and "." in text:
            if text.rfind(".") > text.rfind(","):
                text = text.replace(",", "")
            else:
                text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(".", "").replace(",", ".")
        return float(text)
    except Exception:
        return None


class CcmaWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "CCMA"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Cuenta Corriente (CCMA)", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Cuenta Corriente de Monotributistas y Autonomos (CCMA)")
        self.add_info_label(container, "Consulta individual o masiva basada en Excel. PDF opcional con descarga desde MinIO.")

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

        self.opt_proxy = tk.BooleanVar(value=False)
        self.opt_movimientos = tk.BooleanVar(value=True)
        self.opt_pdf = tk.BooleanVar(value=False)
        flags = ttk.Frame(container)
        flags.pack(anchor="w", pady=2)
        ttk.Checkbutton(flags, text="proxy_request", variable=self.opt_proxy).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(flags, text="movimientos", variable=self.opt_movimientos).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(flags, text="pdf", variable=self.opt_pdf).pack(side="left")

        # Download Path
        self.add_download_path_frame(container)

        # Filtro de periodo para recálculo
        recalculo_frame = ttk.LabelFrame(container, text="Recalculo de reporte (filtro por periodo)")
        recalculo_frame.pack(fill="x", pady=4)
        rc_inner = ttk.Frame(recalculo_frame)
        rc_inner.pack(fill="x", padx=4, pady=4)
        ttk.Label(rc_inner, text="Desde (MM/AAAA)").grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Label(rc_inner, text="Hasta (MM/AAAA)").grid(row=0, column=2, padx=4, pady=2, sticky="w")
        self.periodo_desde_var = tk.StringVar()
        self.periodo_hasta_var = tk.StringVar()
        ttk.Entry(rc_inner, textvariable=self.periodo_desde_var, width=12).grid(row=0, column=1, padx=4, pady=2)
        ttk.Entry(rc_inner, textvariable=self.periodo_hasta_var, width=12).grid(row=0, column=3, padx=4, pady=2)
        ttk.Button(rc_inner, text="Recalcular Reporte", command=self._recalcular_reporte).grid(
            row=0, column=4, padx=8, pady=2
        )

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("ccma.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualización CCMA")).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=12, service="ccma")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _sanitize_filename_part(self, value: str, fallback: str = "desconocido") -> str:
        cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", (value or "").strip())
        cleaned = cleaned.strip("_")
        return cleaned or fallback

    def _parse_optional_bool(self, value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            try:
                if pd.isna(value):
                    return None
            except Exception:
                pass
            return bool(value)
        text = str(value).strip()
        if not text:
            return None
        lowered = text.lower()
        if lowered in {"true", "1", "si", "sí", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        return None

    def _resolve_cuit_label(self, cuit_repr: str, cuit_rep: str, data: Any) -> str:
        if cuit_repr:
            return cuit_repr
        if isinstance(data, dict):
            response_ccma = data.get("response_ccma")
            if isinstance(response_ccma, dict):
                cuit_data = str(response_ccma.get("cuit", "")).strip()
                if cuit_data:
                    return cuit_data
        return cuit_rep

    def _save_ccma_response_json(self, dest_dir: Optional[str], cuit_label: str, data: Any) -> Tuple[Optional[str], Optional[str]]:
        if not dest_dir:
            return None, "No hay carpeta de descarga disponible."
        try:
            os.makedirs(dest_dir, exist_ok=True)
            safe_cuit = self._sanitize_filename_part(cuit_label)
            timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            filename = f"{safe_cuit}_{timestamp}.json"
            path = os.path.join(dest_dir, filename)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
            return path, None
        except Exception as exc:
            return None, str(exc)

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        if not isinstance(data, dict):
            return []
        response_obj = data.get("response_ccma", data)
        if not isinstance(response_obj, dict):
            return []
        url = response_obj.get("pdf_url_minio")
        if isinstance(url, str) and url.strip().lower().startswith("http"):
            link = build_link(url, None, "ccma", 1)
            return [link] if link else []
        return []

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        payload = {
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave_representante": self.clave_rep_var.get(),
            "cuit_representado": self.cuit_repr_var.get().strip(),
            "proxy_request": bool(self.opt_proxy.get()),
            "movimientos": bool(self.opt_movimientos.get()),
        }
        pdf_requested = bool(self.opt_pdf.get())
        if pdf_requested:
            payload["pdf"] = True
        url = ensure_trailing_slash(base_url) + "api/v1/ccma/consulta"
        self.clear_logs()

        self.run_in_thread(
            self.run_with_log_block,
            payload["cuit_representado"] or payload["cuit_representante"] or "sin_cuit",
            self._worker_individual,
            url,
            headers,
            payload,
            pdf_requested,
        )

    def _worker_individual(self, url, headers, payload, pdf_requested):
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        cuit_label = payload["cuit_representado"] or payload["cuit_representante"]
        self.log_start("CCMA", {"modo": "individual"})
        self.log_separator(cuit_label)
        self.log_request_started(safe_payload)
        resp = safe_post(url, headers, payload)
        data = resp.get("data")
        self.log_response_finished(resp.get("http_status"), data)
        if resp.get("http_status") != 200:
            detail = resp.get("error") or resp.get("detail") or data
            self.log_error(f"HTTP {resp.get('http_status')}: {detail}")

        cuit_label = self._resolve_cuit_label(payload["cuit_representado"], payload["cuit_representante"], data)

        # Download logic
        downloads, errors, download_dir = self._process_downloads(data, self.MODULE_DIR, cuit_label)

        json_path, json_error = self._save_ccma_response_json(download_dir, cuit_label, data)
        if json_path:
            self.log_info(f"JSON guardado: {json_path}")
        if json_error:
            self.log_error(f"JSON: {json_error}")

        if downloads:
            self.log_info(f"PDF descargado: {downloads} -> {download_dir}")
        elif pdf_requested:
             self.log_info("PDF: no se encontro link en la respuesta.")
        elif not download_dir and pdf_requested: # This condition might be redundant but safe
             self.log_error("PDF: no hay carpeta de descarga disponible.")

        for err in errors:
            self.log_error(f"PDF: {err}")

        self.set_preview(self.result_box, json.dumps(resp, indent=2, ensure_ascii=False))

    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/ccma/consulta"

        # Capture options
        movimientos_default = bool(self.opt_movimientos.get())
        pdf_default = bool(self.opt_pdf.get())
        proxy_default = bool(self.opt_proxy.get())

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        # Copy for thread safety
        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("CCMA", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, url, headers, movimientos_default, pdf_default, proxy_default)

    def _worker_excel(self, df, url, headers, movimientos_default, pdf_default, proxy_default):
        rows: List[Dict[str, Any]] = []
        movimientos_rows: List[Dict[str, Any]] = []
        movimientos_requested = False

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
                    self._process_row_ccma,
                    row,
                    url,
                    headers,
                    movimientos_default,
                    pdf_default,
                    proxy_default,
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
                    if not result:
                        self.set_progress(completed, total)
                        continue
                    result_row, result_movs, req_movs = result
                    if result_row:
                        rows.append(result_row)
                    if result_movs:
                        movimientos_rows.extend(result_movs)
                    if req_movs:
                        movimientos_requested = True
                except Exception as exc:
                    self.log_error(f"Error en fila {idx}: {exc}")
                self.set_progress(completed, total)

        # Post processing involves creating DataFrame and saving Excel, which is safe in thread as it doesn't touch UI directly except via log_error
        self._post_process_excel(rows, movimientos_rows, movimientos_requested)
        self.set_execution_summary(self.build_download_execution_summary("CCMA", rows, total_expected=total))
        self.log_info("Procesamiento masivo finalizado.")

    def _process_row_ccma(self, row, url, headers, movimientos_default, pdf_default, proxy_default):
        if self._abort_event.is_set():
            return None, [], False

        cuit_rep = str(row.get("cuit_representante", "")).strip()
        cuit_repr = str(row.get("cuit_representado", "")).strip()
        movimientos_flag = parse_bool_cell(row.get("movimientos"), default=movimientos_default)
        proxy_request = None
        if "proxy_request" in row.index:
            proxy_request = parse_bool_cell(row.get("proxy_request"), default=proxy_default)

        # Special case for pdf flag from excel which could be None to use default
        pdf_flag = self._parse_optional_bool(row.get("pdf"))
        if pdf_flag is None:
            pdf_flag = pdf_default

        payload = {
            "cuit_representante": cuit_rep,
            "clave_representante": str(row.get("clave_representante", "")),
            "cuit_representado": cuit_repr,
            "movimientos": movimientos_flag,
        }
        if proxy_request is not None:
            payload["proxy_request"] = proxy_request
        if pdf_flag:
            payload["pdf"] = True

        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        self.log_separator(cuit_repr or cuit_rep)

        try:
            retry_val = int(row.get("retry", 0))
        except (ValueError, TypeError):
            retry_val = 0
        total_attempts = retry_val if retry_val > 1 else 1

        resp = {}
        data = {}
        http_status = None

        for attempt in range(1, total_attempts + 1):
            self.log_request_started(safe_payload, attempt=attempt, total_attempts=total_attempts)

            resp = safe_post(url, headers, payload)
            http_status = resp.get("http_status")
            data = resp.get("data")
            self.log_response_finished(http_status, data)
            if http_status == 200:
                break

        if http_status != 200:
            detail = resp.get("error") or resp.get("detail") or data
            self.log_error(f"HTTP {http_status}: {detail}")

        cuit_label = self._resolve_cuit_label(cuit_repr, cuit_rep, data)
        row_download = str(
            row.get("ubicacion_descarga")
            or row.get("path_descarga")
            or row.get("carpeta_descarga")
            or ""
        ).strip()

        downloads, errors, download_dir = self._process_downloads(
            data, self.MODULE_DIR, cuit_label, override_dir=row_download
        )

        json_path, json_error = self._save_ccma_response_json(download_dir, cuit_label, data)
        if json_path:
            self.log_info(f"JSON guardado: {json_path}")
        if json_error:
            self.log_error(f"JSON: {json_error}")

        if downloads:
            self.log_info(f"PDF descargado: {downloads} -> {download_dir}")
        elif pdf_flag:
            self.log_info("PDF: no se encontro link en la respuesta.")

        for err in errors:
            self.log_error(f"PDF: {err}")

        row_result = {}
        movs_result = []

        if http_status == 200 and isinstance(data, dict):
            # Extraer clave "response_ccma" si existe, para replicar ejemplo
            response_obj = data.get("response_ccma", data)
            if isinstance(response_obj, dict):
                row_result = {
                    "cuit_representante": cuit_rep,
                    "cuit_representado": cuit_repr,
                    "cuit": response_obj.get("cuit"),
                    "periodo": response_obj.get("periodo"),
                    "deuda_capital": _parse_amount(response_obj.get("deuda_capital")),
                    "deuda_accesorios": _parse_amount(response_obj.get("deuda_accesorios")),
                    "total_deuda": _parse_amount(response_obj.get("total_deuda")),
                    "credito_capital": _parse_amount(response_obj.get("credito_capital")),
                    "credito_accesorios": _parse_amount(response_obj.get("credito_accesorios")),
                    "total_a_favor": _parse_amount(response_obj.get("total_a_favor")),
                    "pdf_url_minio": response_obj.get("pdf_url_minio"),
                    "response_json": json.dumps({"response_ccma": response_obj}, ensure_ascii=False),
                    "movimientos_solicitados": movimientos_flag,
                    "pdf_solicitado": pdf_flag,
                    "descarga_esperada": pdf_flag,
                    "descargas": downloads,
                    "errores_descarga": "; ".join(errors) if errors else None,
                    "errores_postproceso": json_error,
                    "success": True,
                    "error": None,
                }
                movimientos_list = response_obj.get("movimientos")
                if movimientos_flag and isinstance(movimientos_list, list):
                    for mov in movimientos_list:
                        if not isinstance(mov, dict):
                            continue
                        movs_result.append(
                            {
                                "cuit_representante": cuit_rep,
                                "cuit_representado": cuit_repr or response_obj.get("cuit"),
                                **mov,
                            }
                        )
            else:
                row_result = {
                    "cuit_representante": cuit_rep,
                    "cuit_representado": cuit_repr,
                    "movimientos_solicitados": movimientos_flag,
                    "pdf_url_minio": None,
                    "response_json": json.dumps(data, ensure_ascii=False),
                    "pdf_solicitado": pdf_flag,
                    "descarga_esperada": pdf_flag,
                    "descargas": downloads,
                    "errores_descarga": "; ".join(errors) if errors else None,
                    "errores_postproceso": json_error,
                    "success": True,
                    "error": None,
                }
        else:
            row_result = {
                "cuit_representante": cuit_rep,
                "cuit_representado": cuit_repr,
                "movimientos_solicitados": movimientos_flag,
                "pdf_url_minio": None,
                "response_json": None,
                "pdf_solicitado": pdf_flag,
                "descarga_esperada": pdf_flag,
                "descargas": downloads,
                "errores_descarga": "; ".join(errors) if errors else None,
                "errores_postproceso": json_error,
                "success": False,
                "error": json.dumps(resp, ensure_ascii=False),
            }

        return row_result, movs_result, movimientos_flag

    def _post_process_excel(self, rows, movimientos_rows, movimientos_requested):
        out_df = pd.DataFrame(rows)
        movimientos_df = pd.DataFrame(movimientos_rows)
        numeric_fields_ccma = [
            "deuda_capital",
            "deuda_accesorios",
            "total_deuda",
            "credito_capital",
            "credito_accesorios",
            "total_a_favor",
        ]
        for col in numeric_fields_ccma:
            if col in out_df.columns:
                out_df[col] = out_df[col].apply(_parse_amount)
        columnas_movimientos = [
            "cuit_representante",
            "cuit_representado",
            "periodo",
            "impuesto",
            "concepto",
            "subconcepto",
            "descripcion",
            "fecha_movimiento",
            "debe",
            "haber",
        ]
        if movimientos_df.empty and movimientos_requested:
            movimientos_df = pd.DataFrame(columns=columnas_movimientos)
        if not movimientos_df.empty:
            mov_cols = [c for c in columnas_movimientos if c in movimientos_df.columns]
            otros_cols = [c for c in movimientos_df.columns if c not in mov_cols]
            movimientos_df = movimientos_df[mov_cols + otros_cols]
            for monto_col in ("debe", "haber"):
                if monto_col in movimientos_df.columns:
                    movimientos_df[monto_col] = movimientos_df[monto_col].apply(_parse_amount)
        # Guardar consolidado en ./descargas/ReporteCCMA.xlsx
        out_path = os.path.join("descargas/CCMA/", "ReporteCCMA.xlsx")
        try:
            os.makedirs("descargas/CCMA", exist_ok=True)
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                out_df.to_excel(writer, index=False, sheet_name="CCMA")
                hojas_creadas = ["CCMA"]
                if movimientos_requested or not movimientos_df.empty:
                    movimientos_df.to_excel(writer, index=False, sheet_name="Movimientos")
                    hojas_creadas.append("Movimientos")
                for hoja_nombre in hojas_creadas:
                    hoja = writer.sheets.get(hoja_nombre)
                    if hoja is None:
                        continue
                    aplicar_formato_encabezado(hoja)
                    agregar_filtros(hoja)
                    if hoja_nombre == "Movimientos":
                        autoajustar_columnas(hoja)
        except Exception as exc:
            self.log_error(f"Error guardando ReporteCCMA.xlsx: {exc}")
            return
        self.log_info(f"Reporte generado: {out_path}")

        # Only preview update should be scheduled to main thread
        preview_text = df_preview(out_df, rows=min(20, len(out_df)))
        if not movimientos_requested and movimientos_df.empty:
            preview_text += "\n\nMovimientos: no se solicitaron."
        elif movimientos_df.empty:
            preview_text += "\n\nMovimientos: hoja sin filas (sin movimientos devueltos)."
        else:
            preview_text += f"\n\nMovimientos exportados: {len(movimientos_df)} filas en hoja 'Movimientos'."
        self.set_preview(self.result_box, preview_text)

    # ── Recalculo de reporte con filtro de periodo ──────────────────────────

    @staticmethod
    def _periodo_sort(p: str) -> int:
        """Convierte MM/YYYY a YYYYMM para orden cronologico."""
        try:
            mm, yyyy = str(p).strip().split("/")
            return int(yyyy + mm)
        except (ValueError, AttributeError):
            return 0

    @staticmethod
    def _sort_to_periodo(s: int) -> str:
        s_str = str(int(s))
        return f"{s_str[4:6]}/{s_str[0:4]}"

    def _recalcular_reporte(self):
        """Valida entradas y lanza el recalculo en segundo plano."""
        desde = self.periodo_desde_var.get().strip()
        hasta = self.periodo_hasta_var.get().strip()

        if not desde and not hasta:
            messagebox.showwarning("Sin periodo", "Indica al menos Desde o Hasta (MM/AAAA).")
            return

        if desde:
            if not re.match(r"^\d{2}/\d{4}$", desde):
                messagebox.showerror("Formato invalido", "Desde debe tener formato MM/AAAA (ej: 01/2025).")
                return
        if hasta:
            if not re.match(r"^\d{2}/\d{4}$", hasta):
                messagebox.showerror("Formato invalido", "Hasta debe tener formato MM/AAAA (ej: 06/2026).")
                return

        self.run_in_thread(self._recalcular_worker, desde=desde or None, hasta=hasta or None)

    def _recalcular_worker(self, desde=None, hasta=None):
        self.log_info("Iniciando recálculo de reporte CCMA ...")

        out_path = os.path.join("descargas", "CCMA", "ReporteCCMA.xlsx")
        if not os.path.exists(out_path):
            self.log_error(f"No se encontró {out_path}. Procesa el Excel primero.")
            self.set_preview(self.result_box, "Error: no existe ReporteCCMA.xlsx. Ejecuta 'Procesar Excel' antes.")
            return

        try:
            ccma = pd.read_excel(out_path, sheet_name="CCMA")
            movs = pd.read_excel(out_path, sheet_name="Movimientos")
        except Exception as exc:
            self.log_error(f"Error leyendo {out_path}: {exc}")
            return

        self.log_info(f"CCMA: {len(ccma)} filas | Movimientos: {len(movs)} filas")

        # convertir a sortable y filtrar
        movs["_psort"] = movs["periodo"].apply(self._periodo_sort)
        p_min_sort = self._periodo_sort(desde) if desde else 0
        p_max_sort = self._periodo_sort(hasta) if hasta else 999999

        if p_min_sort > 0:
            movs = movs[movs["_psort"] >= p_min_sort]
        if p_max_sort < 999999:
            movs = movs[movs["_psort"] <= p_max_sort]

        self.log_info(f"Movimientos filtrados: {len(movs)} filas")

        movs["cuit_int"] = movs["cuit_representado"].fillna(0).astype("int64")

        def classify_sub(sub):
            if pd.isna(sub):
                return None
            s = int(sub)
            if s in (19, 86):
                return "capital"
            return "accesorios"

        movs["categoria"] = movs["subconcepto"].apply(classify_sub)
        movs["debe_n"] = movs["debe"].fillna(0)
        movs["haber_n"] = movs["haber"].fillna(0)

        agg = movs.groupby(["cuit_int", "categoria"], dropna=False).agg(
            total_debe=("debe_n", "sum"),
            total_haber=("haber_n", "sum"),
            p_min_sort=("_psort", "min"),
            p_max_sort=("_psort", "max"),
        ).reset_index()

        agg["neto"] = agg["total_debe"] - agg["total_haber"]
        agg["deuda"] = agg["neto"].clip(lower=0).round(2)
        agg["credito"] = (-agg["neto"]).clip(lower=0).round(2)

        recs = {}
        for _, row in agg.iterrows():
            cuit = int(row["cuit_int"])
            cat = row["categoria"]
            if cat is None:
                continue
            if cuit not in recs:
                recs[cuit] = {
                    "cuit_representado": cuit,
                    "deuda_capital": 0.0, "deuda_accesorios": 0.0,
                    "credito_capital": 0.0, "credito_accesorios": 0.0,
                    "p_min_sort": 999999, "p_max_sort": 0,
                }
            r = recs[cuit]
            r[f"deuda_{cat}"] = float(row["deuda"])
            r[f"credito_{cat}"] = float(row["credito"])
            if row["p_min_sort"] > 0 and row["p_min_sort"] < r["p_min_sort"]:
                r["p_min_sort"] = int(row["p_min_sort"])
            if row["p_max_sort"] > 0 and row["p_max_sort"] > r["p_max_sort"]:
                r["p_max_sort"] = int(row["p_max_sort"])

        for cuit, r in recs.items():
            r["total_deuda"] = round(r["deuda_capital"] + r["deuda_accesorios"], 2)
            r["total_a_favor"] = round(r["credito_capital"] + r["credito_accesorios"], 2)
            if r["p_min_sort"] < 999999 and r["p_max_sort"] > 0:
                p_min = self._sort_to_periodo(r["p_min_sort"])
                p_max = self._sort_to_periodo(r["p_max_sort"])
                r["periodo"] = p_min if p_min == p_max else f"{p_min} - {p_max}"
            else:
                r["periodo"] = None

        recalc_df = pd.DataFrame(list(recs.values()))
        self.log_info(f"CUITS recalculados: {len(recalc_df)}")

        # actualizar CCMA
        ccma_upd = ccma.copy()
        ccma_upd["cuit_int"] = ccma_upd["cuit_representado"].fillna(0).astype("int64")
        debt_fields = [
            "deuda_capital", "deuda_accesorios", "total_deuda",
            "credito_capital", "credito_accesorios", "total_a_favor",
        ]
        for f in debt_fields:
            if f in ccma_upd.columns:
                ccma_upd[f] = None
        updated = 0
        for idx, row in ccma_upd.iterrows():
            cuit = int(row["cuit_int"]) if row["cuit_int"] != 0 else 0
            m = recalc_df[recalc_df["cuit_representado"] == cuit]
            if len(m) == 1:
                mr = m.iloc[0]
                for f in debt_fields:
                    ccma_upd.at[idx, f] = mr.get(f, 0.0)
                if mr.get("periodo"):
                    ccma_upd.at[idx, "periodo"] = mr["periodo"]
                updated += 1

        self.log_info(f"CCMA actualizadas: {updated}/{len(ccma_upd)}")

        resumen_cols = [
            "cuit_representante", "cuit_representado", "periodo",
            "deuda_capital", "deuda_accesorios", "total_deuda",
            "credito_capital", "credito_accesorios", "total_a_favor",
        ]
        resumen = ccma_upd[resumen_cols].copy()
        resumen = resumen.sort_values("cuit_representado", na_position="last").reset_index(drop=True)

        # guardar
        base, ext = os.path.splitext(out_path)
        output = f"{base}-filtrado{ext}"

        movs_out = movs.drop(columns=["_psort", "cuit_int", "categoria", "debe_n", "haber_n"])
        ccma_out = ccma_upd.drop(columns=["cuit_int"])

        try:
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                ccma_out.to_excel(writer, index=False, sheet_name="CCMA")
                movs_out.to_excel(writer, index=False, sheet_name="Movimientos")
                resumen.to_excel(writer, index=False, sheet_name="Resumen")
                for hoja_nombre in ("CCMA", "Movimientos", "Resumen"):
                    hoja = writer.sheets.get(hoja_nombre)
                    if hoja is None:
                        continue
                    aplicar_formato_encabezado(hoja)
                    agregar_filtros(hoja)
                    if hoja_nombre == "Movimientos":
                        autoajustar_columnas(hoja)
        except Exception as exc:
            self.log_error(f"Error guardando {output}: {exc}")
            return

        self.log_info(f"Reporte filtrado guardado: {output}")

        d = resumen["total_deuda"].fillna(0) > 0
        f = resumen["total_a_favor"].fillna(0) > 0
        sn = resumen["periodo"].isna()

        preview_text = f"Recalculo CCMA — periodo: {desde or '--'} a {hasta or '--'}\n"
        preview_text += f"Reporte guardado: {output}\n"
        preview_text += f"CCMA: {len(ccma_out)} | Movimientos: {len(movs_out)} | Resumen: {len(resumen)}\n"
        preview_text += f"Con deuda: {d.sum()} | A favor: {f.sum()} | Sin movimientos: {sn.sum()}"
        self.set_preview(self.result_box, preview_text)
