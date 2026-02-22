import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mrbot_app.bcra import (
    BCRA_BASE_URL,
    BCRA_OPERATIONS,
    extract_bcra_error_messages,
    flatten_bcra_results,
    get_bcra_operation_choices,
    get_example_excel_name_for_operation,
    run_bcra_operation,
)
from mrbot_app.files import open_with_default_app
from mrbot_app.formatos import agregar_filtros, aplicar_formato_encabezado, autoajustar_columnas
from mrbot_app.helpers import df_preview, parse_bool_cell
from mrbot_app.windows.base import BaseWindow


PARAM_LABELS: Dict[str, str] = {
    "identificacion": "Identificacion",
    "codigo_entidad": "Codigo entidad",
    "numero_cheque": "Numero de cheque",
    "cod_moneda": "Codigo moneda",
    "fecha": "Fecha (AAAA-MM-DD)",
    "fecha_desde": "Fecha desde",
    "fecha_hasta": "Fecha hasta",
    "id_variable": "ID variable",
    "categoria": "Categoria",
    "periodicidad": "Periodicidad",
    "moneda": "Moneda",
    "tipo_serie": "Tipo serie",
    "unidad_expresion": "Unidad expresion",
    "desde": "Desde",
    "hasta": "Hasta",
    "limit": "Limit",
    "offset": "Offset",
}

PARAM_ORDER = [
    "identificacion",
    "codigo_entidad",
    "numero_cheque",
    "cod_moneda",
    "fecha",
    "fecha_desde",
    "fecha_hasta",
    "id_variable",
    "categoria",
    "periodicidad",
    "moneda",
    "tipo_serie",
    "unidad_expresion",
    "desde",
    "hasta",
    "limit",
    "offset",
]

SECTION_DESCRIPTIONS: Dict[str, str] = {
    "Central de Deudores": (
        "El servicio permite obtener un informe consolidado por clave de identificación fiscal "
        "(CUIT, CUIL o CDI) para una persona humana o jurídica respecto de financiaciones "
        "otorgadas por entidades financieras, fideicomisos financieros, entidades no financieras "
        "emisoras de tarjetas de crédito / compra, otros proveedores no financieros de créditos, "
        "sociedades de garantía recíproca, fondos de garantía de carácter público y proveedores "
        "de servicios de crédito entre particulares a través de plataformas."
    ),
    "Cheques Denunciados": (
        "Podrás consultar cheques denunciados, extraviados, sustraídos o adulterados. "
        "La información disponible aquí es suministrada por las entidades financieras que "
        "operan en el país y se publica sin alteraciones."
    ),
    "Estadisticas Cambiarias": (
        "La API de Estadísticas Cambiarias proporciona acceso a recursos relacionados con "
        "la información de los tipos de cambio publicados por el BCRA."
    ),
    "Estadisticas Monetarias": (
        "La API de Estadísticas monetarias proporciona acceso a recursos relacionados con "
        "la información de Series.xlsm y principales variables publicadas por el BCRA."
    ),
}

CENTRAL_DEUDORES_OPS = [
    "central_deudores_deudas",
    "central_deudores_historicas",
    "central_deudores_cheques_rechazados",
]

CENTRAL_SHEET_NAMES = {
    "central_deudores_deudas": "Deudas",
    "central_deudores_historicas": "Historicas",
    "central_deudores_cheques_rechazados": "ChequesRechazados",
}


class BcraWindow(BaseWindow):
    def __init__(self, master=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Consultas BCRA")
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass

        self.example_paths = example_paths or {}
        self.bcra_df: Optional[pd.DataFrame] = None

        operation_choices = get_bcra_operation_choices()
        self._label_to_id = {label: op_id for op_id, label in operation_choices}
        self._id_to_label = {op_id: label for op_id, label in operation_choices}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.add_section_label(container, "Consultas BCRA")
        self.add_info_label(
            container,
            "Consultas directas a https://api.bcra.gob.ar para Central de Deudores, Cheques Denunciados, "
            "Estadisticas Cambiarias y Estadisticas Monetarias.",
        )

        base_frame = ttk.Frame(container)
        base_frame.pack(fill="x", pady=4)
        ttk.Label(base_frame, text="Base URL BCRA").grid(row=0, column=0, padx=4, pady=2, sticky="w")
        self.base_url_var = tk.StringVar(value=BCRA_BASE_URL)
        ttk.Entry(base_frame, textvariable=self.base_url_var, width=52).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(base_frame, text="Restaurar", command=lambda: self.base_url_var.set(BCRA_BASE_URL)).grid(
            row=0, column=2, padx=4, pady=2, sticky="ew"
        )
        base_frame.columnconfigure(1, weight=1)

        op_frame = ttk.Frame(container)
        op_frame.pack(fill="x", pady=4)
        ttk.Label(op_frame, text="Operacion").grid(row=0, column=0, padx=4, pady=2, sticky="w")
        self.operation_var = tk.StringVar(value=operation_choices[0][1])
        self.operation_combo = ttk.Combobox(
            op_frame,
            textvariable=self.operation_var,
            values=[label for _, label in operation_choices],
            state="readonly",
            width=65,
        )
        self.operation_combo.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        self.operation_combo.bind("<<ComboboxSelected>>", self._on_operation_changed)
        op_frame.columnconfigure(1, weight=1)

        self.requirements_var = tk.StringVar(value="")
        ttk.Label(op_frame, textvariable=self.requirements_var, wraplength=760, justify="left").grid(
            row=1, column=0, columnspan=2, padx=4, pady=(0, 2), sticky="w"
        )
        self.section_description_var = tk.StringVar(value="")
        ttk.Label(
            op_frame,
            textvariable=self.section_description_var,
            wraplength=760,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, padx=4, pady=(0, 2), sticky="w")

        params_frame = ttk.LabelFrame(container, text="Parametros")
        params_frame.pack(fill="x", pady=(4, 2))
        self.params_frame = params_frame

        self.param_vars: Dict[str, tk.StringVar] = {}
        self.param_widgets: Dict[str, tuple[ttk.Label, ttk.Entry]] = {}
        self.required_param_fields: List[str] = []
        self.optional_param_fields: List[str] = []
        self.active_param_fields: List[str] = []
        for idx, field in enumerate(PARAM_ORDER):
            var = tk.StringVar()
            self.param_vars[field] = var
            label = ttk.Label(params_frame, text=PARAM_LABELS[field])
            entry = ttk.Entry(params_frame, textvariable=var, width=34)
            self.param_widgets[field] = (label, entry)

        optional_toggle_frame = ttk.Frame(params_frame)
        optional_toggle_frame.grid(row=0, column=0, columnspan=4, padx=4, pady=(2, 2), sticky="w")
        self.show_optional_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            optional_toggle_frame,
            text="Mostrar parámetros opcionales",
            variable=self.show_optional_var,
            command=self._render_param_inputs,
        ).pack(anchor="w")

        self.no_params_label = ttk.Label(
            params_frame,
            text="Este endpoint no requiere parametros para consulta individual.",
        )

        params_frame.columnconfigure(1, weight=1)
        params_frame.columnconfigure(3, weight=1)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="Consultar individual", command=self.consulta_individual).grid(
            row=0, column=0, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(btns, text="Seleccionar Excel", command=self.cargar_excel).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Ejemplo Excel", command=self.abrir_ejemplo).grid(row=0, column=2, padx=4, pady=2, sticky="ew")
        ttk.Button(
            btns,
            text="Previsualizar Excel",
            command=self.previsualizar_excel,
        ).grid(row=0, column=3, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Procesar Excel", command=self.procesar_excel).grid(row=0, column=4, padx=4, pady=2, sticky="ew")
        ttk.Button(btns, text="Limpiar parametros", command=self.limpiar_parametros).grid(row=0, column=5, padx=4, pady=2, sticky="ew")
        btns.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self.preview = self.add_preview(container, height=8)
        self.result_box = self.add_preview(container, height=14)
        self.set_preview(self.preview, "Vista previa del Excel (filas con procesar=SI).")

        self.progress_frame = self.add_progress_bar(container, label="Progreso")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=12, service="bcra")
        self._on_operation_changed()

    def _selected_operation(self) -> str:
        label = self.operation_var.get().strip()
        return self._label_to_id.get(label, "")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _normalize_operation_from_row(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text in BCRA_OPERATIONS:
            return text

        lowered = text.lower()
        for op_id, label in self._id_to_label.items():
            if lowered == label.lower():
                return op_id
        return None

    def _on_operation_changed(self, *_args: Any) -> None:
        operation = self._selected_operation()
        spec = BCRA_OPERATIONS.get(operation, {})
        required = list(spec.get("required") or [])
        optional = list(spec.get("optional") or [])
        self.show_optional_var.set(False)
        self.required_param_fields = required
        self.optional_param_fields = optional
        required_txt = ", ".join(self.required_param_fields) if self.required_param_fields else "ninguno"
        optional_txt = ", ".join(self.optional_param_fields) if self.optional_param_fields else "ninguno"
        self.requirements_var.set(f"Requeridos: {required_txt} | Opcionales: {optional_txt}")
        group = str(spec.get("group", "")).strip()
        group_description = SECTION_DESCRIPTIONS.get(group, "")
        if group_description:
            self.section_description_var.set(f"{group}: {group_description}")
        else:
            self.section_description_var.set("")
        self._render_param_inputs()

    def _render_param_inputs(self) -> None:
        for label, entry in self.param_widgets.values():
            label.grid_forget()
            entry.grid_forget()
        self.no_params_label.grid_forget()

        active = list(self.required_param_fields)
        if self.show_optional_var.get():
            active = list(dict.fromkeys(active + self.optional_param_fields))
        self.active_param_fields = active

        if not self.active_param_fields:
            self.no_params_label.grid(row=1, column=0, columnspan=4, padx=4, pady=4, sticky="w")
            return

        for idx, field in enumerate(self.active_param_fields):
            row = (idx // 2) + 1
            col = (idx % 2) * 2
            label, entry = self.param_widgets[field]
            label.grid(row=row, column=col, padx=4, pady=2, sticky="w")
            entry.grid(row=row, column=col + 1, padx=4, pady=2, sticky="ew")

    def _is_central_operation(self, operation: str) -> bool:
        spec = BCRA_OPERATIONS.get(operation, {})
        return str(spec.get("group", "")).strip() == "Central de Deudores"

    def _sanitize_identifier(self, value: Any) -> str:
        text = str(value or "").strip()
        clean = re.sub(r"[^0-9A-Za-z._-]", "_", text).strip("_")
        return clean or "desconocido"

    def _central_root_dir(self) -> str:
        return os.path.join("descargas", "bcra", "central_de_deudores")

    def _extract_identificacion_from_row(self, row: pd.Series) -> str:
        for key in ("identificacion", "cuit", "cuil", "cdi"):
            value = str(row.get(key, "")).strip()
            if value:
                return value
        return ""

    def _run_central_queries(self, identificacion: str, base_url: str) -> Dict[str, Dict[str, Any]]:
        query_results: Dict[str, Dict[str, Any]] = {}
        self.log_info(f"Consultando Central de Deudores para identificacion={identificacion}")
        for operation in CENTRAL_DEUDORES_OPS:
            try:
                self.log_info(f"Operacion: {operation}")
                response = self._run_operation_logged(
                    operation=operation,
                    params={"identificacion": identificacion},
                    base_url=base_url,
                )
                data = response.get("data", {})
                flattened = flatten_bcra_results(operation, data)
                errors = extract_bcra_error_messages(data)
                query_results[operation] = {
                    "response": response,
                    "data": data if isinstance(data, dict) else {},
                    "flattened": flattened,
                    "error": "; ".join(errors) if errors else None,
                }
            except Exception as exc:
                self.log_error(f"Error en {operation}: {exc}")
                query_results[operation] = {
                    "response": {"http_status": None, "data": {"status": None}},
                    "data": {"status": None},
                    "flattened": [],
                    "error": str(exc),
                }
        return query_results

    def _build_central_summary_rows(
        self,
        identificacion: str,
        query_results: Dict[str, Dict[str, Any]],
        row_number: Optional[int],
        report_path: Optional[str],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for operation in CENTRAL_DEUDORES_OPS:
            result = query_results.get(operation, {})
            response = result.get("response", {}) if isinstance(result, dict) else {}
            data = result.get("data", {}) if isinstance(result, dict) else {}
            flattened = result.get("flattened", []) if isinstance(result, dict) else []
            row: Dict[str, Any] = {
                "fila": row_number,
                "identificacion": identificacion,
                "operacion": operation,
                "http_status": response.get("http_status") if isinstance(response, dict) else None,
                "status": data.get("status") if isinstance(data, dict) else None,
                "registros": len(flattened) if isinstance(flattened, list) else 0,
                "error": result.get("error") if isinstance(result, dict) else None,
                "reporte_individual": report_path,
            }
            rows.append(row)
        return rows

    def _build_central_detail_rows(
        self,
        identificacion: str,
        query_results: Dict[str, Dict[str, Any]],
        row_number: Optional[int],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for operation in CENTRAL_DEUDORES_OPS:
            result = query_results.get(operation, {})
            flattened = result.get("flattened", []) if isinstance(result, dict) else []
            if not isinstance(flattened, list) or not flattened:
                continue
            for item in flattened:
                row: Dict[str, Any] = {
                    "fila": row_number,
                    "identificacion": identificacion,
                    "operacion": operation,
                }
                if isinstance(item, dict):
                    row.update(item)
                rows.append(row)
        return rows

    def _format_excel_writer(self, writer: pd.ExcelWriter) -> None:
        for sheet in writer.sheets.values():
            try:
                aplicar_formato_encabezado(sheet)
                agregar_filtros(sheet)
                autoajustar_columnas(sheet)
            except Exception:
                continue

    def _write_central_individual_report(
        self,
        identificacion: str,
        query_results: Dict[str, Dict[str, Any]],
    ) -> Tuple[str, pd.DataFrame, pd.DataFrame]:
        cuit_dir = os.path.join(self._central_root_dir(), self._sanitize_identifier(identificacion))
        os.makedirs(cuit_dir, exist_ok=True)
        report_name = f"reporte_central_de_deudores_{self._sanitize_identifier(identificacion)}.xlsx"
        report_path = os.path.join(cuit_dir, report_name)

        summary_df = pd.DataFrame(
            self._build_central_summary_rows(
                identificacion=identificacion,
                query_results=query_results,
                row_number=None,
                report_path=report_path,
            )
        )
        detail_rows = self._build_central_detail_rows(
            identificacion=identificacion,
            query_results=query_results,
            row_number=None,
        )
        detail_df = pd.DataFrame(detail_rows)
        if detail_df.empty:
            detail_df = pd.DataFrame(columns=["identificacion", "operacion"])

        json_rows: List[Dict[str, Any]] = []
        for operation in CENTRAL_DEUDORES_OPS:
            result = query_results.get(operation, {})
            response = result.get("response", {}) if isinstance(result, dict) else {}
            data = response.get("data", {}) if isinstance(response, dict) else {}
            json_rows.append(
                {
                    "identificacion": identificacion,
                    "operacion": operation,
                    "http_status": response.get("http_status") if isinstance(response, dict) else None,
                    "response_json": json.dumps(data, ensure_ascii=False, default=str),
                }
            )
        json_df = pd.DataFrame(json_rows)

        with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, index=False, sheet_name="Resumen")
            detail_df.to_excel(writer, index=False, sheet_name="Consolidado")
            for operation in CENTRAL_DEUDORES_OPS:
                op_rows = query_results.get(operation, {}).get("flattened", [])
                op_df = pd.DataFrame(op_rows) if isinstance(op_rows, list) else pd.DataFrame()
                if op_df.empty:
                    op_df = pd.DataFrame(columns=["sin_datos"])
                sheet_name = CENTRAL_SHEET_NAMES.get(operation, operation)[:31]
                op_df.to_excel(writer, index=False, sheet_name=sheet_name)
            json_df.to_excel(writer, index=False, sheet_name="JSON")
            self._format_excel_writer(writer)

        return report_path, summary_df, detail_df

    def _write_central_consolidated_report(self, summary_df: pd.DataFrame, detail_df: pd.DataFrame) -> str:
        root_dir = self._central_root_dir()
        os.makedirs(root_dir, exist_ok=True)
        report_path = os.path.join(root_dir, "reporte_consolidado_central_de_deudores.xlsx")

        if summary_df.empty:
            summary_df = pd.DataFrame(columns=["identificacion", "operacion", "http_status", "status", "registros", "error"])
        if detail_df.empty:
            detail_df = pd.DataFrame(columns=["identificacion", "operacion"])

        with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, index=False, sheet_name="Resumen")
            detail_df.to_excel(writer, index=False, sheet_name="Consolidado")
            for operation in CENTRAL_DEUDORES_OPS:
                if "operacion" in detail_df.columns:
                    op_df = detail_df[detail_df["operacion"] == operation].copy()
                else:
                    op_df = pd.DataFrame()
                if op_df.empty:
                    op_df = pd.DataFrame(columns=["sin_datos"])
                sheet_name = CENTRAL_SHEET_NAMES.get(operation, operation)[:31]
                op_df.to_excel(writer, index=False, sheet_name=sheet_name)
            self._format_excel_writer(writer)

        return report_path

    def _procesar_excel_central_deudores(self, df: pd.DataFrame, base_url: str) -> None:
        total = len(df)
        self.set_progress(0, total)

        summary_rows: List[Dict[str, Any]] = []
        detail_rows: List[Dict[str, Any]] = []

        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            if self._abort_event.is_set():
                break
            identificacion = self._extract_identificacion_from_row(row)
            with self.log_block(identificacion or f"fila_{idx}"):
                if not identificacion:
                    self.log_error("Falta identificacion (columnas esperadas: identificacion/cuit/cuil/cdi).")
                    summary_rows.append(
                        {
                            "fila": idx,
                            "identificacion": None,
                            "operacion": "central_deudores",
                            "http_status": None,
                            "status": None,
                            "registros": 0,
                            "error": "Falta identificacion (columnas esperadas: identificacion/cuit/cuil/cdi).",
                            "reporte_individual": None,
                        }
                    )
                    self.set_progress(idx, total)
                    continue

                query_results = self._run_central_queries(identificacion, base_url)
                report_path: Optional[str] = None
                try:
                    report_path, _, _ = self._write_central_individual_report(identificacion, query_results)
                    self.log_info(f"Reporte individual generado: {report_path}")
                except Exception as exc:
                    self.log_error(f"No se pudo guardar reporte individual: {exc}")
                    summary_rows.append(
                        {
                            "fila": idx,
                            "identificacion": identificacion,
                            "operacion": "reporte_individual",
                            "http_status": None,
                            "status": None,
                            "registros": 0,
                            "error": f"No se pudo guardar reporte individual: {exc}",
                            "reporte_individual": None,
                        }
                    )

                summary_rows.extend(
                    self._build_central_summary_rows(
                        identificacion=identificacion,
                        query_results=query_results,
                        row_number=idx,
                        report_path=report_path,
                    )
                )
                detail_rows.extend(
                    self._build_central_detail_rows(
                        identificacion=identificacion,
                        query_results=query_results,
                        row_number=idx,
                    )
                )
            self.set_progress(idx, total)

        summary_df = pd.DataFrame(summary_rows)
        detail_df = pd.DataFrame(detail_rows)

        consolidated_path: Optional[str] = None
        try:
            consolidated_path = self._write_central_consolidated_report(summary_df, detail_df)
            self.log_info(f"Reporte consolidado generado: {consolidated_path}")
        except Exception as exc:
            self.log_error(f"No se pudo guardar el reporte consolidado: {exc}")

        parts: List[str] = []
        if consolidated_path:
            parts.append(f"Reporte consolidado generado: {consolidated_path}")
        if not summary_df.empty:
            parts.append("\nResumen de procesamiento:")
            parts.append(df_preview(summary_df, rows=len(summary_df)))
        if not detail_df.empty:
            parts.append("\nDetalle tabular (todas las filas):")
            parts.append(df_preview(detail_df, rows=len(detail_df)))
        self.set_preview(self.result_box, "\n".join(parts) if parts else "Sin datos para mostrar.")

    def limpiar_parametros(self) -> None:
        for var in self.param_vars.values():
            var.set("")

    def _collect_params_from_form(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for key in self.active_param_fields:
            var = self.param_vars[key]
            value = var.get().strip()
            if value:
                params[key] = value
        return params

    def _run_operation_logged(self, operation: str, params: Dict[str, Any], base_url: str) -> Dict[str, Any]:
        request_payload = {
            "operation": operation,
            "params": params,
            "base_url": base_url,
        }
        self.log_request_started(request_payload, label="REQUEST BCRA")
        response = run_bcra_operation(
            operation=operation,
            params=params,
            base_url=base_url,
        )
        self.log_response_finished(response.get("http_status"), response.get("data"))
        if response.get("date_adjustment_warning"):
            self.log_info(str(response.get("date_adjustment_warning")))
        if response.get("lookup_ssl_warning"):
            self.log_info(str(response.get("lookup_ssl_warning")))
        data = response.get("data")
        errors = extract_bcra_error_messages(data)
        if errors:
            self.log_error("; ".join(errors))
        return response

    def _extract_result_text(self, response: Dict[str, Any]) -> str:
        data = response.get("data")
        operation = response.get("operation", "")
        flattened = flatten_bcra_results(operation, data)
        parts: List[str] = []

        if response.get("date_adjustment_warning"):
            parts.append(f"Ajuste de fecha: {response['date_adjustment_warning']}")

        parts.append(json.dumps(response, indent=2, ensure_ascii=False, default=str))

        if flattened:
            df = pd.DataFrame(flattened)
            parts.append("\nDetalle tabular (todas las filas):")
            parts.append(df_preview(df, rows=len(df)))

        return "\n\n".join(parts)

    def _read_excel(self, filename: str) -> pd.DataFrame:
        df = pd.read_excel(filename, dtype=str).fillna("")
        df.columns = [str(c).strip().lower() for c in df.columns]
        return df

    def abrir_ejemplo(self) -> None:
        operation = self._selected_operation()
        filename = get_example_excel_name_for_operation(operation)
        if not filename:
            messagebox.showerror("Error", "No se encontro Excel de ejemplo para la operacion seleccionada.")
            return

        path = self.example_paths.get(filename)
        if not path:
            messagebox.showerror("Error", f"No se encontro el Excel de ejemplo: {filename}")
            return

        if not open_with_default_app(path):
            messagebox.showerror("Error", "No se pudo abrir el Excel de ejemplo.")

    def cargar_excel(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        self.bring_to_front()
        if not filename:
            return
        try:
            self.bcra_df = self._read_excel(filename)
            self._refresh_excel_preview()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo leer el Excel: {exc}")
            self.bcra_df = None

    def previsualizar_excel(self) -> None:
        if self.bcra_df is None or self.bcra_df.empty:
            messagebox.showwarning("Aviso", "No hay Excel cargado.")
            return
        rows_to_process = self._rows_to_process(self.bcra_df)
        if rows_to_process.empty:
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return
        self.open_df_preview(rows_to_process, "Previsualizacion BCRA", max_rows=len(rows_to_process))

    def _refresh_excel_preview(self) -> None:
        if self.bcra_df is None or self.bcra_df.empty:
            self.set_preview(self.preview, "Vista previa del Excel (filas con procesar=SI).")
            return
        rows_to_process = self._rows_to_process(self.bcra_df)
        if rows_to_process.empty:
            self.set_preview(self.preview, "No hay filas marcadas con procesar=SI.")
            return
        self.set_preview(self.preview, df_preview(rows_to_process, rows=len(rows_to_process)))

    def consulta_individual(self) -> None:
        operation = self._selected_operation()
        if not operation:
            messagebox.showerror("Error", "Selecciona una operacion valida.")
            return

        params = self._collect_params_from_form()
        base_url = self.base_url_var.get().strip() or BCRA_BASE_URL

        if self._is_central_operation(operation):
            identificacion = str(params.get("identificacion", "")).strip()
            if not identificacion:
                messagebox.showerror("Error", "Para Central de Deudores debes ingresar 'identificacion'.")
                return
            block_label = identificacion
        else:
            block_label = operation

        self.clear_logs()
        self.log_start("BCRA", {"modo": "individual", "operacion": operation})
        self.run_in_thread(
            self.run_with_log_block,
            block_label,
            self._worker_consulta_individual,
            operation,
            params,
            base_url,
        )

    def _worker_consulta_individual(self, operation: str, params: Dict[str, Any], base_url: str) -> None:
        if self._is_central_operation(operation):
            identificacion = str(params.get("identificacion", "")).strip()
            query_results = self._run_central_queries(identificacion, base_url)
            try:
                report_path, summary_df, detail_df = self._write_central_individual_report(identificacion, query_results)
                self.log_info(f"Reporte individual generado: {report_path}")
            except Exception as exc:
                self.log_error(f"No se pudo generar el reporte individual: {exc}")
                self.set_preview(self.result_box, f"No se pudo generar el reporte individual: {exc}")
                return

            parts = [
                f"Reporte individual generado: {report_path}",
                "\nResumen de endpoints:",
                df_preview(summary_df, rows=len(summary_df)),
            ]
            if not detail_df.empty:
                parts.append("\nDetalle tabular (todas las filas):")
                parts.append(df_preview(detail_df, rows=len(detail_df)))
            self.set_preview(self.result_box, "\n".join(parts))
            return

        try:
            response = self._run_operation_logged(
                operation=operation,
                params=params,
                base_url=base_url,
            )
        except Exception as exc:
            self.log_error(str(exc))
            self.set_preview(self.result_box, str(exc))
            return

        self.set_preview(self.result_box, self._extract_result_text(response))

    def _rows_to_process(self, df: pd.DataFrame) -> pd.DataFrame:
        if "procesar" not in df.columns:
            return df
        mask = df["procesar"].apply(lambda value: parse_bool_cell(value, default=False))
        return df[mask]

    def _row_params(self, row: pd.Series) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for key in PARAM_ORDER:
            value = str(row.get(key, "")).strip()
            if value:
                params[key] = value
        return params

    def procesar_excel(self) -> None:
        if self.bcra_df is None or self.bcra_df.empty:
            self.set_progress(0, 0)
            messagebox.showerror("Error", "Carga un Excel primero.")
            return

        selected_operation = self._selected_operation()
        if not selected_operation:
            messagebox.showerror("Error", "Selecciona una operacion valida.")
            return

        base_url = self.base_url_var.get().strip() or BCRA_BASE_URL
        df = self._rows_to_process(self.bcra_df)
        if df.empty:
            self.set_progress(0, 0)
            messagebox.showwarning("Sin filas a procesar", "No hay filas marcadas con procesar=SI.")
            return

        df_copy = df.copy()
        self.clear_logs()
        self.log_start(
            "BCRA",
            {"modo": "masivo", "filas": len(df_copy), "operacion": selected_operation},
        )
        self.run_in_thread(self._worker_procesar_excel, df_copy, selected_operation, base_url)

    def _worker_procesar_excel(self, df: pd.DataFrame, selected_operation: str, base_url: str) -> None:
        if self._is_central_operation(selected_operation):
            self._procesar_excel_central_deudores(df, base_url)
            self.log_info("Procesamiento masivo finalizado.")
            return

        summary_rows: List[Dict[str, Any]] = []
        detail_rows: List[Dict[str, Any]] = []

        total = len(df)
        self.set_progress(0, total)

        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            if self._abort_event.is_set():
                break

            row_label = (
                str(row.get("identificacion", "")).strip()
                or str(row.get("cuit", "")).strip()
                or str(row.get("codigo_entidad", "")).strip()
                or str(row.get("id_variable", "")).strip()
                or f"fila_{idx}"
            )

            with self.log_block(row_label):
                operation_value = row.get("consulta", "") or row.get("operacion", "")
                operation = self._normalize_operation_from_row(operation_value)
                if not operation:
                    if str(operation_value).strip():
                        self.log_error(f"Operacion no soportada: {operation_value}")
                        summary_rows.append(
                            {
                                "fila": idx,
                                "operacion": str(operation_value),
                                "http_status": None,
                                "status": None,
                                "registros": 0,
                                "error": f"Operacion no soportada: {operation_value}",
                            }
                        )
                        self.set_progress(idx, total)
                        continue
                    operation = selected_operation

                if operation not in BCRA_OPERATIONS:
                    self.log_error(f"Operacion no soportada: {operation_value}")
                    summary_rows.append(
                        {
                            "fila": idx,
                            "operacion": str(operation_value),
                            "http_status": None,
                            "status": None,
                            "registros": 0,
                            "error": f"Operacion no soportada: {operation_value}",
                        }
                    )
                    self.set_progress(idx, total)
                    continue

                params = self._row_params(row)
                self.log_info(f"Fila {idx} - operacion {operation}")
                try:
                    response = self._run_operation_logged(
                        operation=operation,
                        params=params,
                        base_url=base_url,
                    )
                    data = response.get("data", {})
                    flattened = flatten_bcra_results(operation, data)
                    errors = extract_bcra_error_messages(data)
                    summary_rows.append(
                        {
                            "fila": idx,
                            "operacion": operation,
                            "http_status": response.get("http_status"),
                            "status": data.get("status") if isinstance(data, dict) else None,
                            "registros": len(flattened),
                            "error": "; ".join(errors) if errors else None,
                        }
                    )

                    for detail in flattened:
                        item = {
                            "fila": idx,
                            "operacion": operation,
                        }
                        if isinstance(detail, dict):
                            item.update(detail)
                        detail_rows.append(item)
                except Exception as exc:
                    self.log_error(str(exc))
                    summary_rows.append(
                        {
                            "fila": idx,
                            "operacion": operation,
                            "http_status": None,
                            "status": None,
                            "registros": 0,
                            "error": str(exc),
                        }
                    )

            self.set_progress(idx, total)

        summary_df = pd.DataFrame(summary_rows)
        detail_df = pd.DataFrame(detail_rows)

        parts = ["Resumen de procesamiento:", df_preview(summary_df, rows=min(30, len(summary_df)))]
        if not detail_df.empty:
            parts.append("\nDetalle tabular (todas las filas):")
            parts.append(df_preview(detail_df, rows=len(detail_df)))

        self.set_preview(self.result_box, "\n".join(parts))
        self.log_info("Procesamiento masivo finalizado.")
