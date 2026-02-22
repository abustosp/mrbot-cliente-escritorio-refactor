import base64
import hashlib
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


DEFAULT_WSAA_SERVICE = os.getenv("WSAA_SERVICE", "veconsumerws")
DEFAULT_CERT_API_URL = os.getenv("CERT_API_URL", "https://api-certificados.mrbot.com.ar/")
DEFAULT_CERT_API_CN = os.getenv("CERT_API_CN", "mrbot")


def _get_env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


DEFAULT_CERT_API_TIMEOUT = _get_env_int("CERT_API_TIMEOUT", 60)
DEFAULT_TOKEN_CACHE_SEC = _get_env_int("TOKEN_SIGN_CACHE_SEC", 600)


def _normalize_key_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.match(r".*[+-]\d{4}$", text):
        text = text[:-2] + ":" + text[-2:]

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _find_first_value(obj: Any, keys: set, max_depth: int = 8) -> Optional[str]:
    stack: List[Tuple[Any, int]] = [(obj, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue

        if isinstance(current, dict):
            for k, v in current.items():
                normalized = _normalize_key_name(k)
                if normalized in keys:
                    if v is None:
                        continue
                    value = str(v).strip()
                    if value:
                        return value
                if isinstance(v, (dict, list)):
                    stack.append((v, depth + 1))
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))

    return None


def _extract_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    message = _find_first_value(
        data,
        {
            "message",
            "msg",
            "error",
            "detail",
            "descripcion",
            "description",
            "faultstring",
        },
    )
    return message or ""


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def _safe_read_head(path: str, max_bytes: int = 4096) -> str:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(max_bytes)
        return chunk.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _read_file_text(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    return raw.decode("utf-8", errors="ignore")


def _classify_cert_material(path: str) -> Optional[str]:
    lower = path.lower()
    ext = os.path.splitext(lower)[1]

    if ext in {".key"}:
        return "key"
    if ext in {".crt", ".cer"}:
        return "cert"

    if ext == ".pem":
        head = _safe_read_head(path)
        if "PRIVATE KEY" in head:
            return "key"
        if "BEGIN CERTIFICATE" in head:
            return "cert"

    return None


def _score_path(path: str, cuit: str) -> Tuple[int, int]:
    basename = os.path.basename(path).lower()
    score = 0

    if cuit and cuit in basename:
        score += 20
    if "afip" in basename:
        score += 5
    if "arca" in basename:
        score += 3

    return score, -len(path)


def _pick_best_candidate(candidates: List[str], cuit: str) -> Optional[str]:
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: _score_path(p, cuit), reverse=True)[0]


def discover_certificate_paths(cuit_representada: str, cert_dir: str) -> Dict[str, str]:
    """
    Intenta descubrir automaticamente material criptografico en una carpeta.

    Regla:
    - busca par cert+key
    - prioriza nombres de archivo que contengan el CUIT representado
    """
    result: Dict[str, str] = {}
    base_dir = (cert_dir or "").strip()
    cuit = re.sub(r"\D", "", (cuit_representada or ""))

    if not base_dir or not os.path.isdir(base_dir):
        return result

    cert_files: List[str] = []
    key_files: List[str] = []

    for root, _dirs, files in os.walk(base_dir):
        for filename in files:
            path = os.path.join(root, filename)
            kind = _classify_cert_material(path)
            if kind == "cert":
                cert_files.append(path)
            elif kind == "key":
                key_files.append(path)

    best_cert = _pick_best_candidate(cert_files, cuit)
    best_key = _pick_best_candidate(key_files, cuit)

    if best_cert:
        result["cert_path"] = best_cert
    if best_key:
        result["key_path"] = best_key

    return result


def _resolve_cert_material(
    cuit_representada: str,
    cert_path: str,
    key_path: str,
    cert_dir: str,
) -> Dict[str, Any]:
    resolved_cert_path = (cert_path or "").strip()
    resolved_key_path = (key_path or "").strip()
    resolved_cert_dir = (cert_dir or "").strip()

    if not resolved_cert_path:
        resolved_cert_path = os.getenv("AFIP_CERT_PATH", "").strip()
    if not resolved_key_path:
        resolved_key_path = os.getenv("AFIP_KEY_PATH", "").strip()
    if not resolved_cert_dir:
        resolved_cert_dir = os.getenv("AFIP_CERT_DIR", "").strip()

    discovery: Dict[str, str] = {}
    if not (resolved_cert_path and resolved_key_path):
        discovery = discover_certificate_paths(cuit_representada, resolved_cert_dir)
        resolved_cert_path = resolved_cert_path or discovery.get("cert_path", "")
        resolved_key_path = resolved_key_path or discovery.get("key_path", "")

    if not resolved_cert_path or not resolved_key_path:
        return {
            "success": False,
            "message": (
                "No se encontró material criptográfico. "
                "Define AFIP_CERT_PATH + AFIP_KEY_PATH "
                "(o AFIP_CERT_DIR para autodetección)."
            ),
            "cert_dir": resolved_cert_dir,
            "discovery": discovery,
        }

    if not os.path.isfile(resolved_cert_path):
        return {
            "success": False,
            "message": f"No se encontró el certificado: {resolved_cert_path}",
        }
    if not os.path.isfile(resolved_key_path):
        return {
            "success": False,
            "message": f"No se encontró la clave privada: {resolved_key_path}",
        }

    return {
        "success": True,
        "cert_path": resolved_cert_path,
        "key_path": resolved_key_path,
        "cert_dir": resolved_cert_dir,
        "discovery": discovery,
    }


def _resolve_material_for_token_api(
    cuit_representada: str,
    cert_path: str,
    key_path: str,
    cert_dir: str,
) -> Dict[str, Any]:
    resolved = _resolve_cert_material(
        cuit_representada=cuit_representada,
        cert_path=cert_path,
        key_path=key_path,
        cert_dir=cert_dir,
    )
    if not resolved.get("success"):
        return resolved

    resolved_cert_path = resolved.get("cert_path", "")
    resolved_key_path = resolved.get("key_path", "")

    try:
        cert_text = _read_file_text(resolved_cert_path)
        key_text = _read_file_text(resolved_key_path)
    except Exception as exc:
        return {
            "success": False,
            "message": f"No se pudo preparar certificado/clave para la API: {exc}",
            "cert_path": resolved_cert_path,
            "key_path": resolved_key_path,
            "cert_dir": resolved.get("cert_dir", ""),
        }

    cert_b64 = base64.b64encode(cert_text.encode("utf-8")).decode("ascii")
    key_b64 = base64.b64encode(key_text.encode("utf-8")).decode("ascii")

    return {
        "success": True,
        "cert_b64": cert_b64,
        "key_b64": key_b64,
        "cert_path": resolved_cert_path,
        "key_path": resolved_key_path,
        "cert_dir": resolved.get("cert_dir", ""),
    }


def _call_cert_api_token_sign(
    cert_api_url: str,
    email: str,
    api_key: str,
    cuit_representante: str,
    certificado_b64: str,
    llave_privada_b64: str,
    servicio_id: str,
    testing: bool,
    cn: str,
    timeout_sec: int,
) -> Dict[str, Any]:
    url = _ensure_trailing_slash(cert_api_url) + "api/v1/token_sign/"

    params = {
        "email": email,
        "api_key": api_key,
        "cuit_representante": int(cuit_representante),
        "certificado": certificado_b64,
        "llave_privada": llave_privada_b64,
        "servicio_id": servicio_id,
        "testing": str(bool(testing)).lower(),
        "cn": cn,
    }

    try:
        response = requests.post(url, params=params, timeout=timeout_sec)
    except Exception as exc:
        return {
            "success": False,
            "message": f"No se pudo conectar con la API de certificados: {exc}",
            "http_status": None,
            "api_url": url,
        }

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    if response.status_code != 200:
        message = _extract_message(data) or f"API certificados respondió HTTP {response.status_code}"
        return {
            "success": False,
            "message": message,
            "http_status": response.status_code,
            "api_url": url,
            "raw_response": data,
        }

    token = _find_first_value(data, {"token"})
    sign = _find_first_value(data, {"sign", "firma"})
    expiration_raw = _find_first_value(
        data,
        {"expirationtime", "expiration", "expires", "vencimiento", "fechavencimiento"},
    )
    expiration_time = _parse_iso_datetime(expiration_raw or "")

    if not token or not sign:
        message = _extract_message(data) or "La API de certificados no devolvió token/sign."
        return {
            "success": False,
            "message": message,
            "http_status": response.status_code,
            "api_url": url,
            "raw_response": data,
        }

    return {
        "success": True,
        "token": token,
        "sign": sign,
        "expiration_time": expiration_time,
        "expiration_time_raw": expiration_raw,
        "http_status": response.status_code,
        "api_url": url,
        "raw_response": data,
    }


class TokenSignManager:
    """
    Gestiona obtención y cache temporal de token/sign usando api-certificados.mrbot.com.ar.
    """

    def __init__(self):
        self._cache: Dict[Tuple[str, str, bool, str, str, str, str, str], Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _cache_key(
        self,
        service: str,
        cuit_representada: str,
        cuit_representante: str,
        testing: bool,
        cert_api_url: str,
        cert_api_email: str,
        cert_api_cn: str,
        material_fingerprint: str,
    ) -> Tuple[str, str, bool, str, str, str, str, str]:
        return (
            service,
            f"{cuit_representada}|{cuit_representante}",
            bool(testing),
            cert_api_url,
            cert_api_email,
            cert_api_cn,
            material_fingerprint,
            str(bool(testing)),
        )

    def get_token_sign(
        self,
        cuit_representada: str,
        cuit_representante: str = "",
        service: str = DEFAULT_WSAA_SERVICE,
        testing: bool = False,
        cert_path: str = "",
        key_path: str = "",
        cert_dir: str = "",
        timeout_sec: Optional[int] = None,
        force_refresh: bool = False,
        cert_api_url: str = "",
        cert_api_email: str = "",
        cert_api_key: str = "",
        cert_api_cn: str = "",
    ) -> Dict[str, Any]:
        clean_cuit_repr = re.sub(r"\D", "", (cuit_representada or ""))
        if len(clean_cuit_repr) != 11:
            return {
                "success": False,
                "message": "El CUIT representado debe tener 11 dígitos.",
            }

        clean_cuit_rep = re.sub(r"\D", "", (cuit_representante or "")) or clean_cuit_repr
        if len(clean_cuit_rep) != 11:
            return {
                "success": False,
                "message": "El CUIT representante debe tener 11 dígitos.",
            }

        effective_api_url = (cert_api_url or os.getenv("CERT_API_URL", "") or DEFAULT_CERT_API_URL).strip()
        effective_api_email = (cert_api_email or os.getenv("CERT_API_EMAIL", "") or os.getenv("MAIL", "")).strip()
        effective_api_key = (cert_api_key or os.getenv("CERT_API_KEY", "") or os.getenv("API_KEY", "")).strip()
        effective_api_cn = (cert_api_cn or os.getenv("CERT_API_CN", "") or DEFAULT_CERT_API_CN).strip()

        if not effective_api_email:
            return {
                "success": False,
                "message": "Falta email para la API de certificados (CERT_API_EMAIL o MAIL).",
            }
        if not effective_api_key:
            return {
                "success": False,
                "message": "Falta API key para la API de certificados (CERT_API_KEY o API_KEY).",
            }

        prepared = _resolve_material_for_token_api(
            cuit_representada=clean_cuit_repr,
            cert_path=cert_path,
            key_path=key_path,
            cert_dir=cert_dir,
        )
        if not prepared.get("success"):
            return prepared

        cert_b64 = prepared.get("cert_b64", "")
        key_b64 = prepared.get("key_b64", "")

        fingerprint = hashlib.sha256(f"{cert_b64}|{key_b64}".encode("utf-8")).hexdigest()
        cache_key = self._cache_key(
            service=service,
            cuit_representada=clean_cuit_repr,
            cuit_representante=clean_cuit_rep,
            testing=testing,
            cert_api_url=effective_api_url,
            cert_api_email=effective_api_email,
            cert_api_cn=effective_api_cn,
            material_fingerprint=fingerprint,
        )

        if not force_refresh:
            with self._lock:
                cached = self._cache.get(cache_key)
            if cached:
                expires_at = cached.get("cached_until")
                if isinstance(expires_at, datetime) and expires_at > datetime.now(timezone.utc):
                    out = dict(cached)
                    out["cached"] = True
                    out["source"] = "cache"
                    return out

        timeout = timeout_sec if timeout_sec is not None else DEFAULT_CERT_API_TIMEOUT
        api_result = _call_cert_api_token_sign(
            cert_api_url=effective_api_url,
            email=effective_api_email,
            api_key=effective_api_key,
            cuit_representante=clean_cuit_rep,
            certificado_b64=cert_b64,
            llave_privada_b64=key_b64,
            servicio_id=service,
            testing=bool(testing),
            cn=effective_api_cn,
            timeout_sec=timeout,
        )

        if not api_result.get("success"):
            api_result["cert_path"] = prepared.get("cert_path", "")
            api_result["key_path"] = prepared.get("key_path", "")
            api_result["cert_dir"] = prepared.get("cert_dir", "")
            return api_result

        now = datetime.now(timezone.utc)
        cached_until = now + timedelta(seconds=DEFAULT_TOKEN_CACHE_SEC)
        exp = api_result.get("expiration_time")
        if isinstance(exp, datetime):
            exp_margin = exp - timedelta(minutes=2)
            if exp_margin > now:
                cached_until = min(cached_until, exp_margin)

        output = {
            "success": True,
            "token": api_result.get("token"),
            "sign": api_result.get("sign"),
            "expiration_time": api_result.get("expiration_time"),
            "expiration_time_raw": api_result.get("expiration_time_raw"),
            "http_status": api_result.get("http_status"),
            "api_url": api_result.get("api_url"),
            "raw_response": api_result.get("raw_response"),
            "cached": False,
            "source": "api_certificados",
            "service": service,
            "cuit_representada": clean_cuit_repr,
            "cuit_representante": clean_cuit_rep,
            "cert_path": prepared.get("cert_path", ""),
            "key_path": prepared.get("key_path", ""),
            "cert_dir": prepared.get("cert_dir", ""),
            "cached_until": cached_until,
        }

        with self._lock:
            self._cache[cache_key] = dict(output)

        return output


def obtain_token_sign(
    cuit_representada: str,
    cuit_representante: str = "",
    service: str = DEFAULT_WSAA_SERVICE,
    testing: bool = False,
    cert_path: str = "",
    key_path: str = "",
    cert_dir: str = "",
    timeout_sec: Optional[int] = None,
    force_refresh: bool = False,
    cert_api_url: str = "",
    cert_api_email: str = "",
    cert_api_key: str = "",
    cert_api_cn: str = "",
) -> Dict[str, Any]:
    manager = TokenSignManager()
    return manager.get_token_sign(
        cuit_representada=cuit_representada,
        cuit_representante=cuit_representante,
        service=service,
        testing=testing,
        cert_path=cert_path,
        key_path=key_path,
        cert_dir=cert_dir,
        timeout_sec=timeout_sec,
        force_refresh=force_refresh,
        cert_api_url=cert_api_url,
        cert_api_email=cert_api_email,
        cert_api_key=cert_api_key,
        cert_api_cn=cert_api_cn,
    )
