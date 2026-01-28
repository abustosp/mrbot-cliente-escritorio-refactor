import json
from typing import Any, Dict, List, Optional
import os

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import ExcelHandlerMixin


class ConsultaCuitWindow(BaseWindow, ExcelHandlerMixin):
    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Consulta de CUIT", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Consulta de constancia de CUIT")
        self.add_info_label(container, "Consulta individual o masiva.")

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT individual").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.cuit_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("consulta_cuit.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=3, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2), weight=1)

        self.preview = self.add_preview(container, height=8)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Vista previa del Excel (primeras filas).")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        payload = {"cuit": self.cuit_var.get().strip()}
        url = ensure_trailing_slash(base_url) + "api/v1/consulta_cuit/individual"
        resp = safe_post(url, headers, payload)
        self.set_preview(self.result_box, json.dumps(resp, indent=2, ensure_ascii=False))

    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/consulta_cuit/masivo"

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None:
            df_to_process = self.excel_df

        cuits = [str(row.get("cuit", "")).strip() for _, row in df_to_process.iterrows() if str(row.get("cuit", "")).strip()]
        total = len(cuits)
        self.set_progress(0, total)
        payload = {"cuits": cuits}
        resp = safe_post(url, headers, payload)
        data = resp.get("data", {})
        rows: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            detail = data.get("results") or data.get("data")
            if isinstance(detail, list):
                for item in detail:
                    rows.append(item if isinstance(item, dict) else {"item": item})
        out_df = pd.DataFrame(rows) if rows else pd.DataFrame([data])
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
        self.set_progress(total, total)
