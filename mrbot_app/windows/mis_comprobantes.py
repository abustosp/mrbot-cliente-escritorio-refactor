import json
import os
import zipfile
from typing import Dict, Optional, Any

import pandas as pd
import requests
import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.helpers import build_headers, ensure_trailing_slash, format_date_str, safe_get, safe_post
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

    def show_requests(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + f"api/v1/user/consultas/{email}"
        resp = safe_get(url, headers)
        messagebox.showinfo("Requests restantes", json.dumps(resp.get("data"), indent=2, ensure_ascii=False))

    def confirmar(self) -> None:
        # Ensure an Excel file has been loaded via ExcelHandlerMixin before proceeding
        if self.excel_df is None:
            messagebox.showerror("Error", "Carga un Excel primero.")
            return

        answer = messagebox.askyesno("Confirmar", "Esta accion enviara las consultas. Continuar?")
        if answer:
            self.run_in_thread(self._procesar_excel_worker)

    def _procesar_excel_worker(self) -> None:
        # Clear logs using the thread-safe helper, which schedules updates on the main thread.
        self.after(0, lambda: (
            self.log_text.configure(state="normal"),
            self.log_text.delete("1.0", tk.END),
            self.log_text.configure(state="disabled")
        ))

        self.log_start("Mis Comprobantes", {"modo": "masivo", "archivo": self.excel_filename})

        df = self._filter_procesar(self.excel_df)
        if df is None or df.empty:
            self.log_info("No hay filas para procesar.")
            return

        total = len(df)
        self.set_progress(0, total)

        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url_api = ensure_trailing_slash(base_url) + "api/v1/mis_comprobantes/consulta"

        FALLBACK_BASE_DIR = os.path.join("descargas", "mis_comprobantes")

        errores = []

        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            if self._abort_event.is_set():
                self.log_info("Proceso abortado por el usuario.")
                break

            try:
                # Extract fields
                desde = format_date_str(row.get("desde", ""))
                hasta = format_date_str(row.get("hasta", ""))
                cuit_inicio_sesion = str(row.get("cuit_inicio_sesion") or row.get("cuit_inicio") or row.get("cuit_login") or row.get("cuit_representante") or "").strip()

                # Try multiple keys for common fields
                representado_nombre = str(row.get("representado_nombre") or row.get("nombre_representado") or row.get("representado") or row.get("nombre") or "").strip() or "Representado"
                representado_cuit = str(row.get("representado_cuit") or row.get("cuit_representado") or row.get("representadocuit") or row.get("cuit") or "").strip()
                contrasena = str(row.get("contrasena") or row.get("clave") or row.get("clave_fiscal") or "")

                descarga_emitidos = self._to_bool(row.get("descarga_emitidos"))
                descarga_recibidos = self._to_bool(row.get("descarga_recibidos"))

                label = f"{representado_nombre} ({representado_cuit})" if representado_cuit else representado_nombre
                self.log_separator(label)
                self.log_info(f"Periodo: {desde} - {hasta}")

                payload = {
                    "desde": desde,
                    "hasta": hasta,
                    "cuit_inicio_sesion": cuit_inicio_sesion,
                    "representado_nombre": representado_nombre,
                    "representado_cuit": representado_cuit,
                    "contrasena": contrasena,
                    "descarga_emitidos": descarga_emitidos,
                    "descarga_recibidos": descarga_recibidos,
                    "carga_minio": True,
                    "carga_json": False,
                    "b64": False,
                    "carga_s3": False,
                    "proxy_request": False
                }

                safe_payload = dict(payload)
                safe_payload["contrasena"] = "***"
                self.log_request(safe_payload)

                resp = safe_post(url_api, headers, payload, timeout_sec=180) # Longer timeout for MC
                data = resp.get("data", {})
                self.log_response(resp.get("http_status"), data)

                if resp.get("http_status") != 200 or not data.get("success"):
                     err_msg = data.get("error") or data.get("detail") or data.get("message") or "Error desconocido"
                     self.log_error(f"API Error: {err_msg}")
                     errores.append(f"{label}: {err_msg}")
                     self.set_progress(idx, total)
                     continue

                # Downloads
                if descarga_emitidos:
                    self._handle_download_section(
                        data, row, "emitidos", "mis_comprobantes_emitidos_url_minio",
                        representado_nombre, representado_cuit, cuit_inicio_sesion, FALLBACK_BASE_DIR
                    )

                if descarga_recibidos:
                    self._handle_download_section(
                        data, row, "recibidos", "mis_comprobantes_recibidos_url_minio",
                        representado_nombre, representado_cuit, cuit_inicio_sesion, FALLBACK_BASE_DIR
                    )

            except Exception as exc:
                self.log_error(f"Excepcion procesando fila {idx}: {exc}")
                errores.append(f"Fila {idx}: {exc}")

            self.set_progress(idx, total)

        if errores:
            self.log_info(f"Finalizado con {len(errores)} errores.")
        else:
            self.log_info("Finalizado exitosamente.")

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, bool): return value
        text = str(value).lower().strip()
        return text in ("si", "yes", "true", "1", "s", "y")

    def _handle_download_section(self, data, row, section_key, url_key, rep_name, rep_cuit, cuit_login, fallback_base):
        url = data.get(url_key)
        if not url:
            self.log_info(f"No hay URL para {section_key}")
            return

        # Determine path
        path_col = f"ubicacion_{section_key}"
        name_col = f"nombre_{section_key}"

        target_dir = str(row.get(path_col) or "").strip()
        filename_base = str(row.get(name_col) or "").strip() or section_key.capitalize()

        if not target_dir:
             # Fallback
             safe_cuit = "".join(c for c in cuit_login if c.isalnum()) or "sin_cuit"
             safe_name = "".join(c for c in rep_name if c.isalnum() or c in " _-") or "descarga"
             target_dir = os.path.join(fallback_base, safe_cuit, safe_name)

        os.makedirs(target_dir, exist_ok=True)

        zip_path = os.path.join(target_dir, f"{filename_base}_temp.zip")
        csv_path = os.path.join(target_dir, f"{filename_base}.csv")

        self.log_info(f"Descargando {section_key} a {zip_path}")

        # Download ZIP
        try:
            r = requests.get(url, stream=True, timeout=60)
            if r.status_code == 200:
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Extract CSV
                if self._extract_csv_from_zip(zip_path, csv_path):
                    self.log_info(f"Extraído CSV: {csv_path}")
                    try:
                        os.remove(zip_path)
                    except OSError:
                        # Ignorar errores al eliminar el ZIP temporal; falla de limpieza no es crítica
                        pass
                else:
                    self.log_error(f"Fallo extracción de ZIP {zip_path}")
            else:
                self.log_error(f"Error descarga HTTP {r.status_code}")
        except Exception as e:
            self.log_error(f"Excepcion descarga: {e}")

    def _extract_csv_from_zip(self, zip_path, dest_csv) -> bool:
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                names = z.namelist()
                csv_file = next((n for n in names if n.lower().endswith(".csv")), None)
                if not csv_file and names:
                    csv_file = names[0] # Fallback to first file

                if csv_file:
                    with z.open(csv_file) as source, open(dest_csv, "wb") as target:
                        target.write(source.read())
                    return True
        except Exception as e:
            self.log_error(f"Zip error: {e}")
        return False
