import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv(".env", override=True)

root_url = os.getenv("URL", "https://api-bots.mrbot.com.ar")
mail = os.getenv("MAIL")
api_key = os.getenv("API_KEY")

FALLBACK_BASE_DIR = os.path.join("descargas", "portal_iva")


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


def _log_request(payload: Any, log_fn: Optional[Callable[[str], None]] = None) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    _log_message(f"REQUEST: {serialized}", log_fn)


def _log_response(http_status: Any, payload: Any, log_fn: Optional[Callable[[str], None]] = None) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    _log_message(f"RESPONSE: HTTP {http_status} - {serialized}", log_fn)


def consulta_portal_iva(
    cuit_representante: str,
    clave_representante: str,
    cuit_representado: str,
    denominacion: str,
    periodo: str,
    operaciones_ng_o_e: bool = False,
    prorrateo_global: bool = False,
    prorrateo_asignacion_directa: bool = False,
    prorrateo_ambos: bool = False,
    importacion_definitiva_bienes: bool = False,
    importacion_servicios: bool = False,
    regimen_turiva: bool = False,
    bienes_usados: bool = False,
    ninguna_anteriores: bool = True,
    descarga_csv_ventas: bool = True,
    descarga_csv_compras: bool = True,
    carga_minio: bool = True,
    proxy_request: Optional[bool] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    url = root_url.rstrip("/") + "/api/v1/portal_iva/consulta"

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "email": mail,
    }

    payload = {
        "cuit_representante": cuit_representante,
        "clave_representante": clave_representante,
        "cuit_representado": cuit_representado,
        "denominacion": denominacion,
        "periodo": periodo,
        "operaciones_ng_o_e": operaciones_ng_o_e,
        "prorrateo_global": prorrateo_global,
        "prorrateo_asignacion_directa": prorrateo_asignacion_directa,
        "prorrateo_ambos": prorrateo_ambos,
        "importacion_definitiva_bienes": importacion_definitiva_bienes,
        "importacion_servicios": importacion_servicios,
        "regimen_turiva": regimen_turiva,
        "bienes_usados": bienes_usados,
        "ninguna_anteriores": ninguna_anteriores,
        "descarga_csv_ventas": descarga_csv_ventas,
        "descarga_csv_compras": descarga_csv_compras,
        "carga_minio": carga_minio,
    }

    if proxy_request is not None:
        payload["proxy_request"] = proxy_request

    safe_payload = dict(payload)
    if "clave_representante" in safe_payload:
        safe_payload["clave_representante"] = "***"

    _log_message(f"REQUEST INICIO: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_fn)
    _log_request(safe_payload, log_fn)
    _log_message("", log_fn)

    response = requests.post(url, headers=headers, json=payload)
    http_status = response.status_code
    response_end = datetime.now()

    try:
        data = response.json()
    except ValueError:
        data = {
            "success": False,
            "error": f"Respuesta no JSON (HTTP {response.status_code})",
            "http_status": response.status_code,
            "content": response.text[:500],
        }
        _log_error(f"Respuesta no JSON (HTTP {response.status_code})", log_fn)
        _log_message(f"RESPONSE FIN: {response_end.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_fn)
        _log_response(http_status, data, log_fn)
        _log_message("", log_fn)
        return data

    _log_message(f"RESPONSE FIN: {response_end.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_fn)
    _log_response(http_status, data, log_fn)
    _log_message("", log_fn)
    return data
