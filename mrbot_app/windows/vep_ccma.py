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


MEDIOS_PAGO = ["internet_banking", "link", "pago_mis_cuentas", "xn_group", "qr"]
FILTROS_SLOTS = 5


def _parse_amount(value: Any) -> Optional[float]:
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


class VepCcmaWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "VEP_CCMA"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="VEP desde CCMA", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        self.filtro_vars_impuestos: List[Dict[str, tk.StringVar]] = []
        self.filtro_vars_intereses: List[Dict[str, tk.StringVar]] = []

        self.resizable(True, True)
        self.geometry("1200x700")
        self.minsize(1000, 600)

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        left_col = ttk.Frame(container)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        right_col = ttk.Frame(container)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        self.add_section_label(left_col, "VEP desde Cuenta Corriente de Monotributistas (CCMA)")
        self.add_info_label(
            left_col,
            "Genera VEP a partir de la CCMA del contribuyente. "
            "Los filtros son incluyentes (whitelist): sin filtro se selecciona todo, "
            "con filtro solo las filas que coinciden (OR entre lineas, AND dentro de cada linea)."
        )

        inputs = ttk.Frame(left_col)
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

        medio_frame = ttk.Frame(left_col)
        medio_frame.pack(fill="x", pady=2)
        ttk.Label(medio_frame, text="Medio de pago").pack(side="left", padx=4)
        self.medio_pago_var = tk.StringVar(value="internet_banking")
        self.medio_pago_cb = ttk.Combobox(
            medio_frame, textvariable=self.medio_pago_var, values=MEDIOS_PAGO, state="readonly", width=22
        )
        self.medio_pago_cb.pack(side="left", padx=4)

        flags = ttk.Frame(left_col)
        flags.pack(anchor="w", pady=2)
        self.opt_sel_impuestos = tk.BooleanVar(value=True)
        self.opt_sel_intereses = tk.BooleanVar(value=True)
        self.opt_generar_volante = tk.BooleanVar(value=True)
        self.opt_minio_upload = tk.BooleanVar(value=True)
        self.opt_proxy = tk.BooleanVar(value=False)
        ttk.Checkbutton(flags, text="seleccionar impuestos", variable=self.opt_sel_impuestos).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(flags, text="seleccionar intereses", variable=self.opt_sel_intereses).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(flags, text="generar volante", variable=self.opt_generar_volante).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(flags, text="minio upload", variable=self.opt_minio_upload).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(flags, text="proxy_request", variable=self.opt_proxy).pack(side="left")

        self._build_filtros_frame(left_col, "impuestos", fields=["periodo", "impuesto", "concepto", "subconcepto", "categoria"])
        self._build_filtros_frame(left_col, "intereses", fields=["periodo", "impuesto", "concepto", "subconcepto"])

        self.add_download_path_frame(left_col)

        btns = ttk.Frame(left_col)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("vep_ccma.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.previsualizar_excel("Previsualizacion VEP-CCMA")).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(right_col, height=8, show=False)
        self.result_box = self.add_preview(right_col, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(right_col, label="Progreso")

        self.log_text = self.add_collapsible_log(right_col, title="Logs de ejecucion", height=15, service="vep_ccma")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _build_filtros_frame(self, parent, tipo: str, fields: list) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=f"Filtros de {tipo}")
        frame.pack(fill="x", pady=4)
        inner = ttk.Frame(frame)
        inner.pack(fill="x", padx=4, pady=4)

        for col_idx, field in enumerate(fields):
            ttk.Label(inner, text=field.capitalize()).grid(row=0, column=col_idx, padx=2, pady=2, sticky="w")

        if tipo == "impuestos":
            target_list = self.filtro_vars_impuestos
        else:
            target_list = self.filtro_vars_intereses

        for slot in range(1, FILTROS_SLOTS + 1):
            row_vars: Dict[str, tk.StringVar] = {}
            for col_idx, field in enumerate(fields):
                var = tk.StringVar()
                ttk.Entry(inner, textvariable=var, width=12).grid(row=slot, column=col_idx, padx=2, pady=1, sticky="ew")
                row_vars[field] = var
            target_list.append(row_vars)

        for col_idx in range(len(fields)):
            inner.columnconfigure(col_idx, weight=1)

        return frame

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
        if lowered in {"true", "1", "si", "si", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        return None

    def _collect_filtros_from_ui(self, vars_list: List[Dict[str, tk.StringVar]]) -> Optional[List[Dict[str, str]]]:
        filtros: List[Dict[str, str]] = []
        for row_vars in vars_list:
            entry: Dict[str, str] = {}
            for field, var in row_vars.items():
                val = var.get().strip()
                if val:
                    entry[field] = val
            if entry:
                filtros.append(entry)
        return filtros if filtros else None

    def _collect_filtros_from_row(self, row, tipo: str) -> Optional[List[Dict[str, str]]]:
        campos_base = ["periodo", "impuesto", "concepto", "subconcepto"]
        if tipo == "impuestos":
            campos_base = campos_base + ["categoria"]
        filtros: List[Dict[str, str]] = []
        for n in range(1, FILTROS_SLOTS + 1):
            entry: Dict[str, str] = {}
            for campo in campos_base:
                col = f"filtro_{tipo}_{campo}_{n}"
                val = str(row.get(col, "")).strip()
                if val:
                    entry[campo] = val
            if entry:
                filtros.append(entry)
        return filtros if filtros else None

    def _build_payload(self, cuit_rep, clave_rep, cuit_repr, medio_pago,
                       sel_impuestos, sel_intereses, generar_volante,
                       minio_upload, proxy_request,
                       filtro_impuestos, filtro_intereses):
        payload: Dict[str, Any] = {
            "cuit_representante": cuit_rep,
            "clave_representante": clave_rep,
            "cuit_representado": cuit_repr,
            "medio_pago": medio_pago,
            "seleccionar_impuestos": sel_impuestos,
            "seleccionar_intereses": sel_intereses,
            "generar_volante": generar_volante,
        }
        if minio_upload is not None:
            payload["minio_upload"] = minio_upload
        if proxy_request:
            payload["proxy_request"] = proxy_request
        if filtro_impuestos is not None:
            payload["filtro_impuestos"] = filtro_impuestos
        if filtro_intereses is not None:
            payload["filtro_intereses"] = filtro_intereses
        return payload

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        if not isinstance(data, dict):
            return []
        links: List[Dict[str, str]] = []
        url_minio = data.get("url_minio")
        if isinstance(url_minio, str) and url_minio.strip().lower().startswith("http"):
            link = build_link(url_minio, None, "vep_ccma", 1)
            if link:
                links.append(link)
        url_minio_qr = data.get("url_minio_qr")
        if isinstance(url_minio_qr, str) and url_minio_qr.strip().lower().startswith("http"):
            link = build_link(url_minio_qr, None, "vep_ccma_qr", 2)
            if link:
                links.append(link)
        return links

    def _save_response_json(self, dest_dir: Optional[str], cuit_label: str, data: Any) -> Tuple[Optional[str], Optional[str]]:
        if not dest_dir:
            return None, "No hay carpeta de descarga disponible."
        try:
            os.makedirs(dest_dir, exist_ok=True)
            safe_cuit = self._sanitize_filename_part(cuit_label)
            timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            filename = f"vep_{safe_cuit}_{timestamp}.json"
            path = os.path.join(dest_dir, filename)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
            return path, None
        except Exception as exc:
            return None, str(exc)

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)

        filtro_impuestos = self._collect_filtros_from_ui(self.filtro_vars_impuestos)
        filtro_intereses = self._collect_filtros_from_ui(self.filtro_vars_intereses)

        payload = self._build_payload(
            cuit_rep=self.cuit_rep_var.get().strip(),
            clave_rep=self.clave_rep_var.get(),
            cuit_repr=self.cuit_repr_var.get().strip(),
            medio_pago=self.medio_pago_var.get(),
            sel_impuestos=bool(self.opt_sel_impuestos.get()),
            sel_intereses=bool(self.opt_sel_intereses.get()),
            generar_volante=bool(self.opt_generar_volante.get()),
            minio_upload=bool(self.opt_minio_upload.get()),
            proxy_request=bool(self.opt_proxy.get()),
            filtro_impuestos=filtro_impuestos,
            filtro_intereses=filtro_intereses,
        )

        url = ensure_trailing_slash(base_url) + "api/v1/vep-ccma/generar"
        self.clear_logs()

        self.run_in_thread(
            self.run_with_log_block,
            payload["cuit_representado"] or payload["cuit_representante"] or "sin_cuit",
            self._worker_individual,
            url,
            headers,
            payload,
        )

    def _worker_individual(self, url, headers, payload):
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        cuit_label = payload["cuit_representado"] or payload["cuit_representante"]
        self.log_start("VEP-CCMA", {"modo": "individual"})
        self.log_separator(cuit_label)
        self.log_request_started(safe_payload)
        resp = safe_post(url, headers, payload)
        data = resp.get("data")
        http_status = resp.get("http_status")
        self.log_response_finished(http_status, data)

        if http_status != 200:
            detail = resp.get("error") or resp.get("detail") or data
            self.log_error(f"HTTP {http_status}: {detail}")

        downloads, errors, download_dir = self._process_downloads(data, self.MODULE_DIR, cuit_label)

        json_path, json_error = self._save_response_json(download_dir, cuit_label, data)
        if json_path:
            self.log_info(f"JSON guardado: {json_path}")
        if json_error:
            self.log_error(f"JSON: {json_error}")

        if downloads:
            self.log_info(f"Archivos descargados: {downloads} -> {download_dir}")
        if http_status == 200 and isinstance(data, dict):
            if data.get("url_minio") and not downloads:
                self.log_info("PDF: link presente pero sin descarga (no se configuro carpeta).")
            if not data.get("url_minio"):
                self.log_info("PDF: no se encontro link en la respuesta.")

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
        url = ensure_trailing_slash(base_url) + "api/v1/vep-ccma/generar"

        medio_pago_default = self.medio_pago_var.get()
        sel_imp_default = bool(self.opt_sel_impuestos.get())
        sel_int_default = bool(self.opt_sel_intereses.get())
        gen_vol_default = bool(self.opt_generar_volante.get())
        minio_default = bool(self.opt_minio_upload.get())
        proxy_default = bool(self.opt_proxy.get())

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("VEP-CCMA", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(
            self._worker_excel, df_copy, url, headers,
            medio_pago_default, sel_imp_default, sel_int_default,
            gen_vol_default, minio_default, proxy_default,
        )

    def _worker_excel(self, df, url, headers, medio_pago_default,
                      sel_imp_default, sel_int_default, gen_vol_default,
                      minio_default, proxy_default):
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
                    self._process_row_vep_ccma,
                    row,
                    url,
                    headers,
                    medio_pago_default,
                    sel_imp_default,
                    sel_int_default,
                    gen_vol_default,
                    minio_default,
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
                    if result:
                        rows.append(result)
                except Exception as exc:
                    self.log_error(f"Error en fila {idx}: {exc}")
                self.set_progress(completed, total)

        self._post_process_excel(rows)
        self.set_execution_summary(self.build_download_execution_summary("VEP-CCMA", rows, total_expected=total))
        self.log_info("Procesamiento masivo finalizado.")

    def _process_row_vep_ccma(self, row, url, headers, medio_pago_default,
                               sel_imp_default, sel_int_default, gen_vol_default,
                               minio_default, proxy_default):
        if self._abort_event.is_set():
            return None

        cuit_rep = str(row.get("cuit_representante", "")).strip()
        cuit_repr = str(row.get("cuit_representado", "")).strip()
        medio_pago = str(row.get("medio_pago", "")).strip() or medio_pago_default

        sel_imp = parse_bool_cell(row.get("seleccionar_impuestos"), default=sel_imp_default)
        sel_int = parse_bool_cell(row.get("seleccionar_intereses"), default=sel_int_default)
        gen_vol = parse_bool_cell(row.get("generar_volante"), default=gen_vol_default)

        minio_flag = self._parse_optional_bool(row.get("minio_upload"))
        if minio_flag is None:
            minio_flag = minio_default

        proxy_flag = None
        if "proxy_request" in row.index:
            proxy_flag = parse_bool_cell(row.get("proxy_request"), default=proxy_default)

        filtro_impuestos = self._collect_filtros_from_row(row, "impuestos")
        filtro_intereses = self._collect_filtros_from_row(row, "intereses")

        payload = self._build_payload(
            cuit_rep=cuit_rep,
            clave_rep=str(row.get("clave_representante", "")),
            cuit_repr=cuit_repr,
            medio_pago=medio_pago,
            sel_impuestos=sel_imp,
            sel_intereses=sel_int,
            generar_volante=gen_vol,
            minio_upload=minio_flag,
            proxy_request=proxy_flag,
            filtro_impuestos=filtro_impuestos,
            filtro_intereses=filtro_intereses,
        )

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

        cuit_label = cuit_repr or cuit_rep
        row_download = str(
            row.get("ubicacion_descarga")
            or row.get("path_descarga")
            or row.get("carpeta_descarga")
            or ""
        ).strip()

        downloads, errors, download_dir = self._process_downloads(
            data, self.MODULE_DIR, cuit_label, override_dir=row_download
        )

        json_path, json_error = self._save_response_json(download_dir, cuit_label, data)
        if json_path:
            self.log_info(f"JSON guardado: {json_path}")
        if json_error:
            self.log_error(f"JSON: {json_error}")

        if downloads:
            self.log_info(f"Archivos descargados: {downloads} -> {download_dir}")
        elif isinstance(data, dict) and data.get("url_minio"):
            self.log_info("PDF: link presente pero sin descarga (no se configuro carpeta).")

        for err in errors:
            self.log_error(f"Descarga: {err}")

        row_result = {
            "cuit_representante": cuit_rep,
            "cuit_representado": cuit_repr,
            "medio_pago": medio_pago,
            "success": False,
            "error": None,
            "total_impuestos": None,
            "total_intereses": None,
            "total_seleccionado": None,
            "url_minio": None,
            "url_minio_qr": None,
            "nombre_archivo": None,
            "volante_json": None,
            "descargas": downloads,
            "errores_descarga": "; ".join(errors) if errors else None,
            "errores_postproceso": json_error,
        }

        if http_status == 200 and isinstance(data, dict):
            row_result.update({
                "success": data.get("success", True),
                "message": data.get("message", ""),
                "total_impuestos": data.get("total_impuestos"),
                "total_intereses": data.get("total_intereses"),
                "total_seleccionado": data.get("total_seleccionado"),
                "url_minio": data.get("url_minio"),
                "url_minio_qr": data.get("url_minio_qr"),
                "nombre_archivo": data.get("nombre_archivo"),
                "volante_json": json.dumps(data, ensure_ascii=False),
            })
        else:
            row_result.update({
                "success": False,
                "error": json.dumps(resp, ensure_ascii=False),
            })

        return row_result

    def _post_process_excel(self, rows):
        out_df = pd.DataFrame(rows)
        out_path = os.path.join("descargas", "VEP_CCMA", "ReporteVEP_CCMA.xlsx")
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                out_df.to_excel(writer, index=False, sheet_name="VEP_CCMA")
                hoja = writer.sheets["VEP_CCMA"]
                aplicar_formato_encabezado(hoja)
                agregar_filtros(hoja)
                autoajustar_columnas(hoja)
        except Exception as exc:
            self.log_error(f"Error guardando ReporteVEP_CCMA.xlsx: {exc}")
            return

        self.log_info(f"Reporte generado: {out_path}")
        preview_text = df_preview(out_df, rows=min(20, len(out_df)))
        self.set_preview(self.result_box, preview_text)
