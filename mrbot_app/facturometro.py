import json
import os
import glob
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote, urlparse

import pandas as pd
from openpyxl import load_workbook

from mrbot_app.consulta import descargar_archivo_minio
from mrbot_app.formatos import (
    aplicar_formato_encabezado,
    autoajustar_columnas,
    agregar_filtros,
)
from mrbot_app.helpers import (
    build_headers,
    ensure_trailing_slash,
    safe_post,
)

MODULE_DIR = "facturometro"


def _representado_dir(base_dir: str, cuit_login: str, cuit_representado: str) -> str:
    path = os.path.join(base_dir, cuit_login, cuit_representado)
    os.makedirs(path, exist_ok=True)
    return path


def consultar_facturometro(
    cuit_login: str,
    clave: str,
    config: tuple,
    cuit_representado: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    base_url, api_key, email = config
    url = ensure_trailing_slash(base_url) + "api/v1/facturometro/consulta"
    headers = build_headers(api_key, email)
    payload = {"cuit_login": cuit_login, "clave": clave, "cuit_representado": cuit_representado}

    if log_fn:
        safe = payload.copy()
        safe["clave"] = "***"
        log_fn(f"REQUEST: {json.dumps(safe, ensure_ascii=False)}")

    resp = safe_post(url, headers, payload)
    http_status = resp.get("http_status")
    data = resp.get("data", {})

    if log_fn:
        log_fn(f"RESPONSE: HTTP {http_status} - {json.dumps(data, ensure_ascii=False, default=str)}")

    result = {
        "cuit_login": cuit_login,
        "cuit_representado": cuit_representado,
    }

    if http_status != 200:
        detail = data.get("detail", {})
        if isinstance(detail, dict):
            msg = detail.get("message", [f"HTTP {http_status}"])
            if isinstance(msg, list):
                msg = "; ".join(msg)
            error_code = detail.get("error_code", "")
        else:
            msg = str(detail)
            error_code = ""
        result.update({
            "success": False,
            "http_status": http_status,
            "message": msg,
            "error_code": error_code,
            "monto_facturado": None,
            "tope_facturacion": None,
            "categoria": None,
            "screenshot_url": None,
        })
        return result

    result.update({
        "success": data.get("success", False),
        "http_status": http_status,
        "message": data.get("message", ""),
        "monto_facturado": data.get("monto_facturado"),
        "tope_facturacion": data.get("tope_facturacion"),
        "categoria": data.get("categoria"),
        "screenshot_url": data.get("screenshot_url_minio"),
    })
    return result


def guardar_resultado_json(
    resultado: Dict[str, Any],
    base_dir: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    cuit_login = resultado["cuit_login"]
    cuit_representado = resultado["cuit_representado"]
    dir_path = _representado_dir(base_dir, cuit_login, cuit_representado)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"facturometro_{cuit_representado}_{timestamp}.json"
    path = os.path.join(dir_path, filename)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2, default=str)
        if log_fn:
            log_fn(f"JSON guardado: {path}")
        return path
    except Exception as e:
        if log_fn:
            log_fn(f"ERROR guardando JSON: {e}")
        return None


def descargar_screenshot(
    screenshot_url: str,
    cuit_login: str,
    cuit_representado: str,
    base_dir: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    if not screenshot_url:
        return None

    dir_path = _representado_dir(base_dir, cuit_login, cuit_representado)

    parsed = unquote(os.path.basename(urlparse(screenshot_url).path))
    base_name = parsed or f"facturometro_{cuit_representado}.png"
    name_no_ext, ext = os.path.splitext(base_name)
    if not ext:
        ext = ".png"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"facturometro_{cuit_representado}_{timestamp}{ext}"
    path = os.path.join(dir_path, filename)

    res = descargar_archivo_minio(screenshot_url, path)
    if res.get("success"):
        if log_fn:
            log_fn(f"Captura descargada: {path}")
        return path
    else:
        if log_fn:
            log_fn(f"ERROR descargando captura: {res.get('error')}")
        return None


def generar_reporte_excel(
    consulta_base_dir: str,
    output_path: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> None:
    json_files = glob.glob(os.path.join(consulta_base_dir, "*", "*", "facturometro_*.json"))
    if not json_files:
        if log_fn:
            log_fn("No se encontraron archivos JSON para generar el reporte.")
        return

    if log_fn:
        log_fn(f"Generando reporte desde {len(json_files)} archivos JSON...")

    rows = []
    for fpath in sorted(json_files):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows.append(data)
        except Exception as e:
            if log_fn:
                log_fn(f"Error leyendo {fpath}: {e}")

    if not rows:
        if log_fn:
            log_fn("No hay datos para incluir en el reporte.")
        return

    df = pd.DataFrame(rows)

    column_map = {
        "cuit_login": "CUIT Login",
        "cuit_representado": "CUIT Representado",
        "success": "Éxito",
        "http_status": "HTTP Status",
        "message": "Mensaje",
        "monto_facturado": "Monto Facturado",
        "tope_facturacion": "Tope Facturación",
        "categoria": "Categoría",
        "error_code": "Código Error",
        "screenshot_url": "URL Captura",
    }

    available_cols = [c for c in column_map if c in df.columns]
    df_out = df[available_cols].rename(columns={c: column_map[c] for c in available_cols})

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_out.to_excel(writer, sheet_name="Facturómetro", index=False)

    wb = load_workbook(output_path)
    ws = wb["Facturómetro"]
    aplicar_formato_encabezado(ws)
    autoajustar_columnas(ws)
    agregar_filtros(ws)
    wb.save(output_path)

    if log_fn:
        log_fn(f"Reporte generado: {output_path}")
