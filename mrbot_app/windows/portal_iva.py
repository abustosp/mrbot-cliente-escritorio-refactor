import concurrent.futures
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse, unquote

from mrbot_app.config import get_max_workers
from mrbot_app.portal_iva import consulta_portal_iva, FALLBACK_BASE_DIR
from mrbot_app.helpers import (
    build_headers,
    df_preview,
    ensure_trailing_slash,
    safe_get,
    parse_bool_cell,
    format_date_str,
    get_unique_filename,
    unzip_and_rename,
)
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import ExcelHandlerMixin, DownloadHandlerMixin


class PortalIvaWindow(BaseWindow, ExcelHandlerMixin, DownloadHandlerMixin):
    MODULE_DIR = "portal_iva"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Descarga Portal IVA", config_provider=config_provider)
        ExcelHandlerMixin.__init__(self)
        DownloadHandlerMixin.__init__(self)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Modulo Portal IVA")
        self.add_info_label(
            container,
            "Descarga de archivos CSV del Portal IVA (ARCA). "
            "Consulta individual o masiva via Excel. "
            "Admite columnas opcionales: procesar (SI/NO), ubicacion_ventas, nombre_ventas, "
            "ubicacion_compras, nombre_compras y proxy_request.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        ttk.Label(inputs, text="CUIT Representante").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Clave Representante").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="CUIT Representado").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Denominacion").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(inputs, text="Periodo (AAAAMM)").grid(row=4, column=0, sticky="w", padx=4, pady=2)

        self.cuit_rep_var = tk.StringVar()
        self.clave_var = tk.StringVar()
        self.cuit_repr_var = tk.StringVar()
        self.denominacion_var = tk.StringVar()
        self.periodo_var = tk.StringVar()

        ttk.Entry(inputs, textvariable=self.cuit_rep_var, width=25).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.clave_var, width=25, show="*").grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.cuit_repr_var, width=25).grid(row=2, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.denominacion_var, width=25).grid(row=3, column=1, padx=4, pady=2, sticky="ew")
        ttk.Entry(inputs, textvariable=self.periodo_var, width=15).grid(row=4, column=1, padx=4, pady=2, sticky="w")
        inputs.columnconfigure(1, weight=1)

        iva_opts = ttk.LabelFrame(container, text="Opciones IVA", padding=4)
        iva_opts.pack(fill="x", pady=4)
        self.operaciones_ng_o_e_var = tk.BooleanVar(value=False)
        self.prorrateo_global_var = tk.BooleanVar(value=False)
        self.prorrateo_asignacion_directa_var = tk.BooleanVar(value=False)
        self.prorrateo_ambos_var = tk.BooleanVar(value=False)
        self.importacion_definitiva_bienes_var = tk.BooleanVar(value=False)
        self.importacion_servicios_var = tk.BooleanVar(value=False)
        self.regimen_turiva_var = tk.BooleanVar(value=False)
        self.bienes_usados_var = tk.BooleanVar(value=False)
        self.ninguna_anteriores_var = tk.BooleanVar(value=True)

        iva_checkboxes = [
            ("Op. No Grav. o Exentas", self.operaciones_ng_o_e_var),
            ("Prorrateo Global", self.prorrateo_global_var),
            ("Prorrateo Asig. Directa", self.prorrateo_asignacion_directa_var),
            ("Prorrateo Ambos", self.prorrateo_ambos_var),
            ("Importac. Definitiva Bienes", self.importacion_definitiva_bienes_var),
            ("Importac. Servicios", self.importacion_servicios_var),
            ("Regimen Turismo (TurIVA)", self.regimen_turiva_var),
            ("Bienes Usados", self.bienes_usados_var),
        ]
        for i, (text, var) in enumerate(iva_checkboxes):
            row = i // 2
            col = i % 2
            ttk.Checkbutton(iva_opts, text=text, variable=var).grid(row=row, column=col, padx=4, pady=1, sticky="w")

        ttk.Checkbutton(
            iva_opts, text="Ninguna de las anteriores", variable=self.ninguna_anteriores_var
        ).grid(row=len(iva_checkboxes) // 2 + 1, column=0, columnspan=2, padx=4, pady=1, sticky="w")

        download_opts = ttk.Frame(container)
        download_opts.pack(fill="x", pady=4)
        self.descarga_csv_ventas_var = tk.BooleanVar(value=True)
        self.descarga_csv_compras_var = tk.BooleanVar(value=True)
        self.carga_minio_var = tk.BooleanVar(value=True)
        self.proxy_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(download_opts, text="Descargar CSV Ventas", variable=self.descarga_csv_ventas_var).grid(
            row=0, column=0, padx=4, pady=2, sticky="w"
        )
        ttk.Checkbutton(download_opts, text="Descargar CSV Compras", variable=self.descarga_csv_compras_var).grid(
            row=0, column=1, padx=4, pady=2, sticky="w"
        )
        ttk.Checkbutton(download_opts, text="Carga MinIO", variable=self.carga_minio_var).grid(
            row=0, column=2, padx=4, pady=2, sticky="w"
        )
        ttk.Checkbutton(download_opts, text="proxy_request", variable=self.proxy_var).grid(
            row=0, column=3, padx=4, pady=2, sticky="w"
        )

        self.add_download_path_frame(container)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Consulta Individual", command=self.consulta_individual).grid(
            row=0, column=0, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(
            row=0, column=1, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Requests restantes", command=self.show_requests).grid(
            row=0, column=2, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Ver ejemplo", command=lambda: self.abrir_ejemplo_key("portal_iva.xlsx")).grid(
            row=1, column=0, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Previsualizar Excel", command=self.previsualizar_excel).grid(
            row=1, column=1, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(
            row=1, column=2, padx=4, pady=2, sticky="ew"
        )
        btns.columnconfigure((0, 1, 2), weight=1)

        self.preview = self.add_preview(container, height=8, show=False)
        self.set_preview(
            self.preview, "Selecciona un Excel y presiona 'Previsualizar Excel' para ver los datos."
        )

        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(
            container, title="Logs de ejecucion", height=16, service="portal_iva"
        )

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log_message(text)

    def _build_payload_from_ui(self) -> Dict[str, Any]:
        periodo = self.periodo_var.get().strip()
        periodo_digits = "".join(ch for ch in periodo if ch.isdigit())
        if len(periodo_digits) >= 6:
            periodo = periodo_digits[:6]

        payload = {
            "cuit_representante": self.cuit_rep_var.get().strip(),
            "clave_representante": self.clave_var.get(),
            "cuit_representado": self.cuit_repr_var.get().strip(),
            "denominacion": self.denominacion_var.get().strip(),
            "periodo": periodo,
            "operaciones_ng_o_e": bool(self.operaciones_ng_o_e_var.get()),
            "prorrateo_global": bool(self.prorrateo_global_var.get()),
            "prorrateo_asignacion_directa": bool(self.prorrateo_asignacion_directa_var.get()),
            "prorrateo_ambos": bool(self.prorrateo_ambos_var.get()),
            "importacion_definitiva_bienes": bool(self.importacion_definitiva_bienes_var.get()),
            "importacion_servicios": bool(self.importacion_servicios_var.get()),
            "regimen_turiva": bool(self.regimen_turiva_var.get()),
            "bienes_usados": bool(self.bienes_usados_var.get()),
            "ninguna_anteriores": bool(self.ninguna_anteriores_var.get()),
            "descarga_csv_ventas": bool(self.descarga_csv_ventas_var.get()),
            "descarga_csv_compras": bool(self.descarga_csv_compras_var.get()),
            "carga_minio": bool(self.carga_minio_var.get()),
            "proxy_request": bool(self.proxy_var.get()),
        }
        return payload

    def _extract_archivos(self, data: Dict[str, Any]) -> List[Dict[str, str]]:
        archivos = data.get("archivos", [])
        if not isinstance(archivos, list):
            return []
        result = []
        for item in archivos:
            if isinstance(item, dict) and item.get("url_minio"):
                result.append({
                    "libro": item.get("libro", "desconocido"),
                    "archivo": item.get("archivo", "archivo.zip"),
                    "url": item["url_minio"],
                })
        return result

    def _get_success_and_error(self, data: Dict[str, Any]) -> tuple[bool, str]:
        detail = data.get("detail")
        if isinstance(detail, dict):
            success = detail.get("success", data.get("success", False))
            messages = detail.get("message", [])
            if isinstance(messages, list):
                error_text = "; ".join(str(m) for m in messages if m)
            else:
                error_text = str(messages) if messages else ""
            return success, error_text
        success = data.get("success", False)
        error_text = str(
            data.get("error") or data.get("message") or data.get("detail") or ""
        )
        if isinstance(error_text, list):
            error_text = "; ".join(str(e) for e in error_text) if error_text else ""
        return success, error_text

    def _process_single_response(
        self,
        response: Dict[str, Any],
        download_root: str,
        descarga_ventas: bool,
        descarga_compras: bool,
    ) -> tuple[int, List[str]]:
        downloads_total = 0
        errors = []

        success, error_text = self._get_success_and_error(response)
        if not success:
            msg = error_text or "Error desconocido"
            self.log_error(f"Error en API: {msg}")
            return 0, [msg]

        archivos = self._extract_archivos(response)

        for item in archivos:
            libro = item["libro"]
            url = item["url"]

            if libro == "ventas" and not descarga_ventas:
                continue
            if libro == "compras" and not descarga_compras:
                continue

            self.log_info(f"{libro.capitalize()} URL: {url[:50]}...")
            subdir = os.path.join(download_root, libro.capitalize())
            os.makedirs(subdir, exist_ok=True)

            link_obj = {"url": url, "filename": f"{libro.capitalize()}.zip"}
            downloads, errs = self._download_links_direct([link_obj], subdir)
            downloads_total += downloads
            if downloads:
                self.log_info(f"{libro.capitalize()} descargado en: {subdir}")
            errors.extend(errs)

        return downloads_total, errors

    def _process_response_excel(
        self,
        response: Dict[str, Any],
        ub_ventas: str,
        nom_ventas: str,
        ub_compras: str,
        nom_compras: str,
        fallback_root: str,
    ) -> tuple[int, List[str]]:
        downloads_total = 0
        errors = []

        success, error_text = self._get_success_and_error(response)
        if not success:
            msg = error_text or "Error desconocido"
            self.log_error(f"Error en API: {msg}")
            return 0, [msg]

        archivos = self._extract_archivos(response)

        for item in archivos:
            libro = item["libro"]
            url = item["url"]
            nombre_original = item.get("archivo", f"{libro}.zip")

            if libro == "ventas":
                custom_path = ub_ventas
                custom_name = nom_ventas
            elif libro == "compras":
                custom_path = ub_compras
                custom_name = nom_compras
            else:
                continue

            self.log_info(f"{libro.capitalize()} URL: {url[:50]}...")

            if custom_path:
                target_dir = custom_path
            else:
                target_dir = os.path.join(fallback_root, libro.capitalize())

            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as e:
                errors.append(f"Error creando directorio {target_dir}: {e}")
                continue

            if custom_name:
                filename_base = custom_name
                if not filename_base.lower().endswith(".zip"):
                    filename_zip = f"{filename_base}.zip"
                else:
                    filename_zip = filename_base
                    filename_base = os.path.splitext(filename_base)[0]
            else:
                path_url = urlparse(url).path
                derived_name = unquote(os.path.basename(path_url))
                if derived_name and derived_name.lower().endswith(".zip"):
                    filename_zip = derived_name
                    filename_base = os.path.splitext(derived_name)[0]
                else:
                    filename_base = libro
                    filename_zip = f"{filename_base}.zip"

            final_filename_zip = get_unique_filename(target_dir, filename_zip)
            link_obj = {"url": url, "filename": final_filename_zip}
            downloads, errs = self._download_links_direct([link_obj], target_dir)
            downloads_total += downloads

            if errs:
                errors.extend(errs)

            if downloads > 0:
                full_zip_path = os.path.join(target_dir, final_filename_zip)
                self.log_info(f"{libro.capitalize()} descargado en: {full_zip_path}")

                final_stem = os.path.splitext(final_filename_zip)[0]
                extracted_path = unzip_and_rename(full_zip_path, final_stem)
                if extracted_path:
                    self.log_info(f"Descomprimido: {os.path.basename(extracted_path)}")
                else:
                    warning = f"No se pudo descomprimir/renombrar {full_zip_path}"
                    self.log_warning(warning)
                    errors.append(warning)

        return downloads_total, errors

    def _download_links_direct(
        self, links: List[Dict[str, str]], dest_dir: str
    ) -> tuple[int, List[str]]:
        from mrbot_app.windows.minio_helpers import download_links

        return download_links(links, dest_dir)

    def show_requests(self) -> None:
        base_url, api_key, email = self._get_config()
        headers = build_headers(api_key, email)
        url = ensure_trailing_slash(base_url) + f"api/v1/user/consultas/{email}"

        def _fetch():
            resp = safe_get(url, headers)
            messagebox.showinfo(
                "Requests restantes",
                json.dumps(resp.get("data"), indent=2, ensure_ascii=False),
            )

        self.run_in_thread(
            lambda: self.after(
                0,
                lambda: messagebox.showinfo(
                    "Requests restantes",
                    json.dumps(safe_get(url, headers).get("data"), indent=2, ensure_ascii=False),
                ),
            )
        )

    def consulta_individual(self) -> None:
        payload = self._build_payload_from_ui()
        cuit_repr = payload.get("cuit_representado", "").strip()
        cuit_rep = payload.get("cuit_representante", "").strip()

        if not cuit_rep or not payload.get("clave_representante", "").strip():
            messagebox.showerror("Error", "Faltan datos obligatorios (CUIT y Clave).")
            return

        self.clear_logs()
        self.log_start("Portal IVA", {"modo": "individual"})

        self.run_in_thread(
            self.run_with_log_block,
            cuit_repr or cuit_rep or "sin_cuit",
            self._worker_individual,
            payload,
        )

    def _worker_individual(self, payload: Dict[str, Any]) -> None:
        cuit_repr = payload.get("cuit_representado", "") or payload.get("cuit_representante", "")
        descarga_ventas = payload.get("descarga_csv_ventas", True)
        descarga_compras = payload.get("descarga_csv_compras", True)
        proxy_request = payload.get("proxy_request", False)
        cuit_rep = payload["cuit_representante"]

        self.log_separator(f"{payload['denominacion']} ({cuit_repr})")

        target_dir = self.download_dir_var.get().strip()
        final_dir = target_dir
        if not final_dir:
            final_dir = os.path.join(FALLBACK_BASE_DIR, cuit_rep, payload.get("denominacion", cuit_repr))
            try:
                os.makedirs(final_dir, exist_ok=True)
            except Exception:
                final_dir = "Descargas"

        self.log_info(f"Directorio descarga: {final_dir}")

        response = consulta_portal_iva(
            cuit_representante=cuit_rep,
            clave_representante=payload["clave_representante"],
            cuit_representado=payload["cuit_representado"],
            denominacion=payload["denominacion"],
            periodo=payload["periodo"],
            operaciones_ng_o_e=payload["operaciones_ng_o_e"],
            prorrateo_global=payload["prorrateo_global"],
            prorrateo_asignacion_directa=payload["prorrateo_asignacion_directa"],
            prorrateo_ambos=payload["prorrateo_ambos"],
            importacion_definitiva_bienes=payload["importacion_definitiva_bienes"],
            importacion_servicios=payload["importacion_servicios"],
            regimen_turiva=payload["regimen_turiva"],
            bienes_usados=payload["bienes_usados"],
            ninguna_anteriores=payload["ninguna_anteriores"],
            descarga_csv_ventas=descarga_ventas,
            descarga_csv_compras=descarga_compras,
            carga_minio=True,
            proxy_request=proxy_request,
            log_fn=self.log_message,
        )

        self._process_single_response(response, final_dir, descarga_ventas, descarga_compras)
        self.log_info("Proceso individual finalizado.")

    def procesar_excel(self) -> None:
        if self.excel_df is None or self.excel_df.empty:
            messagebox.showerror("Error", "Carga un Excel primero.")
            return

        df_to_process = self._filter_procesar(self.excel_df)
        if df_to_process is None or df_to_process.empty:
            messagebox.showwarning("Sin filas", "No hay filas con procesar=SI")
            return

        default_proxy = bool(self.proxy_var.get())
        df_copy = df_to_process.copy()

        self.clear_logs()
        self.log_start("Portal IVA", {"modo": "masivo", "filas": len(df_copy)})

        self.run_in_thread(self._worker_excel, df_copy, default_proxy)

    def _worker_excel(self, df: pd.DataFrame, default_proxy: bool) -> None:
        rows: List[Dict[str, Any]] = []
        total = len(df)
        self.set_progress(0, total)
        max_workers = get_max_workers()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.run_with_log_block,
                    str(
                        row.get("cuit_representado", "")
                        or row.get("cuit_representante", "")
                        or "sin_cuit"
                    ).strip(),
                    self._process_row_portal_iva,
                    row,
                    default_proxy,
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

        out_df = pd.DataFrame(rows)
        self.set_preview(self.result_box, df_preview(out_df, rows=min(20, len(out_df))))
        self.set_execution_summary(self.build_download_execution_summary("Portal IVA", rows, total_expected=total))
        self.log_info("Procesamiento masivo finalizado.")

    def _process_row_portal_iva(
        self, row: pd.Series, default_proxy: bool
    ) -> Optional[Dict[str, Any]]:
        if self._abort_event.is_set():
            return None

        cuit_representante = str(row.get("cuit_representante", "")).strip()
        clave = str(row.get("clave_representante", "") or row.get("clave", "") or row.get("contrasena", "")).strip()
        cuit_representado = str(row.get("cuit_representado", "")).strip()
        denominacion = str(row.get("denominacion", "") or row.get("denominacion_representado", "")).strip()

        periodo = str(row.get("periodo", "")).strip()
        periodo_digits = "".join(ch for ch in periodo if ch.isdigit())
        if len(periodo_digits) >= 6:
            periodo = periodo_digits[:6]

        def _bool_val(key: str, default: bool) -> bool:
            val = row.get(key, "")
            text = str(val).lower().strip()
            if text in ("si", "1", "true", "yes", "y"):
                return True
            if text in ("no", "0", "false", "n"):
                return False
            return default

        operaciones_ng_o_e = _bool_val("operaciones_ng_o_e", False)
        prorrateo_global = _bool_val("prorrateo_global", False)
        prorrateo_asignacion_directa = _bool_val("prorrateo_asignacion_directa", False)
        prorrateo_ambos = _bool_val("prorrateo_ambos", False)
        importacion_definitiva_bienes = _bool_val("importacion_definitiva_bienes", False)
        importacion_servicios = _bool_val("importacion_servicios", False)
        regimen_turiva = _bool_val("regimen_turiva", False)
        bienes_usados = _bool_val("bienes_usados", False)
        ninguna_anteriores = _bool_val("ninguna_anteriores", True)
        descarga_ventas = _bool_val("descarga_csv_ventas", True)
        descarga_compras = _bool_val("descarga_csv_compras", True)
        proxy_request = _bool_val("proxy_request", default_proxy) if "proxy_request" in row.index else default_proxy

        ub_ventas = str(row.get("ubicacion_ventas", "")).strip()
        nom_ventas = str(row.get("nombre_ventas", "")).strip()
        ub_compras = str(row.get("ubicacion_compras", "")).strip()
        nom_compras = str(row.get("nombre_compras", "")).strip()

        row_download = str(row.get("ubicacion_descarga", "")).strip()

        self.log_separator(f"{denominacion} ({cuit_representado})")

        fallback_dir = row_download
        if not fallback_dir:
            fallback_dir = os.path.join(
                FALLBACK_BASE_DIR, cuit_representante, denominacion or cuit_representado
            )

        try:
            if not (ub_ventas and ub_compras):
                os.makedirs(fallback_dir, exist_ok=True)
        except Exception:
            pass

        self.log_info(f"Periodo: {periodo}")

        try:
            retry_val = int(row.get("retry", 0))
        except (ValueError, TypeError):
            retry_val = 0
        total_attempts = retry_val if retry_val > 1 else 1

        response = {}
        for attempt in range(1, total_attempts + 1):
            if attempt > 1:
                self.log_info(f"Reintentando... (Intento {attempt}/{total_attempts})")

            response = consulta_portal_iva(
                cuit_representante=cuit_representante,
                clave_representante=clave,
                cuit_representado=cuit_representado,
                denominacion=denominacion,
                periodo=periodo,
                operaciones_ng_o_e=operaciones_ng_o_e,
                prorrateo_global=prorrateo_global,
                prorrateo_asignacion_directa=prorrateo_asignacion_directa,
                prorrateo_ambos=prorrateo_ambos,
                importacion_definitiva_bienes=importacion_definitiva_bienes,
                importacion_servicios=importacion_servicios,
                regimen_turiva=regimen_turiva,
                bienes_usados=bienes_usados,
                ninguna_anteriores=ninguna_anteriores,
                descarga_csv_ventas=descarga_ventas,
                descarga_csv_compras=descarga_compras,
                carga_minio=True,
                proxy_request=proxy_request,
                log_fn=self.log_message,
            )

            if response.get("success", False):
                break

        downloads, errors = self._process_response_excel(
            response,
            ub_ventas,
            nom_ventas,
            ub_compras,
            nom_compras,
            fallback_dir,
        )
        success, error_text = self._get_success_and_error(response)
        return {
            "cuit_representado": cuit_representado or cuit_representante,
            "success": success,
            "message": error_text or None,
            "descargas": downloads,
            "errores_descarga": "; ".join(errors) if errors else None,
            "descarga_esperada": descarga_ventas or descarga_compras,
        }
