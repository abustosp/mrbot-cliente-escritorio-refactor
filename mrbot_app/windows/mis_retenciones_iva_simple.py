import calendar
import json
import os
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, ttk

from mrbot_app.helpers import build_headers, ensure_trailing_slash, format_date_str, safe_post
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.mixins import DownloadHandlerMixin


IVA_SIMPLE_OPERACIONES = (
    "RETENCIONES IMPOSITIVAS",
    "PERCEPCIONES IMPOSITIVAS",
    "PERCEPCIONES ADUANERAS",
)


def iva_simple_max_hasta(desde: str) -> Optional[date]:
    try:
        value = datetime.strptime(format_date_str(desde), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def validate_iva_simple_date_range(desde: str, hasta: str) -> Optional[str]:
    max_hasta = iva_simple_max_hasta(desde)
    try:
        desde_date = datetime.strptime(format_date_str(desde), "%d/%m/%Y").date()
        hasta_date = datetime.strptime(format_date_str(hasta), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return "Las fechas deben tener formato DD/MM/AAAA."
    if hasta_date < desde_date:
        return "La fecha Hasta no puede ser anterior a Desde."
    if max_hasta and hasta_date > max_hasta:
        return f"Para IVA Simple, Hasta no puede superar {max_hasta.strftime('%d/%m/%Y')}."
    return None


class MisRetencionesIvaSimpleWindow(BaseWindow, DownloadHandlerMixin):
    MODULE_DIR = "Mis_Retenciones_IVA_Simple"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Mis Retenciones IVA Simple", config_provider=config_provider)
        DownloadHandlerMixin.__init__(self)
        self.example_paths = example_paths or {}
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Mis Retenciones IVA Simple")
        self.add_info_label(
            container,
            "Descarga las tres operaciones de ARCA en formato IVA Simple y XLS. "
            "Hasta no puede superar el último día del mes siguiente a Desde.",
        )

        inputs = ttk.Frame(container)
        inputs.pack(fill="x", pady=4)
        fields = (
            ("CUIT representante", "cuit_representante", False),
            ("Clave representante", "clave_representante", True),
            ("CUIT representado (opcional)", "cuit_representado", False),
            ("Denominación", "denominacion", False),
            ("Fecha desde (DD/MM/AAAA)", "desde", False),
            ("Fecha hasta (DD/MM/AAAA)", "hasta", False),
        )
        self._vars: Dict[str, tk.StringVar] = {}
        for row, (label, name, secret) in enumerate(fields):
            ttk.Label(inputs, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=2)
            variable = tk.StringVar()
            self._vars[name] = variable
            ttk.Entry(inputs, textvariable=variable, width=30, show="*" if secret else "").grid(
                row=row, column=1, padx=4, pady=2, sticky="ew"
            )
        inputs.columnconfigure(1, weight=1)

        opts = ttk.Frame(container)
        opts.pack(fill="x", pady=2)
        self.proxy_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="proxy_request", variable=self.proxy_var).pack(side="left", padx=4)

        self.add_download_path_frame(container)
        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=4)
        ttk.Button(buttons, text="Consultar", command=self.consulta_individual).pack(side="left", padx=4)

        self.result_box = self.add_preview(container, height=14)
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=12, service="mis_retenciones_iva_simple")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _value(self, name: str) -> str:
        return self._vars[name].get().strip()

    def consulta_individual(self) -> None:
        desde = format_date_str(self._value("desde"))
        hasta = format_date_str(self._value("hasta"))
        date_error = validate_iva_simple_date_range(desde, hasta)
        if date_error:
            messagebox.showerror("Rango inválido", date_error)
            return

        base_url, api_key, email = self._get_config()
        payload = {
            "cuit_representante": self._value("cuit_representante"),
            "clave_representante": self._vars["clave_representante"].get(),
            "cuit_representado": self._value("cuit_representado") or None,
            "denominacion": self._value("denominacion"),
            "desde": desde,
            "hasta": hasta,
            "carga_minio": True,
            "proxy_request": bool(self.proxy_var.get()),
        }
        url = ensure_trailing_slash(base_url) + "api/v1/mis_retenciones_iva_simple/consulta"
        headers = build_headers(api_key, email)
        self.clear_logs()
        self.run_in_thread(
            self.run_with_log_block,
            payload["cuit_representado"] or payload["cuit_representante"] or "sin_cuit",
            self._worker_individual,
            url,
            headers,
            payload,
        )

    def _worker_individual(self, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> None:
        safe_payload = dict(payload)
        safe_payload["clave_representante"] = "***"
        self.log_start("Mis Retenciones IVA Simple", {"modo": "individual", "operaciones": list(IVA_SIMPLE_OPERACIONES)})
        self.log_separator(payload.get("cuit_representado") or payload.get("cuit_representante"))
        self.log_request_started(safe_payload)
        response = safe_post(url, headers, payload)
        data = response.get("data", {}) if isinstance(response, dict) else {}
        self.log_response_finished(response.get("http_status") if isinstance(response, dict) else None, data)
        cuit_folder = payload.get("cuit_representado") or payload.get("cuit_representante") or "sin_cuit"
        downloads, errors, download_dir = self._process_downloads(
            data, self.MODULE_DIR, cuit_folder, service_key="retencion"
        )
        if downloads:
            self.log_info(f"Descargas completadas: {downloads} -> {download_dir}")
        elif data:
            self.log_info("Sin links de descarga en la respuesta.")
        for error in errors:
            self.log_error(f"Descarga: {error}")
        self.set_preview(self.result_box, json.dumps(response, indent=2, ensure_ascii=False))


__all__ = ["IVA_SIMPLE_OPERACIONES", "MisRetencionesIvaSimpleWindow", "iva_simple_max_hasta", "validate_iva_simple_date_range"]
