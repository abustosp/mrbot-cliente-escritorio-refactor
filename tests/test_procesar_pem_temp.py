import os
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mrbot_app.config import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_EMAIL
from mrbot_app.procesar_pem import discover_pem_files, process_single_pem


load_dotenv(".env", override=True)

SOURCE_FOLDER = Path("/home/abp/Desktop/pem-ejemplo/08-05-2024 al 14-05-2024")


def _validate_output_files(outputs: dict) -> None:
    for key in ("json", "xml", "xlsx"):
        out_path = outputs.get(key)
        assert out_path, f"Falta path de salida para {key}"
        assert os.path.exists(out_path), f"No existe archivo de salida {key}: {out_path}"
        assert os.path.getsize(out_path) > 0, f"Archivo de salida vacio {key}: {out_path}"


def test_procesar_pem_temp_samples() -> None:
    """
    Test temporal de integración para procesar PEM de ejemplo.
    Copia los .pem a una carpeta temporal para no alterar archivos de origen.
    """
    assert SOURCE_FOLDER.exists(), f"No existe carpeta de muestras: {SOURCE_FOLDER}"

    source_files = discover_pem_files(SOURCE_FOLDER, include_subdirs=True)
    assert source_files, "No se encontraron archivos .pem en la carpeta de muestras."

    with tempfile.TemporaryDirectory(prefix="mrbot-pem-test-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        for source_file in source_files:
            shutil.copy2(source_file, tmpdir_path / source_file.name)

        tmp_files = discover_pem_files(tmpdir_path, include_subdirs=True)
        assert len(tmp_files) == len(source_files), "La cantidad de PEM copiados no coincide."

        for pem_file in tmp_files:
            result = process_single_pem(
                pem_file,
                base_url=DEFAULT_BASE_URL,
                api_key=DEFAULT_API_KEY,
                email=DEFAULT_EMAIL,
            )
            assert result.get("success"), f"Fallo procesando {pem_file.name}: {result.get('error')}"
            _validate_output_files(result.get("outputs", {}))


if __name__ == "__main__":
    test_procesar_pem_temp_samples()
    print("OK - test_procesar_pem_temp_samples")
