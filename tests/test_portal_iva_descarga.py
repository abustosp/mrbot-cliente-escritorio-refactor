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

TEST_CUIT_PORTAL_IVA = os.getenv("TEST_CUIT_PORTAL_IVA", "")
TEST_CLAVE_PORTAL_IVA = os.getenv("TEST_CLAVE_PORTAL_IVA", "")
TEST_CUIT_REPRESENTADO_PORTAL_IVA = os.getenv("TEST_CUIT_REPRESENTADO_PORTAL_IVA", "")
TEST_DENOMINACION_PORTAL_IVA = os.getenv("TEST_DENOMINACION_PORTAL_IVA", "")
TEST_PERIODO_PORTAL_IVA = os.getenv("TEST_PERIODO_PORTAL_IVA", "")

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


def _links_portal_iva(data: dict) -> list[str]:
    links: list[str] = []
    for item in data.get("archivos") or []:
        if isinstance(item, dict) and item.get("url_minio"):
            links.append(item["url_minio"])
    return links


def test_portal_iva_descarga() -> None:
    if not TEST_CUIT_PORTAL_IVA or not TEST_CLAVE_PORTAL_IVA:
        raise ValueError(
            "Credenciales de test no configuradas. "
            "Revisa TEST_CUIT_PORTAL_IVA y TEST_CLAVE_PORTAL_IVA en .env"
        )

    payload = {
        "cuit_representante": TEST_CUIT_PORTAL_IVA,
        "clave_representante": TEST_CLAVE_PORTAL_IVA,
        "cuit_representado": TEST_CUIT_REPRESENTADO_PORTAL_IVA,
        "denominacion": TEST_DENOMINACION_PORTAL_IVA,
        "periodo": TEST_PERIODO_PORTAL_IVA,
        "operaciones_ng_o_e": False,
        "prorrateo_global": False,
        "prorrateo_asignacion_directa": False,
        "prorrateo_ambos": False,
        "importacion_definitiva_bienes": False,
        "importacion_servicios": False,
        "regimen_turiva": False,
        "bienes_usados": False,
        "ninguna_anteriores": True,
        "descarga_csv_ventas": True,
        "descarga_csv_compras": True,
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(
        BASE_URL + "api/v1/portal_iva/consulta",
        headers=HEADERS,
        json=payload,
        timeout=180,
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_portal_iva(data)
    _download_first(links)


if __name__ == "__main__":
    test_portal_iva_descarga()
