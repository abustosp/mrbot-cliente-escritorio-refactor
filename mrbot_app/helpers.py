import os
import re
import sys
import zipfile
import shutil
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from mrbot_app.config import get_request_timeouts


def ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def build_headers(api_key: str, email: str) -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    if email:
        headers["email"] = email
    return headers


def safe_post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    post_timeout, _ = get_request_timeouts()
    effective_timeout = timeout_sec if timeout_sec is not None else post_timeout
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=effective_timeout)
        try:
            data = resp.json()
        except Exception:
            data = {"raw_text": resp.text}
        return {"http_status": resp.status_code, "data": data}
    except Exception as exc:
        return {"http_status": None, "data": {"success": False, "message": f"Error de conexion: {exc}"}}


def safe_get(url: str, headers: Dict[str, str], timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    _, get_timeout = get_request_timeouts()
    effective_timeout = timeout_sec if timeout_sec is not None else get_timeout
    try:
        resp = requests.get(url, headers=headers, timeout=effective_timeout)
        try:
            data = resp.json()
        except Exception:
            data = {"raw_text": resp.text}
        return {"http_status": resp.status_code, "data": data}
    except Exception as exc:
        return {"http_status": None, "data": {"success": False, "message": f"Error de conexion: {exc}"}}


def _format_period_aaaamm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
    if isinstance(value, (int, float)):
        try:
            return f"{int(value):06d}"
        except Exception:
            return str(value)
    text = str(value).strip()
    if not text:
        return text
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        return digits
    return text


def _format_excel_serial(value: float) -> Optional[str]:
    try:
        dt = pd.to_datetime(value, unit="D", origin="1899-12-30")
    except Exception:
        return None
    if pd.isna(dt):
        return None
    try:
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return None


def format_date_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, (int, float)):
        if 1 <= value <= 80000:
            formatted = _format_excel_serial(value)
            if formatted:
                return formatted
        if isinstance(value, float) and value.is_integer():
            text = str(int(value))
        else:
            text = str(value)
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
        if pd.notna(parsed):
            return parsed.strftime("%d/%m/%Y")
        return text
    text = str(value).strip()
    if not text:
        return text
    if text.isdigit():
        if len(text) == 8:
            try:
                year = int(text[:4])
            except ValueError:
                year = 0
            if 1900 <= year <= 2100:
                try:
                    parsed = datetime.strptime(text, "%Y%m%d")
                    return parsed.strftime("%d/%m/%Y")
                except Exception:
                    pass
    if text.isdigit():
        num = int(text)
        if 1 <= num <= 80000:
            formatted = _format_excel_serial(num)
            if formatted:
                return formatted
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        parsed = pd.to_datetime(text, dayfirst=False, errors="coerce")
        if pd.notna(parsed):
            return parsed.strftime("%d/%m/%Y")
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.notna(parsed):
        return parsed.strftime("%d/%m/%Y")
    return text


def _format_dates_str(df: pd.DataFrame) -> pd.DataFrame:
    """Intenta formatear columnas con nombres que contengan desde/hasta/fecha a dd/mm/aaaa como string."""
    out = df.copy()
    for col in out.columns:
        lower_col = col.lower()
        if "periodo" in lower_col and any(key in lower_col for key in ["desde", "hasta"]):
            out[col] = out[col].apply(_format_period_aaaamm)
            continue
        if any(key in lower_col for key in ["desde", "hasta", "fecha"]):
            out[col] = out[col].apply(format_date_str)
    return out


def df_preview(df: pd.DataFrame, rows: int = 5) -> str:
    if df.empty:
        return "Sin filas para mostrar."
    subset = _format_dates_str(df.head(rows).copy())
    headers = list(subset.columns)
    header_line = " | ".join(headers)
    rows_str = []
    for _, row in subset.iterrows():
        row_vals = []
        for h in headers:
            v = row[h]
            try:
                is_na = pd.isna(v)
                if hasattr(is_na, "all"):
                    is_na = is_na.all()
            except Exception:
                is_na = False
            row_vals.append("" if is_na else str(v))
        rows_str.append(" | ".join(row_vals))
    max_len = max(len(header_line), *(len(r) for r in rows_str))
    sep = "-" * max_len
    return "\n".join([header_line, sep] + rows_str)


def parse_bool_cell(value: Any, default: bool = False) -> bool:
    """
    Convierte valores de celdas a booleano. Acepta 1/0, true/false, si/no, yes/no.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "si", "sí", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return default


def make_today_str() -> str:
    return date.today().strftime("%d/%m/%Y")


def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Datos") -> bytes:
    with pd.ExcelWriter(os.devnull if sys.platform == "win32" else "/tmp/ignore.xlsx", engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    from io import BytesIO

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


def get_unique_filename(directory: str, filename: str) -> str:
    """
    Genera un nombre único para el archivo en el directorio.
    Si el archivo ya existe, agrega un timestamp al nombre (antes de la extensión).
    Formato timestamp: _YYYYMMDD-HH_MM_SS
    Si aun con timestamp existe (muy raro), agrega contador.
    """
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return filename

    base, ext = os.path.splitext(filename)
    timestamp = datetime.now().strftime("%Y%m%d-%H_%M_%S")
    new_name = f"{base}_{timestamp}{ext}"

    # Loop de seguridad por si acaso cae en el mismo segundo
    counter = 1
    while os.path.exists(os.path.join(directory, new_name)):
        new_name = f"{base}_{timestamp}_{counter}{ext}"
        counter += 1

    return new_name


def unzip_and_rename(zip_path: str, target_name_no_ext: str) -> Optional[str]:
    """
    Descomprime el zip en la misma ubicación.
    Si hay un solo archivo, lo renombra a target_name_no_ext + su extension original.
    Se asegura de no sobreescribir archivos existentes leyendo directamente del zip.
    Devuelve la ruta del archivo extraido si tuvo éxito, None en caso contrario.
    No borra el zip.
    """
    try:
        directory = os.path.dirname(zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            files = zf.namelist()
            if len(files) != 1:
                return None  # Requisito: unico archivo

            inner_filename = files[0]
            _, inner_ext = os.path.splitext(inner_filename)

            # Nombre destino
            target_filename = target_name_no_ext + inner_ext

            # Verificar colisión para el archivo destino y obtener nombre único
            unique_target_filename = get_unique_filename(directory, target_filename)
            final_path = os.path.join(directory, unique_target_filename)

            # Streaming copy directly to target
            with zf.open(inner_filename) as source:
                with open(final_path, 'wb') as target:
                    shutil.copyfileobj(source, target)

            return final_path
    except Exception:
        return None
