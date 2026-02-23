import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mrbot_app.procesar_pem import discover_pem_files, process_single_pem
from mrbot_app.windows.base import BaseWindow


class ProcesarPemWindow(BaseWindow):
    """
    Ventana para convertir archivos .pem usando /api/v1/procesar-pem/convertir
    y guardar salida JSON/XML/XLSX en una carpeta 'procesado-pem'.
    """

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Conversión PEM de Controladores Fiscales", config_provider=config_provider)
        self.geometry("1120x760")
        self.resizable(True, True)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass

        self.example_paths = example_paths or {}
        self.folder_var = tk.StringVar()
        self.subfolders_var = tk.BooleanVar(value=True)

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.add_section_label(container, "Conversión PEM a JSON/XML/XLSX")
        self.add_info_label(
            container,
            "Procesa todos los archivos .pem de una carpeta usando el endpoint "
            "/api/v1/procesar-pem/convertir y guarda la salida en un subdirectorio "
            "'procesado-pem' dentro de la carpeta de cada archivo.",
        )

        folder_frame = ttk.LabelFrame(container, text="Carpeta de entrada")
        folder_frame.pack(fill="x", pady=(6, 4))

        ttk.Label(folder_frame, text="Carpeta").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        ttk.Entry(folder_frame, textvariable=self.folder_var, width=90).grid(
            row=0, column=1, padx=4, pady=4, sticky="ew"
        )
        ttk.Button(folder_frame, text="Seleccionar...", command=self.select_folder).grid(
            row=0, column=2, padx=4, pady=4, sticky="ew"
        )
        ttk.Checkbutton(
            folder_frame,
            text="Procesar subcarpetas",
            variable=self.subfolders_var,
        ).grid(row=1, column=0, columnspan=3, padx=4, pady=(0, 6), sticky="w")
        folder_frame.columnconfigure(1, weight=1)

        actions_frame = ttk.Frame(container)
        actions_frame.pack(fill="x", pady=(2, 6))
        ttk.Button(actions_frame, text="Procesar archivos .pem", command=self.process_folder).pack(fill="x")

        self.result_box = self.add_preview(container, height=14)
        self.set_preview(
            self.result_box,
            "Selecciona una carpeta y presiona 'Procesar archivos .pem'.\n"
            "Se crearán archivos .json, .xml y .xlsx en subcarpetas 'procesado-pem'.",
        )

        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(
            container,
            title="Logs de ejecución",
            height=12,
            service="procesar_pem",
        )

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def select_folder(self) -> None:
        folder = filedialog.askdirectory()
        self.bring_to_front()
        if folder:
            self.folder_var.set(folder)

    def process_folder(self) -> None:
        folder = self.folder_var.get().strip()
        include_subdirs = bool(self.subfolders_var.get())

        if not folder:
            messagebox.showwarning("Carpeta requerida", "Selecciona una carpeta para procesar archivos .pem.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Carpeta inválida", "La carpeta indicada no existe o no es accesible.")
            return

        base_url, api_key, email = self._get_config()
        self.clear_logs()
        self.log_start(
            "Procesar PEM",
            {
                "carpeta": folder,
                "subcarpetas": include_subdirs,
                "base_url": base_url,
            },
        )
        self.run_in_thread(self._worker_process_folder, folder, include_subdirs, base_url, api_key, email)

    def _worker_process_folder(self, folder: str, include_subdirs: bool, base_url: str, api_key: str, email: str) -> None:
        pem_files = discover_pem_files(folder, include_subdirs=include_subdirs)
        total = len(pem_files)
        self.set_progress(0, total)

        if total == 0:
            self.log_error("No se encontraron archivos .pem en la carpeta indicada.")
            self.set_preview(
                self.result_box,
                "No se encontraron archivos .pem.\n"
                "Verifica la carpeta seleccionada o activa 'Procesar subcarpetas'.",
            )
            return

        self.log_info(f"Archivos PEM encontrados: {total}")

        processed_count = 0
        success_count = 0
        error_count = 0
        output_dirs: set[str] = set()
        errors: List[str] = []

        for index, pem_path in enumerate(pem_files, start=1):
            if self._abort_event.is_set():
                break

            result = self.run_with_log_block(
                pem_path.name,
                self._process_single_file,
                pem_path,
                base_url,
                api_key,
                email,
            )
            processed_count += 1

            if isinstance(result, dict) and result.get("success"):
                success_count += 1
                outputs = result.get("outputs", {})
                xlsx_path = outputs.get("xlsx")
                if xlsx_path:
                    output_dirs.add(str(Path(xlsx_path).parent))
            else:
                error_count += 1
                error_text = "Error no especificado"
                if isinstance(result, dict):
                    error_text = str(result.get("error") or error_text)
                errors.append(f"{pem_path.name}: {error_text}")

            self.set_progress(index, total)

        summary_lines = [
            f"Carpeta: {folder}",
            f"Subcarpetas: {'SI' if include_subdirs else 'NO'}",
            f"Archivos detectados: {total}",
            f"Archivos procesados: {processed_count}",
            f"Exitosos: {success_count}",
            f"Con error: {error_count}",
        ]

        if output_dirs:
            summary_lines.append("")
            summary_lines.append("Directorios de salida:")
            for out_dir in sorted(output_dirs):
                summary_lines.append(out_dir)

        if errors:
            summary_lines.append("")
            summary_lines.append("Errores:")
            summary_lines.extend(errors[:25])
            if len(errors) > 25:
                summary_lines.append(f"... {len(errors) - 25} error(es) adicional(es).")

        summary_text = "\n".join(summary_lines)
        self.set_preview(self.result_box, summary_text)

        if self._abort_event.is_set():
            self.log_info(f"Proceso abortado. Procesados {processed_count}/{total}.")
            return

        self.log_info(
            f"Proceso finalizado. Total: {total}, exitosos: {success_count}, con error: {error_count}."
        )

    def _process_single_file(self, pem_path: Path, base_url: str, api_key: str, email: str) -> Dict[str, Any]:
        self.log_info(f"Procesando archivo: {pem_path}")
        result = process_single_pem(
            pem_path,
            base_url=base_url,
            api_key=api_key,
            email=email,
        )

        if result.get("success"):
            outputs = result.get("outputs", {})
            self.log_info(f"JSON: {outputs.get('json')}")
            self.log_info(f"XML: {outputs.get('xml')}")
            self.log_info(f"XLSX: {outputs.get('xlsx')}")
        else:
            self.log_error(str(result.get("error") or "Error no especificado"))

        return result
