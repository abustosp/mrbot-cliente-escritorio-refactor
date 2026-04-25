import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mrbot_app.consulta import descargar_archivo_minio

load_dotenv()

BASE_URL = os.getenv("URL", "https://api-bots.mrbot.com.ar/").rstrip("/") + "/"
API_KEY = os.getenv("API_KEY", "")
MAIL = os.getenv("MAIL", "")

TEST_RETPER_ARBA_CUIT = os.getenv("TEST_RETPER_ARBA_CUIT", "")
TEST_RETPER_ARBA_CLAVE = os.getenv("TEST_RETPER_ARBA_CLAVE", "")
TEST_RETPER_AGIP_USUARIO = os.getenv("TEST_RETPER_AGIP_USUARIO", "")
TEST_RETPER_AGIP_CLAVE = os.getenv("TEST_RETPER_AGIP_CLAVE", "")
TEST_RETPER_AGIP_CUIT = os.getenv("TEST_RETPER_AGIP_CUIT", "")
TEST_RETPER_MISIONES_CUIT = os.getenv("TEST_RETPER_MISIONES_CUIT", "")
TEST_RETPER_MISIONES_CLAVE = os.getenv("TEST_RETPER_MISIONES_CLAVE", "")

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["x-api-key"] = API_KEY
if MAIL:
    HEADERS["email"] = MAIL


def _download_first(links: list[str]) -> None:
    assert links, "No se encontraron links de descarga en la respuesta."
    url = links[0]
    name = os.path.basename(urlparse(url).path) or "descarga.bin"
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, name)
        res = descargar_archivo_minio(url, target)
        assert res.get("success"), f"Descarga fallida: {res}"
        assert os.path.exists(target), "El archivo descargado no existe."
        assert os.path.getsize(target) > 0, "El archivo descargado esta vacio."


def _links_ret_per(data: dict) -> list[str]:
    links: list[str] = []
    for item in data.get("archivos") or []:
        if isinstance(item, dict) and item.get("url_minio"):
            links.append(item["url_minio"])
    return links


def test_arba_descarga() -> None:
    if not TEST_RETPER_ARBA_CUIT or not TEST_RETPER_ARBA_CLAVE:
        raise ValueError(
            "Credenciales ARBA no configuradas. "
            "Revisa TEST_RETPER_ARBA_CUIT y TEST_RETPER_ARBA_CLAVE en .env"
        )

    payload = {
        "cuit": TEST_RETPER_ARBA_CUIT,
        "clave": TEST_RETPER_ARBA_CLAVE,
        "periodo": "202601",
        "denominacion": "Test ARBA",
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(
        BASE_URL + "api/v1/retenciones_percepciones_iibb/arba/consulta",
        headers=HEADERS, json=payload, timeout=180,
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_ret_per(data)
    _download_first(links)


def test_agip_descarga() -> None:
    if not TEST_RETPER_AGIP_USUARIO or not TEST_RETPER_AGIP_CLAVE:
        raise ValueError(
            "Credenciales AGIP no configuradas. "
            "Revisa TEST_RETPER_AGIP_USUARIO y TEST_RETPER_AGIP_CLAVE en .env"
        )

    payload = {
        "usuario": TEST_RETPER_AGIP_USUARIO,
        "clave": TEST_RETPER_AGIP_CLAVE,
        "cuit_representado": TEST_RETPER_AGIP_CUIT,
        "denominacion": "Test AGIP",
        "desde": "202601",
        "hasta": "202601",
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(
        BASE_URL + "api/v1/retenciones_percepciones_iibb/agip/consulta",
        headers=HEADERS, json=payload, timeout=180,
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_ret_per(data)
    _download_first(links)


def test_misiones_descarga() -> None:
    if not TEST_RETPER_MISIONES_CUIT or not TEST_RETPER_MISIONES_CLAVE:
        raise ValueError(
            "Credenciales Misiones no configuradas. "
            "Revisa TEST_RETPER_MISIONES_CUIT y TEST_RETPER_MISIONES_CLAVE en .env"
        )

    payload = {
        "cuit_representante": TEST_RETPER_MISIONES_CUIT,
        "clave_representante": TEST_RETPER_MISIONES_CLAVE,
        "cuit_representado": TEST_RETPER_MISIONES_CUIT,
        "denominacion": "Test Misiones",
        "desde": "202601",
        "hasta": "202601",
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(
        BASE_URL + "api/v1/retenciones_percepciones_iibb/misiones/consulta",
        headers=HEADERS, json=payload, timeout=180,
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_ret_per(data)
    _download_first(links)


if __name__ == "__main__":
    test_arba_descarga()
    test_agip_descarga()
    test_misiones_descarga()
