import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from mrbot_app.consulta import descargar_archivo_minio
from mrbot_app.helpers import get_unique_filename


def sanitize_identifier(value: str, fallback: str = "desconocido") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", (value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def _ensure_extension(name: str, url: str) -> str:
    if "." in name:
        return name
    ext = os.path.splitext(urlparse(url).path)[1]
    if ext:
        return f"{name}{ext}"
    return name


def build_link(url: str, filename_hint: Optional[str], fallback_prefix: str, index: int) -> Optional[Dict[str, str]]:
    if not isinstance(url, str):
        return None
    clean_url = url.strip()
    if not clean_url.lower().startswith("http"):
        return None
    base = unquote(os.path.basename(urlparse(clean_url).path))
    name = base.strip()
    if not name:
        hint = (filename_hint or "").strip() or f"{fallback_prefix}_{index}"
        name = _ensure_extension(hint, clean_url)
    return {"url": clean_url, "filename": name}


def is_writable_dir(path: str) -> bool:
    try:
        if not path:
            return False
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".mrbot_write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def prepare_download_dir(module_name: str, desired_path: str, cuit_repr: str) -> Tuple[Optional[str], List[str]]:
    messages: List[str] = []
    target = (desired_path or "").strip()
    if target:
        if is_writable_dir(target):
            return target, messages
        messages.append(f"No se pudo usar la carpeta indicada '{target}'. Se intentará con la ruta por defecto.")
    fallback = os.path.join("descargas", module_name, sanitize_identifier(cuit_repr or "desconocido"))
    if is_writable_dir(fallback):
        messages.append(f"Usando carpeta por defecto: {fallback}")
        return fallback, messages
    messages.append(f"No se pudo preparar la ruta por defecto '{fallback}'.")
    return None, messages


def download_links(links: List[Dict[str, str]], dest_dir: Optional[str]) -> Tuple[int, List[str]]:
    if not dest_dir:
        return 0, ["No hay ruta de descarga disponible."]
    successes = 0
    errors: List[str] = []
    for link in links:
        url = link.get("url")
        filename = link.get("filename") or "archivo"
        if not url:
            errors.append(f"{filename}: URL vacía")
            continue
        # Use get_unique_filename for collision handling (adds timestamp if needed)
        filename_unique = get_unique_filename(dest_dir, filename)
        target_path = os.path.join(dest_dir, filename_unique)

        res = descargar_archivo_minio(url, target_path)
        if res.get("success"):
            successes += 1
        else:
            errors.append(f"{filename}: {res.get('error') or 'Error al descargar'}")
    return successes, errors


def collect_minio_links(data: Any, fallback_prefix: str) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    def looks_like_download(url: str, key: Optional[str]) -> bool:
        lowered = url.lower()
        if "minio" in lowered:
            return True
        if key and "minio" in key.lower():
            return True
        if lowered.split("?")[0].endswith((".pdf", ".xls", ".xlsx", ".csv", ".zip")):
            return True
        if key and key.lower().endswith(("url", "link")):
            return True
        return False

    def add(url: str, hint: Optional[str]) -> None:
        link = build_link(url, hint, fallback_prefix, len(links) + 1)
        if not link:
            return
        key = (link["url"], link["filename"])
        if key in seen:
            return
        seen.add(key)
        links.append(link)

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    walk(v)
                elif isinstance(v, str):
                    if v.strip().lower().startswith("http") and looks_like_download(v, str(k)):
                        hint = k if isinstance(k, str) and "." in k else None
                        add(v, hint)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, str):
            if obj.strip().lower().startswith("http") and looks_like_download(obj, None):
                add(obj, None)

    walk(data)
    return links
