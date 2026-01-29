import json
from typing import Any, Dict, List, Optional
import os

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, safe_get
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import ExcelHandlerMixin


class ApocrifosWindow(BaseWindow, ExcelHandlerMixin):
    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Consulta de Apocrifos", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Consulta de Apocrifos")
        self.add_info_label(container, "Consulta individual o masiva de CUITs.")

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
        ttk.Button(btns, text="Ejemplo Excel", command=lambda: self.abrir_ejemplo_key("apocrifos.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=3, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2), weight=1)

        self.preview = self.add_preview(container, height=8)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Vista previa del Excel (primeras filas).")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

    def consulta_individual(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        cuit = self.cuit_var.get().strip()
        url = ensure_trailing_slash(base_url) + f"api/v1/apoc/consulta/{cuit}"
        resp = safe_get(url, headers)
        self.set_preview(self.result_box, json.dumps(resp, indent=2, ensure_ascii=False))

    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None:
             df_to_process = self.excel_df

        self.run_in_thread(self._procesar_excel_worker, df_to_process)

    def _procesar_excel_worker(self, df_to_process: pd.DataFrame) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        rows: List[Dict[str, Any]] = []

        total = len(df_to_process)
        self.set_progress(0, total)
        for idx, (_, row) in enumerate(df_to_process.iterrows(), start=1):
            if self._abort_event.is_set():
                break

            cuit = str(row.get("cuit", "")).strip()
            url = ensure_trailing_slash(base_url) + f"api/v1/apoc/consulta/{cuit}"
            resp = safe_get(url, headers)
            data = resp.get("data", {})
            rows.append(
                {
                    "cuit": cuit,
                    "http_status": resp.get("http_status"),
                    "apoc": data.get("apoc") if isinstance(data, dict) else None,
                    "message": data.get("message") if isinstance(data, dict) else None,
                }
            )
            self.set_progress(idx, total)
        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
