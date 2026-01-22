import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mrbot_app.files import open_with_default_app
from mrbot_app.helpers import build_headers, df_preview, ensure_trailing_slash, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.minio_helpers import build_link, collect_minio_links, download_links, prepare_download_dir


class DeclaracionEnLineaWindow(BaseWindow):
    MODULE_DIR = "Declaracion_en_Linea"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="DDJJ en Linea")
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.config_provider = config_provider
        self.example_paths = example_paths or {}
        self.ddjj_df: Optional[pd.DataFrame] = None

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Declaracion en Linea (DDJJ)")
        self.add_info_label(
            container,
            "Consulta individual o masiva por periodo. Descarga automatica desde MinIO (carga_minio=True) "
            "con proxy_request=False fijo.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave representante").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Representado nombre").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Periodo desde (AAAAMM)").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Periodo hasta (AAAAMM)").grid(row=5, column=0, sticky="w", padx=4, pady=2)
        self.cuit_rep_var = tk.StringVar()
        self.clave_rep_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        self.nombre_repr_var = tk.StringVar()
        self.periodo_desde_var = tk.StringVar()
        self.periodo_hasta_var = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_rep_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.nombre_repr_var, width=25).grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.periodo_desde_var, width=25).grid(row=4, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.periodo_hasta_var, width=25).grid(row=5, column=1, padx=4, pady=2, sticky="ew")
        inputs.columnconfigure(1, weight=1)

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
        ttk.Button(btns, text="Previsualizar Excel", command=lambda: self.open_df_preview(self._filter_procesar(self.ddjj_df), "Previsualizacion DDJJ")).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.result_box = self.add_preview(container, height=12)
        self.set_preview(self.preview, "Excel no cargado o sin previsualizar. Usa 'Previsualizar Excel'.")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")

        self.log_text = self.add_collapsible_log(container, title="Logs de ejecucion", height=10, service="declaracion_en_linea")

    def seleccionar_carpeta_descarga(self) -> None:
        folder = filedialog.askdirectory()
        self.bring_to_front()
        if folder:
            self.download_dir_var.set(folder)

    def abrir_ejemplo(self) -> None:
        path = self.example_paths.get("declaracion_en_linea.xlsx")
        if not path:
            messagebox.showerror("Error", "No se encontro el Excel de ejemplo.")
            return
        if not open_with_default_app(path):
            messagebox.showerror("Error", "No se pudo abrir el Excel de ejemplo.")

    def cargar_excel(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        self.bring_to_front()
        if not filename:
            return
        try:
            self.ddjj_df = pd.read_excel(filename, dtype=str).fillna("")
            self.ddjj_df.columns = [c.strip().lower() for c in self.ddjj_df.columns]
            df_prev = self._filter_procesar(self.ddjj_df)
            self.set_preview(self.preview, df_preview(df_prev if df_prev is not None else self.ddjj_df))
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo leer el Excel: {exc}")
            self.ddjj_df = None

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        self.log_text.update_idletasks()

    def _filter_procesar(self, df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None:
            return None
        filtered = df
        if "procesar" in filtered.columns:
            filtered = filtered[filtered["procesar"].str.lower().isin(["si", "sí", "yes", "y", "1"])]
        return filtered

    def _optional_value(self, value: str) -> Optional[str]:
        clean = (value or "").strip()
        return clean if clean else None

    def _extract_links(self, data: Any) -> List[Dict[str, str]]:
        links: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        if isinstance(data, dict):
            archivos = data.get("archivos")
            if isinstance(archivos, list):
                for idx, item in enumerate(archivos, start=1):
                    if not isinstance(item, dict):
                        continue
                    candidates = {
                        "ddjj_excel": item.get("link_minio_ddjj_excel"),
                        "dj": item.get("link_minio_dj"),
                        "vep": item.get("link_minio_vep"),
                    }
                    for label, url in candidates.items():
                        link = build_link(url, label, "ddjj", idx)
                        if link:
                            key = (link["url"], link["filename"])
                            if key not in seen:
                                seen.add(key)
                                links.append(link)
        if not links:
            links = collect_minio_links(data, "ddjj")
        return links

    def _download_from_data(self, data: Any, desired_dir: str, cuit_repr: str) -> tuple[int, List[str], Optional[str]]:
        links = self._extract_links(data)
        if not links:
            return 0, [], None
        download_dir, dir_msgs = prepare_download_dir(self.MODULE_DIR, desired_dir, cuit_repr)
        for msg in dir_msgs:
            self.append_log(msg + "\n")
        downloads, errors = download_links(links, download_dir)
        return downloads, errors, download_dir

    def consulta_individual(self) -> None:
        base_url, api_key, email = self.config_provider()
        headers = build_headers(api_key, email)
        cuit_repr = self._optional_value(self.cuit_repr_var.get())
        payload = {
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave_representante": self.clave_rep_var.get(),
            "cuit_representado": cuit_repr,
            "representado_nombre": self._optional_value(self.nombre_repr_var.get()),
            "periodo_desde": self.periodo_desde_var.get().strip(),
            "periodo_hasta": self.periodo_hasta_var.get().strip(),
            "carga_minio": True,
            "proxy_request": False,
        }
        url = ensure_trailing_slash(base_url) + "api/v1/declaracion-en-linea/consulta"
        self.clear_logs()
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        self.append_log(f"Consulta individual Declaracion en Linea: {json.dumps(safe_payload, ensure_ascii=False)}\n")
        resp = safe_post(url, headers, payload)
        data = resp.get("data", {})
        self.append_log(f"Respuesta HTTP {resp.get('http_status')}: {json.dumps(data, ensure_ascii=False)}\n")
        cuit_folder = cuit_repr or payload["cuit_representante"]
        downloads, errors, download_dir = self._download_from_data(data, self.download_dir_var.get(), cuit_folder)
        if downloads:
            self.append_log(f"Descargas completadas: {downloads} -> {download_dir}\n")
        elif data:
            self.append_log("Sin links de descarga en la respuesta.\n")
        for err in errors:
            self.append_log(f"Error de descarga: {err}\n")
        self.set_preview(self.result_box, json.dumps(resp, indent=2, ensure_ascii=False))

    def procesar_excel(self) -> None:
        if self.ddjj_df is None or self.ddjj_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return
        base_url, api_key, email = self.config_provider()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + "api/v1/declaracion-en-linea/consulta"
        rows: List[Dict[str, Any]] = []
        df_to_process = self._filter_procesar(self.ddjj_df)
        if df_to_process is None or df_to_process.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        self.clear_logs()
        self.append_log(f"Procesando {len(df_to_process)} filas Declaracion en Linea\n")
        total = len(df_to_process)
        self.set_progress(0, total)
        for idx, (_, row) in enumerate(df_to_process.iterrows(), start=1):
            cuit_rep = str(row.get("cuit_representante", "")).strip()
            cuit_repr = self._optional_value(str(row.get("cuit_representado", "")))
            row_download = str(row.get("ubicacion_descarga") or row.get("path_descarga") or row.get("carpeta_descarga") or "").strip()
            payload = {
                "cuit_representante": cuit_rep,
                "clave_representante": str(row.get("clave_representante", "")),
                "cuit_representado": cuit_repr,
                "representado_nombre": self._optional_value(str(row.get("representado_nombre", ""))),
                "periodo_desde": str(row.get("periodo_desde", "")).strip(),
                "periodo_hasta": str(row.get("periodo_hasta", "")).strip(),
                "carga_minio": True,
                "proxy_request": False,
            }
            safe_payload = dict(payload)
            safe_payload["clave_representante"] = "***"
            self.append_log(f"- Fila {cuit_repr or cuit_rep}: payload {json.dumps(safe_payload, ensure_ascii=False)}\n")
            resp = safe_post(url, headers, payload)
            data = resp.get("data", {})
            self.append_log(f"  -> HTTP {resp.get('http_status')}: {json.dumps(data, ensure_ascii=False)}\n")
            cuit_folder = cuit_repr or cuit_rep
            downloads, errors, download_dir = self._download_from_data(data, row_download or self.download_dir_var.get(), cuit_folder)
            if downloads:
                self.append_log(f"    Descargas completadas: {downloads} -> {download_dir}\n")
            elif data:
                self.append_log("    Sin links de descarga\n")
            for err in errors:
                self.append_log(f"    Error de descarga: {err}\n")
            rows.append(
                {
                    "cuit_representado": cuit_folder,
                    "http_status": resp.get("http_status"),
                    "success": data.get("success") if isinstance(data, dict) else None,
                    "message": data.get("message") if isinstance(data, dict) else None,
                    "descargas": downloads,
                    "errores_descarga": "; ".join(errors) if errors else None,
                    "carpeta_descarga": download_dir,
                }
            )
            self.set_progress(idx, total)
        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
