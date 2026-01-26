import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mrbot_app.files import open_with_default_app
from mrbot_app.formatos import aplicar_formato_encabezado, agregar_filtros, autoajustar_columnas
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, parse_bool_cell, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import build_link, download_links, prepare_download_dir


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


class CcmaWindow(BaseWindow):
    MODULE_DIR = "CCMA"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Cuenta Corriente (CCMA)")
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.config_provider = config_provider
        self.example_paths = example_paths or {}
        self.ccma_df: Optional[pd.DataFrame] = None

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

        path_frame = ttk.Frame(container)
        path_frame.pack(fill="x", pady=2)
        ttk.Label(path_frame, text="Carpeta descargas (opcional)").grid(row=0, column=0, padx=4, pady=2, sticky="w")
        self.download_dir_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.download_dir_var, width=45).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(path_frame, text="Elegir carpeta", command=self.seleccionar_carpeta_descarga).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        path_frame.columnconfigure(1, weight=1)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=self.abrir_ejemplo).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.open_df_preview((self.ccma_df[self.ccma_df["procesar"].str.lower().isin(["si", "sí", "yes", "y", "1"])]) if (self.ccma_df is not None and "procesar" in self.ccma_df.columns) else self.ccma_df, "Previsualización CCMA")).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=12, service="ccma")

    def seleccionar_carpeta_descarga(self) -> None:
        folder = filedialog.askdirectory()
        self.bring_to_front()
        if folder:
            self.download_dir_var.set(folder)

    def abrir_ejemplo(self) -> None:
        path = self.example_paths.get("ccma.xlsx")
        if not path:
            messagebox.showerror("Error", "No se encontro el Excel de ejemplo.")
            return
        if not open_with_default_app(path):
            messagebox.showerror("Error", "No se pudo abrir el Excel de ejemplo.")

    def cargar_excel(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not filename:
            return
        try:
            self.ccma_df = pd.read_excel(filename, dtype=str).fillna("")
            self.ccma_df.columns = [c.strip().lower() for c in self.ccma_df.columns]
            df_prev = self.ccma_df
            if "procesar" in df_prev.columns:
                df_prev = df_prev[df_prev["procesar"].str.lower().isin(["si", "sí", "yes", "y", "1"])]
            self.set_preview(self.preview, df_preview(df_prev))
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo leer el Excel: {exc}")

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

    def _extract_pdf_link(self, data: Any) -> Optional[Dict[str, str]]:
        if not isinstance(data, dict):
            return None
        response_obj = data.get("response_ccma", data)
        if not isinstance(response_obj, dict):
            return None
        url = response_obj.get("pdf_url_minio")
        if isinstance(url, str) and url.strip().lower().startswith("http"):
            return build_link(url, None, "ccma", 1)
        return None

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def consulta_individual(self) -> None:
        base_url, api_key, email = self.config_provider()
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
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        cuit_label = payload["cuit_representado"] or payload["cuit_representante"]
        self.log_start("CCMA", {"modo": "individual"})
        self.log_separator(cuit_label)
        self.log_request(safe_payload)
        resp = safe_post(url, headers, payload)
        data = resp.get("data")
        self.log_response(resp.get("http_status"), data)
        if resp.get("http_status") != 200:
            detail = resp.get("error") or resp.get("detail") or data
            self.log_error(f"HTTP {resp.get('http_status')}: {detail}")
        cuit_label = self._resolve_cuit_label(payload["cuit_representado"], payload["cuit_representante"], data)
        download_dir, dir_msgs = prepare_download_dir(self.MODULE_DIR, self.download_dir_var.get(), cuit_label)
        for msg in dir_msgs:
            self.log_info(msg)
        json_path, json_error = self._save_ccma_response_json(download_dir, cuit_label, data)
        if json_path:
            self.log_info(f"JSON guardado: {json_path}")
        if json_error:
            self.log_error(f"JSON: {json_error}")
        pdf_link = self._extract_pdf_link(data)
        if pdf_link and download_dir:
            downloads, errors = download_links([pdf_link], download_dir)
            if downloads:
                self.log_info(f"PDF descargado: {downloads} -> {download_dir}")
            for err in errors:
                self.log_error(f"PDF: {err}")
        elif pdf_link and not download_dir:
            self.log_error("PDF: no hay carpeta de descarga disponible.")
        elif pdf_requested:
            self.log_info("PDF: no se encontro link en la respuesta.")
        self.set_preview(self.result_box, json.dumps(resp, indent=2, ensure_ascii=False))

    def procesar_excel(self) -> None:
        if self.ccma_df is None or self.ccma_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return
        base_url, api_key, email = self.config_provider()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/ccma/consulta"
        rows: List[Dict[str, Any]] = []
        movimientos_rows: List[Dict[str, Any]] = []
        movimientos_requested = False
        movimientos_default = bool(self.opt_movimientos.get())
        pdf_default: Optional[bool] = True if self.opt_pdf.get() else None
        df_to_process = self.ccma_df
        if "procesar" in df_to_process.columns:
            df_to_process = df_to_process[df_to_process["procesar"].str.lower().isin(["si", "sí", "yes", "y", "1"])]
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        self.clear_logs()
        self.log_start("CCMA", {"modo": "masivo", "filas": len(df_to_process)})
        total = len(df_to_process)
        self.set_progress(0, total)
        for idx, (_, row) in enumerate(df_to_process.iterrows(), start=1):
            cuit_rep = str(row.get("cuit_representante", "")).strip()
            cuit_repr = str(row.get("cuit_representado", "")).strip()
            movimientos_flag = parse_bool_cell(row.get("movimientos"), default=movimientos_default)
            movimientos_requested = movimientos_requested or movimientos_flag
            pdf_flag = self._parse_optional_bool(row.get("pdf"))
            if pdf_flag is None:
                pdf_flag = pdf_default
            payload = {
                "cuit_representante": cuit_rep,
                "clave_representante": str(row.get("clave_representante", "")),
                "cuit_representado": cuit_repr,
                "proxy_request": bool(self.opt_proxy.get()),
                "movimientos": movimientos_flag
            }
            if pdf_flag is not None:
                payload["pdf"] = pdf_flag
            safe_payload = dict(payload)
            safe_payload["clave_representante"] = "***"
            self.log_separator(cuit_repr or cuit_rep)
            self.log_request(safe_payload)
            resp = safe_post(url, headers, payload)
            http_status = resp.get("http_status")
            data = resp.get("data")
            self.log_response(http_status, data)
            if http_status != 200:
                detail = resp.get("error") or resp.get("detail") or data
                self.log_error(f"HTTP {http_status}: {detail}")
            cuit_label = self._resolve_cuit_label(cuit_repr, cuit_rep, data)
            row_download = str(row.get("ubicacion_descarga") or row.get("path_descarga") or row.get("carpeta_descarga") or "").strip()
            download_dir, dir_msgs = prepare_download_dir(self.MODULE_DIR, row_download or self.download_dir_var.get(), cuit_label)
            for msg in dir_msgs:
                self.log_info(msg)
            json_path, json_error = self._save_ccma_response_json(download_dir, cuit_label, data)
            if json_path:
                self.log_info(f"JSON guardado: {json_path}")
            if json_error:
                self.log_error(f"JSON: {json_error}")
            pdf_link = self._extract_pdf_link(data)
            if pdf_link and download_dir:
                downloads, errors = download_links([pdf_link], download_dir)
                if downloads:
                    self.log_info(f"PDF descargado: {downloads} -> {download_dir}")
                for err in errors:
                    self.log_error(f"PDF: {err}")
            elif pdf_link and not download_dir:
                self.log_error("PDF: no hay carpeta de descarga disponible.")
            elif pdf_flag:
                self.log_info("PDF: no se encontro link en la respuesta.")
            if http_status == 200 and isinstance(data, dict):
                # Extraer clave "response_ccma" si existe, para replicar ejemplo
                response_obj = data.get("response_ccma", data)
                if isinstance(response_obj, dict):
                    rows.append({
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
                        "error": None
                    })
                    movimientos_list = response_obj.get("movimientos")
                    if movimientos_flag and isinstance(movimientos_list, list):
                        for mov in movimientos_list:
                            if not isinstance(mov, dict):
                                continue
                            movimientos_rows.append({
                                "cuit_representante": cuit_rep,
                                "cuit_representado": cuit_repr or response_obj.get("cuit"),
                                **mov
                            })
                else:
                    rows.append({
                        "cuit_representante": cuit_rep,
                        "cuit_representado": cuit_repr,
                        "movimientos_solicitados": movimientos_flag,
                        "pdf_url_minio": None,
                        "response_json": json.dumps(data, ensure_ascii=False),
                        "pdf_solicitado": pdf_flag,
                        "error": None
                    })
            else:
                rows.append({
                    "cuit_representante": cuit_rep,
                    "cuit_representado": cuit_repr,
                    "movimientos_solicitados": movimientos_flag,
                    "pdf_url_minio": None,
                    "response_json": None,
                    "pdf_solicitado": pdf_flag,
                    "error": json.dumps(resp, ensure_ascii=False)
                })
            self.set_progress(idx, total)
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
            messagebox.showerror("Error", f"No se pudo guardar ReporteCCMA.xlsx: {exc}")
            return
        self.log_info(f"Reporte generado: {out_path}")
        preview_text = df_preview(out_df, rows=min(20, len(out_df)))
        if not movimientos_requested and movimientos_df.empty:
            preview_text += "\n\nMovimientos: no se solicitaron."
        elif movimientos_df.empty:
            preview_text += "\n\nMovimientos: hoja sin filas (sin movimientos devueltos)."
        else:
            preview_text += f"\n\nMovimientos exportados: {len(movimientos_df)} filas en hoja 'Movimientos'."
        self.set_preview(self.result_box, preview_text)
