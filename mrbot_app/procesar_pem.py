from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from mrbot_app.config import get_request_timeouts
from mrbot_app.helpers import ensure_trailing_slash


def discover_pem_files(folder: str | Path, include_subdirs: bool = False) -> List[Path]:
    base_path = Path(folder)
    if not base_path.exists() or not base_path.is_dir():
        return []

    candidates = base_path.rglob("*") if include_subdirs else base_path.glob("*")
    files = [item for item in candidates if item.is_file() and item.suffix.lower() == ".pem"]
    files.sort(key=lambda item: str(item).lower())
    return files


def _build_headers(api_key: str, email: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key
    if email:
        headers["email"] = email
    return headers


def convertir_pem_api(
    pem_file: str | Path,
    base_url: str,
    api_key: str = "",
    email: str = "",
    timeout_sec: Optional[int] = None,
) -> Dict[str, Any]:
    post_timeout, _ = get_request_timeouts()
    effective_timeout = timeout_sec if timeout_sec is not None else post_timeout
    endpoint = ensure_trailing_slash(base_url) + "api/v1/procesar-pem/convertir"

    pem_path = Path(pem_file)
    headers = _build_headers(api_key, email)

    try:
        with pem_path.open("rb") as file_handler:
            response = requests.post(
                endpoint,
                headers=headers,
                files={"file": (pem_path.name, file_handler, "application/octet-stream")},
                timeout=effective_timeout,
            )

        try:
            data = response.json()
        except Exception:
            data = {"raw_text": response.text}

        return {
            "http_status": response.status_code,
            "data": data,
        }
    except Exception as exc:
        return {
            "http_status": None,
            "data": {"success": False, "message": f"Error de conexion: {exc}"},
        }


def _attributes_to_xml(attrs: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for key, value in attrs.items():
        safe_value = escape("" if value is None else str(value), quote=True)
        chunks.append(f' {key}="{safe_value}"')
    return "".join(chunks)


def _value_to_xml(tag: str, value: Any, level: int = 0) -> str:
    padding = "  " * level

    if isinstance(value, list):
        return "\n".join(_value_to_xml(tag, item, level) for item in value)

    if isinstance(value, dict):
        attrs = value.get("@attributes")
        attrs_dict = attrs if isinstance(attrs, dict) else {}
        text_value = value.get("#text")
        children = [(key, val) for key, val in value.items() if key not in {"@attributes", "#text"}]
        attrs_txt = _attributes_to_xml(attrs_dict)

        if not children and (text_value is None or text_value == ""):
            return f"{padding}<{tag}{attrs_txt}/>"

        lines: List[str] = [f"{padding}<{tag}{attrs_txt}>"]
        if text_value is not None and text_value != "":
            lines.append(f"{padding}  {escape(str(text_value))}")
        for child_key, child_value in children:
            lines.append(_value_to_xml(child_key, child_value, level + 1))
        lines.append(f"{padding}</{tag}>")
        return "\n".join(lines)

    safe_text = "" if value is None else escape(str(value))
    return f"{padding}<{tag}>{safe_text}</{tag}>"


def to_xml_string(data: Any, root_name: str = "datos") -> str:
    if isinstance(data, dict) and len(data) == 1:
        only_key = next(iter(data))
        body = _value_to_xml(str(only_key), data[only_key], 0)
    else:
        body = _value_to_xml(root_name, data, 0)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def flatten_values(data: Any, prefix: str = "") -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []

    if isinstance(data, dict):
        if not data:
            rows.append((prefix, ""))
            return rows
        for key, value in data.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(flatten_values(value, next_prefix))
        return rows

    if isinstance(data, list):
        if not data:
            rows.append((prefix, "[]"))
            return rows
        for index, value in enumerate(data):
            next_prefix = f"{prefix}[{index}]"
            rows.extend(flatten_values(value, next_prefix))
        return rows

    rows.append((prefix, "" if data is None else str(data)))
    return rows


def _sanitize_sheet_name(name: str, used: set[str]) -> str:
    candidate = re.sub(r"[^0-9A-Za-z_]", "_", (name or "").strip())
    candidate = candidate.strip("_") or "tabla"
    candidate = candidate[:31]
    if candidate not in used:
        used.add(candidate)
        return candidate

    base = candidate[:27] if len(candidate) > 27 else candidate
    idx = 2
    while True:
        alt = f"{base}_{idx}"[:31]
        if alt not in used:
            used.add(alt)
            return alt
        idx += 1


def _to_excel_cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _normalize_dict(value: Dict[str, Any]) -> pd.DataFrame:
    try:
        expanded_rows = _expand_record(value)
        if expanded_rows:
            return pd.DataFrame(expanded_rows)
    except Exception:
        pass

    try:
        df = pd.json_normalize(value, sep=".")
        if not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame([{"valor_json": json.dumps(value, ensure_ascii=False)}])


def _expand_record(record: Dict[str, Any], prefix: str = "") -> List[Dict[str, Any]]:
    base: Dict[str, Any] = {}
    dynamic_options: List[List[Dict[str, Any]]] = []

    for key, value in record.items():
        field = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            nested = _expand_record(value, field)
            if nested:
                dynamic_options.append(nested)
            continue
        if isinstance(value, list):
            dynamic_options.append(_expand_list_values(field, value))
            continue
        base[field] = value

    rows = [base]
    for options in dynamic_options:
        next_rows: List[Dict[str, Any]] = []
        for row in rows:
            for option in options:
                merged = dict(row)
                merged.update(option)
                next_rows.append(merged)
        rows = next_rows or rows
    return rows


def _expand_list_values(field: str, values: List[Any]) -> List[Dict[str, Any]]:
    if not values:
        return [{field: None}]

    options: List[Dict[str, Any]] = []
    for value in values:
        if isinstance(value, dict):
            options.extend(_expand_record(value, field))
            continue
        if isinstance(value, list):
            options.append({field: json.dumps(value, ensure_ascii=False)})
            continue
        options.append({field: value})
    return options


def _normalize_list(value: List[Any]) -> pd.DataFrame:
    if not value:
        return pd.DataFrame(columns=["valor"])

    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, dict):
            try:
                expanded_rows = _expand_record(item)
            except Exception:
                expanded_rows = [{"valor_json": json.dumps(item, ensure_ascii=False)}]
            if not expanded_rows:
                expanded_rows = [{}]
            for row in expanded_rows:
                out_row = dict(row)
                out_row["_idx"] = index
                rows.append(out_row)
            continue

        if isinstance(item, list):
            rows.append({"_idx": index, "valor_json": json.dumps(item, ensure_ascii=False)})
            continue

        rows.append({"_idx": index, "valor": item})

    return pd.DataFrame(rows)


def _collect_list_tables(
    data: Any,
    path: str = "root",
    out: Optional[Dict[str, pd.DataFrame]] = None,
    max_tables: int = 60,
) -> Dict[str, pd.DataFrame]:
    tables = out if out is not None else {}

    if isinstance(data, dict):
        for key, value in data.items():
            next_path = f"{path}.{key}" if path else str(key)
            _collect_list_tables(value, next_path, tables, max_tables=max_tables)
        return tables

    if isinstance(data, list):
        if path not in tables:
            if len(tables) >= max_tables:
                return tables
            tables[path] = _normalize_list(data)
        else:
            tables[path] = pd.concat([tables[path], _normalize_list(data)], ignore_index=True)

        for item in data:
            if isinstance(item, dict):
                for key, value in item.items():
                    next_path = f"{path}.{key}"
                    _collect_list_tables(value, next_path, tables, max_tables=max_tables)
            elif isinstance(item, list):
                _collect_list_tables(item, f"{path}[]", tables, max_tables=max_tables)
        return tables

    return tables


def _build_excel_tables(data: Any) -> List[Tuple[str, pd.DataFrame]]:
    output: List[Tuple[str, pd.DataFrame]] = []

    if isinstance(data, dict):
        output.append(("root", _normalize_dict(data)))
    elif isinstance(data, list):
        output.append(("root", _normalize_list(data)))
    else:
        output.append(("root", pd.DataFrame([{"valor": data}])))

    list_tables = _collect_list_tables(data, path="root", max_tables=60)
    seen_paths: set[str] = {"root"}
    for path, df in list_tables.items():
        if path in seen_paths:
            continue
        seen_paths.add(path)
        output.append((path, df))

    flattened = flatten_values(data)
    if flattened:
        output.append(("flatten", pd.DataFrame(flattened, columns=["campo", "valor"])))

    return output


def _extract_error_message(data: Any, http_status: Optional[int]) -> str:
    if isinstance(data, dict):
        for key in ("message", "detail", "error", "raw_text"):
            value = data.get(key)
            if value:
                return f"HTTP {http_status}: {value}" if http_status else str(value)
        return f"HTTP {http_status}: Respuesta sin mensaje de error" if http_status else "Respuesta sin mensaje de error"
    if data:
        return f"HTTP {http_status}: {data}" if http_status else str(data)
    return f"HTTP {http_status}: Error no especificado" if http_status else "Error no especificado"


def build_output_paths(pem_file: str | Path) -> Dict[str, Path]:
    pem_path = Path(pem_file)
    output_dir = pem_path.parent / "procesado-pem"
    stem = pem_path.stem
    return {
        "dir": output_dir,
        "json": output_dir / f"{stem}.json",
        "xml": output_dir / f"{stem}.xml",
        "xlsx": output_dir / f"{stem}.xlsx",
    }


def save_converted_outputs(pem_file: str | Path, response_data: Dict[str, Any]) -> Dict[str, str]:
    pem_path = Path(pem_file)
    output_paths = build_output_paths(pem_path)
    output_paths["dir"].mkdir(parents=True, exist_ok=True)

    json_payload = response_data
    data_for_conversion = response_data.get("datos", response_data)

    with output_paths["json"].open("w", encoding="utf-8") as json_file:
        json.dump(json_payload, json_file, ensure_ascii=False, indent=2)

    xml_text = to_xml_string(data_for_conversion)
    with output_paths["xml"].open("w", encoding="utf-8") as xml_file:
        xml_file.write(xml_text)

    metadata_df = pd.DataFrame(
        [
            {"campo": "archivo_pem", "valor": pem_path.name},
            {"campo": "nombre_archivo_api", "valor": str(response_data.get("nombre_archivo", pem_path.name))},
            {"campo": "procesado_en", "valor": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        ]
    )
    tables = _build_excel_tables(data_for_conversion)

    used_sheet_names: set[str] = {"metadata", "indice"}
    with pd.ExcelWriter(output_paths["xlsx"], engine="openpyxl") as writer:
        metadata_df.to_excel(writer, index=False, sheet_name="metadata")

        index_rows: List[Dict[str, Any]] = []
        for path, df in tables:
            if df is None:
                continue
            export_df = df.copy()
            if export_df.empty:
                export_df = pd.DataFrame([{"info": "sin datos"}])
            for col in export_df.columns:
                export_df[col] = export_df[col].map(_to_excel_cell)

            sheet_name = _sanitize_sheet_name(path, used_sheet_names)
            export_df.to_excel(writer, index=False, sheet_name=sheet_name)
            index_rows.append(
                {
                    "sheet": sheet_name,
                    "path_origen": path,
                    "filas": len(export_df),
                    "columnas": len(export_df.columns),
                }
            )

        index_df = pd.DataFrame(index_rows or [{"sheet": "metadata", "path_origen": "-", "filas": len(metadata_df), "columnas": len(metadata_df.columns)}])
        index_df.to_excel(writer, index=False, sheet_name="indice")

    return {
        "json": str(output_paths["json"]),
        "xml": str(output_paths["xml"]),
        "xlsx": str(output_paths["xlsx"]),
    }


def process_single_pem(
    pem_file: str | Path,
    base_url: str,
    api_key: str = "",
    email: str = "",
    timeout_sec: Optional[int] = None,
) -> Dict[str, Any]:
    response = convertir_pem_api(pem_file, base_url, api_key=api_key, email=email, timeout_sec=timeout_sec)
    http_status = response.get("http_status")
    data = response.get("data")

    if http_status != 200 or not isinstance(data, dict):
        return {
            "success": False,
            "http_status": http_status,
            "error": _extract_error_message(data, http_status),
            "data": data,
        }

    try:
        outputs = save_converted_outputs(pem_file, data)
    except Exception as exc:
        return {
            "success": False,
            "http_status": http_status,
            "error": f"Error guardando archivos convertidos: {exc}",
            "data": data,
        }

    return {
        "success": True,
        "http_status": http_status,
        "data": data,
        "outputs": outputs,
    }
