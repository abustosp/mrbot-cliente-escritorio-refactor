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

FALLBACK_BASE_DIR = os.path.join("descargas", "descargas_provinciales")


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


def _format_periodo(value: str) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) >= 6:
        return digits[:6]
    return value


def _do_request(
    endpoint: str,
    payload: Dict[str, Any],
    safe_payload: Dict[str, Any],
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    url = root_url.rstrip("/") + endpoint
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "email": mail,
    }

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


def consulta_arba(
    cuit: str,
    clave: str,
    periodo: str,
    denominacion: str,
    carga_minio: bool = True,
    proxy_request: Optional[bool] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    payload = {
        "cuit": cuit,
        "clave": clave,
        "periodo": _format_periodo(periodo),
        "denominacion": denominacion,
        "carga_minio": carga_minio,
    }
    if proxy_request is not None:
        payload["proxy_request"] = proxy_request

    safe_payload = dict(payload)
    if "clave" in safe_payload:
        safe_payload["clave"] = "***"

    return _do_request("/api/v1/retenciones_percepciones_iibb/arba/consulta", payload, safe_payload, log_fn)


def consulta_agip(
    usuario: str,
    clave: str,
    cuit_representado: str,
    denominacion: str,
    desde: str,
    hasta: str,
    carga_minio: bool = True,
    proxy_request: Optional[bool] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    payload = {
        "usuario": usuario,
        "clave": clave,
        "cuit_representado": cuit_representado,
        "denominacion": denominacion,
        "desde": _format_periodo(desde),
        "hasta": _format_periodo(hasta),
        "carga_minio": carga_minio,
    }
    if proxy_request is not None:
        payload["proxy_request"] = proxy_request

    safe_payload = dict(payload)
    if "clave" in safe_payload:
        safe_payload["clave"] = "***"

    return _do_request("/api/v1/retenciones_percepciones_iibb/agip/consulta", payload, safe_payload, log_fn)


def consulta_misiones(
    cuit_representante: str,
    clave_representante: str,
    cuit_representado: str,
    denominacion: str,
    desde: str,
    hasta: str,
    carga_minio: bool = True,
    proxy_request: Optional[bool] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    payload = {
        "cuit_representante": cuit_representante,
        "clave_representante": clave_representante,
        "cuit_representado": cuit_representado,
        "denominacion": denominacion,
        "desde": _format_periodo(desde),
        "hasta": _format_periodo(hasta),
        "carga_minio": carga_minio,
    }
    if proxy_request is not None:
        payload["proxy_request"] = proxy_request

    safe_payload = dict(payload)
    if "clave_representante" in safe_payload:
        safe_payload["clave_representante"] = "***"

    return _do_request("/api/v1/retenciones_percepciones_iibb/misiones/consulta", payload, safe_payload, log_fn)
