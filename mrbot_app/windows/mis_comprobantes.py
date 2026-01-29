import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.mis_comprobantes import consulta_mc
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, safe_get, format_date_str
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import (
    ExcelHandlerMixin,
    DateRangeHandlerMixin,
    DownloadHandlerMixin
)


class GuiDescargaMC(BaseWindow, ExcelHandlerMixin, DateRangeHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "mis_comprobantes"

    def __init__(self, master=None, config_pane: Optional[ttk.Frame] = None, example_paths: Optional[Dict[str, str]] = None):
        provider = config_pane.get_config if config_pane else None
        super().__init__(master, title="Descarga de Mis Comprobantes", config_provider=provider)
        ExcelHandlerMixin.__init__(self)
        DateRangeHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.config_pane = config_pane
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Modulo de Mis Comprobantes")
        self.add_info_label(
            container,
            "Consulta individual o masiva (Excel). "
            "Admite columnas opcionales: procesar (SI/NO), desde, hasta, ubicacion_emitidos, nombre_emitidos, "
            "ubicacion_recibidos, nombre_recibidos.",
        )

        # Dates for Individual Query
        self.add_date_range_frame(container)

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT Representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Nombre Representado").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT Representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave Fiscal").grid(row=3, column=0, sticky="w", padx=4, pady=2)

        self.cuit_inicio_var = tk.StringVar()
        self.nombre_repr_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        self.clave_var = tk.StringVar()

        ttk.Entry(inputs, textvariable=self.cuit_inicio_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.nombre_repr_var, width=25).grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=4)
        self.emitidos_var = tk.BooleanVar(value=True)
        self.recibidos_var = tk.BooleanVar(value=True)
        self.b64_var = tk.BooleanVar(value=False)
        self.minio_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(opts, text="Descarga Emitidos", variable=self.emitidos_var).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Descarga Recibidos", variable=self.recibidos_var).grid(row=0, column=1, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Archivos en Base64", variable=self.b64_var).grid(row=0, column=2, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(opts, text="Carga MinIO", variable=self.minio_var).grid(row=0, column=3, padx=4, pady=2, sticky="w")

        # Download Path
        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Consulta Individual", command=self.consulta_individual).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Requests restantes", command=self.show_requests).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ver ejemplo", command=lambda: self.abrir_ejemplo_key("mis_comprobantes.xlsx")).grid(row=1, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Previsualizar Excel", command=self.previsualizar_excel).grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=2, padx=4, pady=2, sticky="ew")

        btns.columnconfigure((0, 1, 2), weight=1)

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

        def _fetch():
            resp = safe_get(url, headers)
            messagebox.showinfo("Requests restantes", json.dumps(resp.get("data"), indent=2, ensure_ascii=False))

        self.run_in_thread(lambda: self.after(0, lambda: messagebox.showinfo("Requests restantes", json.dumps(safe_get(url, headers).get("data"), indent=2, ensure_ascii=False))))


    def _process_single_response(self, response: Dict[str, Any], download_root: str,
                                 cuit_repr: str, nombre_repr: str,
                                 descarga_emitidos: bool, descarga_recibidos: bool) -> List[str]:
        """
        Helper method to process the response dictionary, extract MinIO links and download them.
        Returns a list of error messages (if any).
        """
        errors = []

        # Check success
        if not response.get("success", False):
            error_msg = response.get("error", response.get("detail", response.get("message", "Error desconocido")))
            self.log_error(f"Error en API: {error_msg}")
            return [str(error_msg)]

        # Emitidos
        if descarga_emitidos:
            url_emitidos = response.get("mis_comprobantes_emitidos_url_minio")
            if url_emitidos:
                self.log_info(f"Emitidos URL: {url_emitidos[:50]}...")
                # Download logic
                emitidos_dir = os.path.join(download_root, "Emitidos")
                os.makedirs(emitidos_dir, exist_ok=True)

                # Mock a list of links format expected by DownloadHandlerMixin logic or similar
                # Since mixin uses generic list, we construct one manually
                link_obj = {"url": url_emitidos, "filename": "Emitidos.zip"}
                downloads, errs = self._download_links_direct([link_obj], emitidos_dir)
                if downloads:
                     self.log_info(f"Emitidos descargado en: {emitidos_dir}")
                     # Extract logic could be added here if needed, similar to original script
                errors.extend(errs)
            else:
                self.log_info("No URL MinIO para Emitidos.")

        # Recibidos
        if descarga_recibidos:
            url_recibidos = response.get("mis_comprobantes_recibidos_url_minio")
            if url_recibidos:
                self.log_info(f"Recibidos URL: {url_recibidos[:50]}...")
                recibidos_dir = os.path.join(download_root, "Recibidos")
                os.makedirs(recibidos_dir, exist_ok=True)

                link_obj = {"url": url_recibidos, "filename": "Recibidos.zip"}
                downloads, errs = self._download_links_direct([link_obj], recibidos_dir)
                if downloads:
                     self.log_info(f"Recibidos descargado en: {recibidos_dir}")
                errors.extend(errs)
            else:
                self.log_info("No URL MinIO para Recibidos.")

        return errors

    def _download_links_direct(self, links: List[Dict[str, str]], dest_dir: str) -> tuple[int, List[str]]:
        # Reuse logic from minio_helpers imported in mixins or implemented locally
        from mrbot_app.windows.minio_helpers import download_links
        return download_links(links, dest_dir)

    def consulta_individual(self) -> None:
        # Gather data on main thread
        desde = self.desde_var.get().strip()
        hasta = self.hasta_var.get().strip()
        cuit_inicio = self.cuit_inicio_var.get().strip()
        nombre_repr = self.nombre_repr_var.get().strip()
        cuit_repr = self.cuit_repr_var.get().strip()
        clave = self.clave_var.get().strip()

        descarga_emitidos = self.emitidos_var.get()
        descarga_recibidos = self.recibidos_var.get()
        carga_minio = self.minio_var.get()
        b64 = self.b64_var.get()

        target_dir = self.download_dir_var.get().strip()

        if not cuit_inicio or not cuit_repr or not clave:
            messagebox.showerror("Error", "Faltan datos obligatorios (CUITs, Clave).")
            return

        self.clear_logs()
        self.log_start("Mis Comprobantes", {"modo": "individual"})

        # Run worker
        self.run_in_thread(
            self._worker_individual,
            desde, hasta, cuit_inicio, nombre_repr, cuit_repr, clave,
            descarga_emitidos, descarga_recibidos, carga_minio, b64, target_dir
        )

    def _worker_individual(self, desde, hasta, cuit_inicio, nombre_repr, cuit_repr, clave,
                           d_emitidos, d_recibidos, minio, b64, target_dir):

        self.log_separator(f"{nombre_repr} ({cuit_repr})")

        # Prepare download dir
        final_dir = target_dir
        if not final_dir:
            from mrbot_app.mis_comprobantes import FALLBACK_BASE_DIR
            final_dir = os.path.join(FALLBACK_BASE_DIR, cuit_inicio, nombre_repr or cuit_repr)
            try:
                os.makedirs(final_dir, exist_ok=True)
            except Exception:
                final_dir = "Descargas"

        self.log_info(f"Directorio descarga: {final_dir}")

        response = consulta_mc(
            desde, hasta, cuit_inicio, nombre_repr, cuit_repr, clave,
            d_emitidos, d_recibidos, carga_minio=minio, carga_json=False, b64=b64,
            log_fn=self.log_message
        )

        self._process_single_response(response, final_dir, cuit_repr, nombre_repr, d_emitidos, d_recibidos)
        self.log_info("Proceso individual finalizado.")


    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            messagebox.showerror("Error", "Carga un Excel primero.")
            return

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            messagebox.showwarning("Sin filas", "No hay filas con procesar=SI")
            return

        # Capture defaults from UI
        default_desde = self.desde_var.get().strip()
        default_hasta = self.hasta_var.get().strip()

        # Copy for thread safety
        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("Mis Comprobantes", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, default_desde, default_hasta)

    def _worker_excel(self, df, default_desde, default_hasta):
        total = len(df)
        self.set_progress(0, total)

        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            if self._abort_event.is_set():
                break

            desde = format_date_str(row.get("desde", "")) or default_desde
            hasta = format_date_str(row.get("hasta", "")) or default_hasta

            cuit_inicio = str(row.get("cuit_inicio_sesion", "") or row.get("cuit_representante", "")).strip()
            nombre_repr = str(row.get("representado_nombre", "") or row.get("nombre_representado", "")).strip()
            cuit_repr = str(row.get("representado_cuit", "") or row.get("cuit_representado", "")).strip()
            clave = str(row.get("contrasena", "") or row.get("clave", "")).strip()

            # Booleanos con logica del excel mixin o pandas
            def _bool_val(key, default):
                val = row.get(key, "")
                text = str(val).lower().strip()
                if text in ("si", "1", "true", "yes", "y"): return True
                if text in ("no", "0", "false", "n"): return False
                return default

            d_emitidos = _bool_val("descarga_emitidos", False)
            d_recibidos = _bool_val("descarga_recibidos", False)

            # Paths specific
            row_download = str(row.get("ubicacion_descarga", "")).strip()

            self.log_separator(f"{nombre_repr} ({cuit_repr})")

            # Determine directory
            final_dir = row_download
            if not final_dir:
                 from mrbot_app.mis_comprobantes import FALLBACK_BASE_DIR
                 final_dir = os.path.join(FALLBACK_BASE_DIR, cuit_inicio, nombre_repr or cuit_repr)

            try:
                os.makedirs(final_dir, exist_ok=True)
            except Exception:
                pass

            self.log_info(f"Periodo: {desde} - {hasta}")

            response = consulta_mc(
                desde, hasta, cuit_inicio, nombre_repr, cuit_repr, clave,
                d_emitidos, d_recibidos, carga_minio=True, carga_json=False, b64=False,
                log_fn=self.log_message
            )

            self._process_single_response(response, final_dir, cuit_repr, nombre_repr, d_emitidos, d_recibidos)

            self.set_progress(idx, total)

        self.log_info("Proceso masivo finalizado.")
