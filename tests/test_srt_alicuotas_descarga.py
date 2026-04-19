import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mrbot_app.srt_alicuotas import normalize_srt_consulta_rows, save_consultas_json_by_cuit, save_consolidated_excel


load_dotenv()

BASE_URL = os.getenv("URL", "https://api-bots.mrbot.com.ar/").rstrip("/") + "/"
API_KEY = os.getenv("API_KEY", "")
MAIL = os.getenv("SRT_TEST_MAIL", os.getenv("MAIL", ""))

OUT_DIR = os.path.join("descargas", "SRT")
RAW_RESPONSE_PATH = os.path.join(OUT_DIR, "response_srt_alicuotas_abp.json")

SRT_TEST_BODY = {
    "cuit_login": "CUIT",
    "clave": "CLAVE",
    "cuits_consulta": [
        "20147130202",
        "20374730429",
        "30568711420",
    ],
    "proxy_request": False,
}


def _build_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    if MAIL:
        headers["email"] = MAIL
    return headers


def test_srt_alicuotas_abp_response_and_outputs() -> None:
    if not MAIL:
        raise ValueError("No hay MAIL configurado para headers. Define MAIL o SRT_TEST_MAIL en .env")

    os.makedirs(OUT_DIR, exist_ok=True)

    url = BASE_URL + "api/v1/srt/alicuotas/consulta"
    response = requests.post(url, headers=_build_headers(), json=SRT_TEST_BODY, timeout=180)

    assert response.status_code == 200, f"HTTP {response.status_code}: {response.text[:600]}"

    data = response.json()

    with open(RAW_RESPONSE_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)

    assert os.path.exists(RAW_RESPONSE_PATH), "No se guardo el JSON bruto de respuesta."

    consultas = data.get("consultas")
    assert isinstance(consultas, list), "La respuesta no contiene una lista en 'consultas'."
    assert "consultas_ok" in data, "Falta 'consultas_ok' en respuesta."
    assert "consultas_error" in data, "Falta 'consultas_error' en respuesta."

    json_paths = save_consultas_json_by_cuit(consultas, OUT_DIR)
    if consultas:
        assert json_paths, "No se generaron JSON individuales por contribuyente."
        for path in json_paths:
            assert os.path.exists(path), f"No existe JSON individual: {path}"

    rows = normalize_srt_consulta_rows(consultas)
    excel_path = save_consolidated_excel(rows, OUT_DIR, filename="srt_alicuotas_consolidado_abp.xlsx")
    if rows:
        assert excel_path is not None, "No se genero ruta de Excel consolidado."
        assert os.path.exists(excel_path), f"No existe Excel consolidado: {excel_path}"


def _run_all() -> None:
    test_srt_alicuotas_abp_response_and_outputs()


if __name__ == "__main__":
    _run_all()
