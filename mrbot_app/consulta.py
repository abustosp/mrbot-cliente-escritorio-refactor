import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv


load_dotenv(".env", override=True)

root_url = os.getenv("URL", "https://api-bots.mrbot.com.ar")
api_key = os.getenv("API_KEY")

# Configuración para descargas concurrentes
MAX_WORKERS = 10


def consulta_requests_restantes(mail: str) -> Dict[str, Any]:
    """
    Consulta las requests restantes del usuario usando la API v1.

    Args:
        mail: Email del usuario

    Returns:
        Dict con información de consultas disponibles
    """
    url = root_url.rstrip("/") + f"/api/v1/user/consultas/{mail}"

    headers = {
        "x-api-key": api_key
    }

    response = requests.get(url, headers=headers)

    try:
        return response.json()
    except ValueError:
        return {
            "success": False,
            "error": f"Respuesta no JSON (HTTP {response.status_code})",
            "http_status": response.status_code,
            "content": response.text[:500],
        }


def descargar_archivo_minio(url: str, destino: str) -> Dict[str, Any]:
    """
    Descarga un archivo desde MinIO.

    Args:
        url: URL del archivo en MinIO
        destino: Ruta local donde guardar el archivo

    Returns:
        Dict con información del resultado de la descarga
    """
    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        os.makedirs(os.path.dirname(destino), exist_ok=True)

        with open(destino, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return {
            "success": True,
            "url": url,
            "destino": destino,
            "size": os.path.getsize(destino),
        }
    except Exception as e:
        return {
            "success": False,
            "url": url,
            "destino": destino,
            "error": str(e),
        }


def descargar_archivos_minio_concurrente(urls: List[Dict[str, str]], max_workers: int = MAX_WORKERS) -> List[Dict[str, Any]]:
    """
    Descarga múltiples archivos desde MinIO de forma concurrente.

    Args:
        urls: Lista de dicts con "url" y "destino"
        max_workers: Número de workers concurrentes (default: 10)

    Returns:
        Lista de resultados de las descargas
    """
    resultados = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(descargar_archivo_minio, item["url"], item["destino"]): item
            for item in urls
        }

        for future in as_completed(futures):
            resultado = future.result()
            resultados.append(resultado)

            if resultado["success"]:
                print(f"✓ Descargado: {os.path.basename(resultado["destino"])}")
            else:
                print(f"✗ Error descargando: {resultado["destino"]} - {resultado["error"]}")

    return resultados


if __name__ == "__main__":
    pass
