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

# Credenciales de testing desde .env
TEST_CUIT_REP_1 = os.getenv("TEST_CUIT_REP_1", "")
TEST_CLAVE_REP_1 = os.getenv("TEST_CLAVE_REP_1", "")
TEST_CUIT_REPRESENTADO_1 = os.getenv("TEST_CUIT_REPRESENTADO_1", "")
TEST_DENOMINACION_1 = os.getenv("TEST_DENOMINACION_1", "")

TEST_CUIT_REP_2 = os.getenv("TEST_CUIT_REP_2", "")
TEST_CLAVE_REP_2 = os.getenv("TEST_CLAVE_REP_2", "")
TEST_CUIT_REPRESENTADO_2 = os.getenv("TEST_CUIT_REPRESENTADO_2", "")
TEST_DENOMINACION_2 = os.getenv("TEST_DENOMINACION_2", "")

TEST_CUIT_REP_3 = os.getenv("TEST_CUIT_REP_3", "")
TEST_CLAVE_REP_3 = os.getenv("TEST_CLAVE_REP_3", "")
TEST_CUIT_REPRESENTADO_3 = os.getenv("TEST_CUIT_REPRESENTADO_3", "")
TEST_DENOMINACION_3 = os.getenv("TEST_DENOMINACION_3", "")

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


def _links_mis_retenciones(data: dict) -> list[str]:
    links: list[str] = []
    for item in data.get("archivos") or []:
        if isinstance(item, dict) and item.get("url_minio"):
            links.append(item["url_minio"])
    return links


def _links_sifere(data: dict) -> list[str]:
    links: list[str] = []
    for item in data.get("archivos_minio") or []:
        if not isinstance(item, dict):
            continue
        for value in item.values():
            if isinstance(value, str) and value.strip().startswith("http"):
                links.append(value)
    return links


def _links_ddjj(data: dict) -> list[str]:
    links: list[str] = []
    for item in data.get("archivos") or []:
        if not isinstance(item, dict):
            continue
        for key in ("link_minio_ddjj_excel", "link_minio_dj", "link_minio_vep"):
            url = item.get(key)
            if url:
                links.append(url)
    return links


def _links_mis_facilidades(data: dict) -> list[str]:
    links: list[str] = []
    for item in data.get("archivos") or []:
        if not isinstance(item, dict):
            continue
        for key in (
            "tablas_excel_url_minio",
            "pagos_pdf_url_minio",
            "cuotas_pdf_url_minio",
            "obligaciones_pdf_url_minio",
        ):
            url = item.get(key)
            if url:
                links.append(url)
    return links


def _links_aportes(data: dict) -> list[str]:
    url = data.get("archivo_historico_minio_url")
    return [url] if url else []


def test_mis_retenciones_descarga() -> None:
    if not TEST_CUIT_REP_1 or not TEST_CLAVE_REP_1:
        raise ValueError("Credenciales de test no configuradas. Revisa TEST_CUIT_REP_1 y TEST_CLAVE_REP_1 en .env")
    
    payload = {
        "cuit_representante": TEST_CUIT_REP_1,
        "clave_representante": TEST_CLAVE_REP_1,
        "cuit_representado": TEST_CUIT_REPRESENTADO_1,
        "denominacion": TEST_DENOMINACION_1,
        "desde": "01/11/2025",
        "hasta": "30/11/2025",
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(BASE_URL + "api/v1/mis_retenciones/consulta", headers=HEADERS, json=payload, timeout=180)
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_mis_retenciones(data)
    _download_first(links)


def test_sifere_descarga() -> None:
    if not TEST_CUIT_REP_2 or not TEST_CLAVE_REP_2:
        raise ValueError("Credenciales de test no configuradas. Revisa TEST_CUIT_REP_2 y TEST_CLAVE_REP_2 en .env")
    
    payload = {
        "cuit_representante": TEST_CUIT_REP_2,
        "clave_representante": TEST_CLAVE_REP_2,
        "cuit_representado": TEST_CUIT_REPRESENTADO_2,
        "periodo": "202401",
        "representado_nombre": TEST_DENOMINACION_2,
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(BASE_URL + "api/v1/sifere/consulta", headers=HEADERS, json=payload, timeout=180)
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_sifere(data)
    _download_first(links)


def test_declaracion_en_linea_descarga() -> None:
    if not TEST_CUIT_REP_1 or not TEST_CLAVE_REP_1:
        raise ValueError("Credenciales de test no configuradas. Revisa TEST_CUIT_REP_1 y TEST_CLAVE_REP_1 en .env")
    
    payload = {
        "cuit_representante": TEST_CUIT_REP_1,
        "clave_representante": TEST_CLAVE_REP_1,
        "cuit_representado": TEST_CUIT_REPRESENTADO_1,
        "representado_nombre": TEST_DENOMINACION_1,
        "periodo_desde": "202511",
        "periodo_hasta": "202511",
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(BASE_URL + "api/v1/declaracion-en-linea/consulta", headers=HEADERS, json=payload, timeout=180)
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_ddjj(data)
    _download_first(links)


def test_mis_facilidades_descarga() -> None:
    if not TEST_CUIT_REP_3 or not TEST_CLAVE_REP_3:
        raise ValueError("Credenciales de test no configuradas. Revisa TEST_CUIT_REP_3 y TEST_CLAVE_REP_3 en .env")
    
    payload = {
        "cuit_login": TEST_CUIT_REP_3,
        "clave": TEST_CLAVE_REP_3,
        "cuit_representado": TEST_CUIT_REPRESENTADO_3,
        "denominacion": TEST_DENOMINACION_3,
        "carga_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(BASE_URL + "api/v1/mis_facilidades/consulta", headers=HEADERS, json=payload, timeout=180)
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_mis_facilidades(data)
    _download_first(links)


def test_aportes_en_linea_descarga() -> None:
    # Este test usa el mismo CUIT como login y representado
    test_cuit = os.getenv("TEST_CUIT_APORTES", TEST_CUIT_REP_3)
    test_clave = os.getenv("TEST_CLAVE_APORTES", TEST_CLAVE_REP_3)
    
    if not test_cuit or not test_clave:
        raise ValueError("Credenciales de test no configuradas. Revisa TEST_CUIT_APORTES y TEST_CLAVE_APORTES en .env")
    
    payload = {
        "cuit_login": test_cuit,
        "clave": test_clave,
        "cuit_representado": test_cuit,
        "archivo_historico_b64": False,
        "archivo_historico_minio": True,
        "proxy_request": False,
    }
    resp = requests.post(BASE_URL + "api/v1/aportes-en-linea/consulta", headers=HEADERS, json=payload, timeout=180)
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    links = _links_aportes(data)
    _download_first(links)


def _run_all() -> None:
    test_mis_retenciones_descarga()
    test_sifere_descarga()
    test_declaracion_en_linea_descarga()
    test_mis_facilidades_descarga()
    test_aportes_en_linea_descarga()


if __name__ == "__main__":
    _run_all()
