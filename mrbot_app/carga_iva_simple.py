import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv(".env", override=True)

root_url = os.getenv("URL", "https://api-bots.mrbot.com.ar")
mail = os.getenv("MAIL")
api_key = os.getenv("API_KEY")

CAMPOS_ARCHIVOS = [
    "liv_cbte", "liv_alicuota",
    "lic_cbte", "lic_alicuota",
    "csv_cf", "csv_cf_restitucion",
    "csv_df", "csv_df_restitucion",
]


def _log_message(message: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    if log_fn:
        log_fn(message)
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = str(message).splitlines() or [""]
    formatted = "\n".join(
        f"[{timestamp}] {line}" if line else f"[{timestamp}]"
        for line in lines
    )
    print(formatted)


def _log_info(message: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    _log_message(f"INFO: {message}", log_fn)


def _log_error(message: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    _log_message(f"ERROR: {message}", log_fn)


def _log_payload(payload: Dict[str, Any], log_fn: Optional[Callable[[str], None]] = None) -> None:
    safe = {}
    for k, v in payload.items():
        safe[k] = "***" if k == "clave_representante" else v
    serialized = json.dumps(safe, ensure_ascii=False, default=str)
    _log_message(f"PAYLOAD: {serialized}", log_fn)


def _log_response(http_status: Any, data: Any, log_fn: Optional[Callable[[str], None]] = None) -> None:
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    _log_message(f"RESPONSE: HTTP {http_status} - {serialized}", log_fn)


def _build_files_list(archivos: Dict[str, str]) -> List[Tuple[str, Tuple[str, bytes, str]]]:
    files = []
    for campo, ruta in archivos.items():
        if campo not in CAMPOS_ARCHIVOS:
            continue
        if not ruta or not os.path.isfile(ruta):
            continue
        nombre = os.path.basename(ruta)
        with open(ruta, "rb") as f:
            contenido = f.read()
        files.append((campo, (nombre, contenido, "text/plain" if ruta.endswith(".txt") else "text/csv")))
    return files


def _extraer_tipo_desde_nombre(filename: str) -> str:
    f = filename.upper()
    if "LIV" in f and "CBTE" in f and "ALICUOTA" not in f:
        return "liv_cbte"
    if "LIV" in f and "CBTE ALICUOTA" in f:
        return "liv_alicuota"
    if "LIC" in f and "CBTE" in f and "ALICUOTA" not in f:
        return "lic_cbte"
    if "LIC" in f and "CBTE ALICUOTA" in f:
        return "lic_alicuota"
    if "IVA SIMPLE - CF" in f and "RESTITUCION" not in f:
        return "csv_cf"
    if "IVA SIMPLE - CF RESTITUCION" in f:
        return "csv_cf_restitucion"
    if "IVA SIMPLE - DF" in f and "RESTITUCION" not in f:
        return "csv_df"
    if "IVA SIMPLE - DF RESTITUCION" in f:
        return "csv_df_restitucion"
    return ""


def mapear_archivos_por_nombre(rutas: List[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    no_match = []
    for r in rutas:
        if not r:
            continue
        tipo = _extraer_tipo_desde_nombre(os.path.basename(r))
        if tipo:
            result[tipo] = r
        else:
            no_match.append(r)
    return result, no_match


def carga_iva_simple(
    cuit_representante: str,
    clave_representante: str,
    cuit_representado: str = "",
    denominacion: str = "",
    periodo: str = "",
    archivos: Optional[Dict[str, str]] = None,
    operaciones_ng_o_e: bool = False,
    prorrateo_global: bool = False,
    prorrateo_asignacion_directa: bool = False,
    prorrateo_ambos: bool = False,
    importacion_definitiva_bienes: bool = False,
    importacion_servicios: bool = False,
    regimen_turiva: bool = False,
    bienes_usados: bool = False,
    ninguna_anteriores: bool = True,
    proxy_request: bool = False,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    url = root_url.rstrip("/") + "/api/v1/portal_iva/carga"

    headers = {
        "x-api-key": api_key,
        "email": mail,
    }

    data: Dict[str, Any] = {
        "cuit_representante": cuit_representante,
        "clave_representante": clave_representante,
        "cuit_representado": cuit_representado or cuit_representante,
        "denominacion": denominacion,
        "periodo": periodo,
        "operaciones_ng_o_e": str(operaciones_ng_o_e).lower(),
        "prorrateo_global": str(prorrateo_global).lower(),
        "prorrateo_asignacion_directa": str(prorrateo_asignacion_directa).lower(),
        "prorrateo_ambos": str(prorrateo_ambos).lower(),
        "importacion_definitiva_bienes": str(importacion_definitiva_bienes).lower(),
        "importacion_servicios": str(importacion_servicios).lower(),
        "regimen_turiva": str(regimen_turiva).lower(),
        "bienes_usados": str(bienes_usados).lower(),
        "ninguna_anteriores": str(ninguna_anteriores).lower(),
        "proxy_request": str(proxy_request).lower(),
    }

    files = _build_files_list(archivos or {})

    _log_message(f"REQUEST INICIO: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_fn)
    _log_payload(data, log_fn)
    _log_info(f"Archivos adjuntos: {len(files)} ({', '.join(f[0] for f in files)})", log_fn)

    try:
        response = requests.post(url, headers=headers, data=data, files=files)
        http_status = response.status_code
        try:
            resp_data = response.json()
        except ValueError:
            resp_data = {
                "success": False,
                "error": f"Respuesta no JSON (HTTP {response.status_code})",
                "http_status": response.status_code,
                "content": response.text[:500],
            }
            _log_error(f"Respuesta no JSON (HTTP {response.status_code})", log_fn)
            _log_message(f"RESPONSE FIN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_fn)
            _log_response(http_status, resp_data, log_fn)
            return resp_data
    except Exception as exc:
        resp_data = {
            "success": False,
            "error": f"Error de conexion: {exc}",
            "http_status": None,
        }
        _log_error(f"Error de conexion: {exc}", log_fn)
        return resp_data

    if not isinstance(resp_data, dict):
        resp_data = {"raw": resp_data}
    resp_data["http_status"] = http_status
    _log_message(f"RESPONSE FIN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_fn)
    _log_response(http_status, resp_data, log_fn)
    return resp_data


def validar_archivos(file_paths: List[str], log_fn: Optional[Callable[[str], None]] = None) -> List[str]:
    missing = []
    for f in file_paths:
        if not f:
            continue
        if not os.path.exists(f):
            missing.append(f)
            _log_error(f"Archivo no encontrado: {f}", log_fn)
    return missing


def validar_opciones_iva(
    operaciones_ng_o_e: bool,
    prorrateo_global: bool,
    prorrateo_asignacion_directa: bool,
    prorrateo_ambos: bool,
    importacion_definitiva_bienes: bool,
    importacion_servicios: bool,
    regimen_turiva: bool,
    bienes_usados: bool,
    ninguna_anteriores: bool,
) -> List[str]:
    errores: List[str] = []

    if operaciones_ng_o_e:
        if not prorrateo_global and not prorrateo_asignacion_directa:
            errores.append(
                "Si 'Op. No Grav. o Exentas' esta activa, debe seleccionar "
                "'Prorrateo Global' o 'Prorrateo Asignacion Directa' (una sola)."
            )
        elif prorrateo_global and prorrateo_asignacion_directa:
            errores.append(
                "Si 'Op. No Grav. o Exentas' esta activa, no puede seleccionar "
                "ambos: 'Prorrateo Global' y 'Prorrateo Asignacion Directa'."
            )

    opciones_activas = any([
        operaciones_ng_o_e,
        prorrateo_global,
        prorrateo_asignacion_directa,
        prorrateo_ambos,
        importacion_definitiva_bienes,
        importacion_servicios,
        regimen_turiva,
        bienes_usados,
    ])
    if ninguna_anteriores and opciones_activas:
        errores.append(
            "'Ninguna de las anteriores' no puede estar activa si alguna de las "
            "opciones de IVA lo esta."
        )

    return errores
