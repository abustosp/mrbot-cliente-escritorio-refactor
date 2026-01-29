import json
import os
from typing import Dict, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.mis_comprobantes import consulta_mc_csv
from mrbot_app.helpers import build_headers, ensure_trailing_slash, safe_get
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import ExcelHandlerMixin


class GuiDescargaMC(BaseWindow, ExcelHandlerMixin):
    def __init__(self, master=None, config_pane: Optional[ttk.Frame] = None, example_paths: Optional[Dict[str, str]] = None):
        provider = config_pane.get_config if config_pane else None
        super().__init__(master, title="Descarga de Mis Comprobantes", config_provider=provider)
        ExcelHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.config_pane = config_pane
        self.example_paths = example_paths or {}
        self.processing = False

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Modulo para descarga masiva")
        self.add_info_label(
            container,
            "Descarga de Mis Comprobantes basada en un Excel con contribuyentes. "
            "Admite columnas opcionales: procesar (SI/NO), desde, hasta, ubicacion_emitidos, nombre_emitidos, "
            "ubicacion_recibidos, nombre_recibidos. Se pueden editar variables de entorno "
            "desde el boton inferior.",
        )

        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill="x", pady=8)

        ttk.Button(btn_frame, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btn_frame, text="Requests restantes", command=self.show_requests).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btn_frame, text="Ver ejemplo", command=lambda: self.abrir_ejemplo_key("mis_comprobantes.xlsx")).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btn_frame, text="Previsualizar Excel", command=self.previsualizar_excel).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btn_frame, text="Descargar Mis Comprobantes", command=self.confirmar).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")

        btn_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.set_preview(self.preview, "Selecciona un Excel y presiona 'Previsualizar Excel' para ver los datos.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=16, service="mis_comprobantes")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_message(text)

    def show_requests(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + f"api/v1/user/consultas/{email}"
        resp = safe_get(url, headers)
        messagebox.showinfo("Requests restantes", json.dumps(resp.get("data"), indent=2, ensure_ascii=False))

    def confirmar(self) -> None:
        excel_to_use = self.excel_filename or self.example_paths.get("mis_comprobantes.xlsx")
        if not excel_to_use:
            messagebox.showerror("Error", "Primero selecciona un Excel o usa el ejemplo de mis_comprobantes.xlsx.")
            return
        if not os.path.exists(excel_to_use):
            messagebox.showerror("Error", f"No se encontró el archivo seleccionado: {excel_to_use}")
            return
        if self.processing:
            messagebox.showinfo("Proceso en curso", "Ya hay un proceso ejecutándose. Espera a que finalice.")
            return
        answer = messagebox.askyesno("Confirmar", "Esta accion enviara las consultas. Continuar?")
        if answer:
            try:
                self.processing = True
                self.clear_logs()
                self.set_progress(0, 0)
                self.log_start("Mis Comprobantes", {"modo": "masivo", "archivo": excel_to_use})
                consulta_mc_csv(
                    excel_to_use,
                    progress_callback=self.set_progress,
                    log_fn=self.log_message,
                    log_start=False,
                )
                messagebox.showinfo("Proceso finalizado", f"Consulta finalizada con {excel_to_use}. Revisa los logs en la ventana.")
            except Exception as exc:
                messagebox.showerror("Error", f"No se pudo ejecutar consulta_mc_csv: {exc}")
                self.log_error(str(exc))
            finally:
                self.processing = False
