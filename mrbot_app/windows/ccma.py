import json
from typing import Any, Dict, List, Optional
import os

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mrbot_app.files import open_with_default_app
from mrbot_app.formatos import aplicar_formato_encabezado, agregar_filtros, autoajustar_columnas
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, parse_bool_cell, safe_post
from mrbot_app.windows.base import BaseWindow


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
        self.add_info_label(container, "Consulta individual o masiva basada en Excel.")

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
        flags = ttk.Frame(container)
        flags.pack(anchor="w", pady=2)
        ttk.Checkbutton(flags, text="proxy_request", variable=self.opt_proxy).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(flags, text="movimientos", variable=self.opt_movimientos).pack(side="left")

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
        url = ensure_trailing_slash(base_url) + "api/v1/ccma/consulta"
        resp = safe_post(url, headers, payload)
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
        df_to_process = self.ccma_df
        if "procesar" in df_to_process.columns:
            df_to_process = df_to_process[df_to_process["procesar"].str.lower().isin(["si", "sí", "yes", "y", "1"])]
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        total = len(df_to_process)
        self.set_progress(0, total)
        for idx, (_, row) in enumerate(df_to_process.iterrows(), start=1):
            cuit_rep = str(row.get("cuit_representante", "")).strip()
            cuit_repr = str(row.get("cuit_representado", "")).strip()
            movimientos_flag = parse_bool_cell(row.get("movimientos"), default=movimientos_default)
            movimientos_requested = movimientos_requested or movimientos_flag
            payload = {
                "cuit_representante": cuit_rep,
                "clave_representante": str(row.get("clave_representante", "")),
                "cuit_representado": cuit_repr,
                "proxy_request": bool(self.opt_proxy.get()),
                "movimientos": movimientos_flag
            }
            resp = safe_post(url, headers, payload)
            http_status = resp.get("http_status")
            data = resp.get("data")
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
                        "response_json": json.dumps({"response_ccma": response_obj}, ensure_ascii=False),
                        "movimientos_solicitados": movimientos_flag,
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
                        "response_json": json.dumps(data, ensure_ascii=False),
                        "error": None
                    })
            else:
                rows.append({
                    "cuit_representante": cuit_rep,
                    "cuit_representado": cuit_repr,
                    "movimientos_solicitados": movimientos_flag,
                    "response_json": None,
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
        try:
            os.makedirs("descargas", exist_ok=True)
            out_path = os.path.join("descargas", "ReporteCCMA.xlsx")
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
        preview_text = df_preview(out_df, rows=min(20, len(out_df)))
        if not movimientos_requested and movimientos_df.empty:
            preview_text += "\n\nMovimientos: no se solicitaron."
        elif movimientos_df.empty:
            preview_text += "\n\nMovimientos: hoja sin filas (sin movimientos devueltos)."
        else:
            preview_text += f"\n\nMovimientos exportados: {len(movimientos_df)} filas en hoja 'Movimientos'."
        self.set_preview(self.result_box, preview_text)
