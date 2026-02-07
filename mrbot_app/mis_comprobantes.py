import csv
import json
import os
import zipfile
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

from mrbot_app.consulta import descargar_archivos_minio_concurrente
from mrbot_app.helpers import format_date_str


load_dotenv(".env", override=True)

root_url = os.getenv("URL", "https://api-bots.mrbot.com.ar")
mail = os.getenv("MAIL")
api_key = os.getenv("API_KEY")

FALLBACK_BASE_DIR = os.path.join("descargas", "mis_compobantes")


def _normalize_key(key: str) -> str:
    """
    Normaliza nombres de columnas/keys para admitir variaciones (tildes, espacios, mayúsculas).
    """
    if key is None:
        return ""
    translation_table = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return (
        str(key)
        .strip()
        .translate(translation_table)
        .lower()
        .replace(" ", "_")
    )


def _to_bool(value: Any, default: bool = False) -> bool:
    """
    Convierte varios tipos de valores a booleanos aceptando si/yes/1/true.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "si", "sí", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return default


def _format_date(value: Any) -> str:
    return format_date_str(value)


def _sanitize_path_fragment(text: str, fallback: str = "descarga") -> str:
    clean = "".join(c for c in str(text) if c.isalnum() or c in (" ", "-", "_")).strip()
    clean = clean.replace(" ", "_")
    return clean or fallback


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


def _log_start(title: str, details: Optional[Dict[str, Any]] = None, log_fn: Optional[Callable[[str], None]] = None) -> None:
    detail_text = ""
    if details:
        detail_text = " | " + json.dumps(details, ensure_ascii=False, default=str)
    _log_message(f"INICIADOR: {title}{detail_text}", log_fn)


def _log_separator(label: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    sep = "-" * 60
    _log_message(f"{sep}\nCONTRIBUYENTE: {label}\n{sep}", log_fn)


def consulta_mc(
    desde,
    hasta,
    cuit_inicio_sesion,
    representado_nombre,
    representado_cuit,
    contrasena,
    descarga_emitidos: bool,
    descarga_recibidos: bool,
    carga_minio: bool = True,
    carga_json: bool = True,
    b64: bool = False,
    proxy_request: Optional[bool] = None,
    log_fn: Optional[Callable[[str], None]] = None,
):
    """
    Consulta de Mis Comprobantes usando la API v1.

    Args:
        desde: Fecha inicio en formato DD/MM/YYYY
        hasta: Fecha fin en formato DD/MM/YYYY
        cuit_inicio_sesion: CUIT del representante
        representado_nombre: Nombre del representado
        representado_cuit: CUIT del representado
        contrasena: Contraseña fiscal
        descarga_emitidos: True para descargar emitidos
        descarga_recibidos: True para descargar recibidos
        carga_minio: True para subir archivos a MinIO y obtener URLs
        carga_json: True para recibir datos en JSON
        b64: True para recibir archivos en base64
        proxy_request: True/False/None para usar proxy
        log_fn: Funcion opcional para registrar logs (UI/CLI)

    Returns:
        Dict con la respuesta de la API
    """
    url = root_url.rstrip("/") + "/api/v1/mis_comprobantes/consulta"
    desde = _format_date(desde)
    hasta = _format_date(hasta)

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "email": mail,
    }

    payload = {
        "desde": desde,
        "hasta": hasta,
        "cuit_inicio_sesion": cuit_inicio_sesion,
        "representado_nombre": representado_nombre,
        "representado_cuit": representado_cuit,
        "contrasena": contrasena,
        "descarga_emitidos": descarga_emitidos,
        "descarga_recibidos": descarga_recibidos,
        "carga_minio": carga_minio,
        "carga_json": carga_json,
        "b64": b64
    }

    if proxy_request is not None:
        payload["proxy_request"] = proxy_request

    safe_payload = dict(payload)
    if "contrasena" in safe_payload:
        safe_payload["contrasena"] = "***"
    _log_request(safe_payload, log_fn)

    response = requests.post(url, headers=headers, json=payload)
    http_status = response.status_code

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
        _log_response(http_status, data, log_fn)
        return data

    _log_response(http_status, data, log_fn)
    return data


def save_to_csv(data, filename):
    """Guarda datos en formato CSV."""
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        if data:
            fieldnames = data[0].keys()
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(data)


def leer_csv_con_encoding(archivo, log_fn: Optional[Callable[[str], None]] = None):
    """
    Intenta leer un archivo CSV con diferentes encodings.
    Primero intenta cp1252, luego utf-8.
    """
    encodings = ["cp1252", "utf-8"]

    for encoding in encodings:
        try:
            with open(archivo, "r", encoding=encoding) as f:
                return csv.DictReader(f, delimiter="|")
        except UnicodeDecodeError:
            continue
        except Exception as e:
            _log_info(f"Advertencia: no se pudo leer archivo con encoding {encoding}: {e}", log_fn)
            continue

    raise ValueError(
        f"No se pudo leer el archivo {archivo} con los encodings disponibles (cp1252, utf-8)"
    )


def extraer_csv_de_zip(zip_path, destino_csv, log_fn: Optional[Callable[[str], None]] = None):
    """
    Extrae el único archivo CSV de un ZIP y lo guarda con el nombre especificado.

    Args:
        zip_path: Ruta al archivo ZIP descargado
        destino_csv: Ruta completa donde guardar el CSV extraído

    Returns:
        bool: True si se extrajo exitosamente, False en caso contrario
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            archivos_en_zip = zip_ref.namelist()

            if not archivos_en_zip:
                _log_error(f"El ZIP {zip_path} esta vacio", log_fn)
                return False

            archivo_csv = None
            for archivo in archivos_en_zip:
                if archivo.lower().endswith(".csv"):
                    archivo_csv = archivo
                    break

            if not archivo_csv:
                archivo_csv = archivos_en_zip[0]

            contenido = zip_ref.read(archivo_csv)

            os.makedirs(os.path.dirname(destino_csv), exist_ok=True)
            with open(destino_csv, "wb") as f:
                f.write(contenido)

            _log_info(f"Extraido: {os.path.basename(destino_csv)}", log_fn)
            return True

    except zipfile.BadZipFile:
        _log_error(f"{zip_path} no es un archivo ZIP valido", log_fn)
        return False
    except Exception as e:
        _log_error(f"Error al extraer ZIP: {e}", log_fn)
        return False


def crear_directorio_seguro(
    ruta,
    nombre_representado: str,
    representado_cuit: Optional[str] = None,
    nombre_archivo: Optional[str] = None,
    cuit_representante: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
):
    """
    Intenta crear un directorio. Si falla, retorna una ruta alternativa.

    Args:
        ruta: Ruta deseada para el directorio
        nombre_representado: Nombre del representado para usar en fallback
        representado_cuit: CUIT del representado para construir fallback específico
        nombre_archivo: Nombre base para carpeta de fallback

    Returns:
        str: Ruta del directorio (original o fallback)
    """
    try:
        ruta_deseada = ruta.strip() if isinstance(ruta, str) else ""
        if ruta_deseada:
            os.makedirs(ruta_deseada, exist_ok=True)
            test_file = os.path.join(ruta_deseada, ".test_write")
            try:
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
                _log_info(f"Directorio verificado: {ruta_deseada}", log_fn)
                return ruta_deseada
            except Exception:
                raise PermissionError(f"No se puede escribir en {ruta_deseada}")
        else:
            raise ValueError("Ruta no especificada")
    except Exception as e:
        cuit_limpio = _sanitize_path_fragment(cuit_representante or representado_cuit, "sin_cuit")
        nombre_limpio = _sanitize_path_fragment(nombre_archivo or nombre_representado, "descarga")
        fallback_dir = os.path.join(FALLBACK_BASE_DIR, cuit_limpio, nombre_limpio)
        try:
            os.makedirs(fallback_dir, exist_ok=True)
            _log_info(f"Advertencia: no se pudo usar {ruta}: {e}", log_fn)
            _log_info(f"Usando directorio alternativo: {fallback_dir}", log_fn)
            return fallback_dir
        except Exception as e2:
            _log_error(f"Error creando directorio fallback: {e2}", log_fn)
            os.makedirs("Descargas", exist_ok=True)
            _log_info("Usando directorio por defecto: ./Descargas", log_fn)
            return "Descargas"


def consulta_mc_csv(
    excel_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    log_start: bool = True,
):
    """
    Procesa el archivo Excel (o CSV legacy) de consultas masivas de Mis Comprobantes.

    Lee el archivo 'Descarga-Mis-Comprobantes.xlsx' (o el CSV legado si existiera) y procesa cada fila que tenga
    'Procesar' = 'si'. Si no se encuentra, usa automáticamente `./ejemplos_api/mis_comprobantes.xlsx`
    como plantilla de prueba. Para cada consulta:
    - Realiza la consulta a la API
    - Descarga archivos ZIP desde MinIO
    - Extrae los CSV de los ZIPs descargados

    Args:
        excel_path: Ruta opcional al Excel a procesar (por ejemplo, './ejemplos_api/mis_comprobantes.xlsx').
        progress_callback: Funcion opcional que recibe (current, total) para actualizar progreso.
        log_fn: Funcion opcional para registrar logs (UI/CLI).
        log_start: True para emitir un iniciador de proceso.

    El archivo Excel se lee con pandas. Si no existe, se intenta usar el CSV con cp1252 y luego utf-8.
    """
    datos = []
    origen = None
    excel_default = "Descarga-Mis-Comprobantes.xlsx"
    excel_example = os.path.join("ejemplos_api", "mis_comprobantes.xlsx")
    csv_path = "Descarga-Mis-Comprobantes.csv"

    def _to_str(value: Any) -> str:
        return "" if value is None else str(value).strip()

    def _normalize_row_keys(row: Dict[str, Any]) -> Dict[str, Any]:
        return {_normalize_key(k): v for k, v in row.items()}

    excel_candidates = [excel_path] if excel_path else []
    excel_candidates.extend([excel_default, excel_example])

    for candidate in excel_candidates:
        if not candidate:
            continue
        if not os.path.exists(candidate):
            continue
        try:
            df = pd.read_excel(candidate, dtype=str).fillna("")
            df.columns = [_normalize_key(c) for c in df.columns]
            datos = df.to_dict(orient="records")
            origen = candidate
            _log_info(f"Excel leido correctamente: {candidate}", log_fn)
            break
        except Exception as e:
            _log_error(f"No se pudo leer Excel '{candidate}': {e}", log_fn)

    if not datos:
        try:
            with open(csv_path, "r", encoding="cp1252") as f:
                datos = [_normalize_row_keys(row) for row in csv.DictReader(f, delimiter="|")]
            _log_info("CSV leido con encoding cp1252 (modo compatibilidad)", log_fn)
        except UnicodeDecodeError:
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    datos = [_normalize_row_keys(row) for row in csv.DictReader(f, delimiter="|")]
                _log_info("CSV leido con encoding utf-8 (modo compatibilidad)", log_fn)
            except Exception as e:
                _log_error(f"Error al leer CSV: {e}", log_fn)
                return
        except FileNotFoundError:
            _log_error(
                f"No se encontro el archivo '{excel_default}' ni el CSV de respaldo '{csv_path}'. "
                f"Tambien se intento '{excel_example}'.",
                log_fn,
            )
            return
        except Exception as e:
            _log_error(f"Error al leer CSV: {e}", log_fn)
            return

    datos_normalizados = [{k: _to_str(v) for k, v in _normalize_row_keys(dato).items()} for dato in datos]

    if not datos_normalizados:
        _log_info("El archivo de configuracion no contiene filas para procesar", log_fn)
        if progress_callback:
            progress_callback(0, 0)
        return

    filas_a_procesar = [dato for dato in datos_normalizados if _to_bool(dato.get("procesar", ""), default=False)]
    if not filas_a_procesar:
        _log_info("El archivo de configuracion no contiene filas para procesar", log_fn)

    total_filas = len(filas_a_procesar)
    if log_start:
        source = origen or excel_path or excel_default
        _log_start("Mis Comprobantes", {"modo": "masivo", "archivo": source, "filas": total_filas}, log_fn)
    if progress_callback:
        progress_callback(0, total_filas)

    errores = []
    errores2 = []

    for idx, dato in enumerate(filas_a_procesar, start=1):
        desde = _format_date(dato.get("desde", ""))
        hasta = _format_date(dato.get("hasta", ""))
        cuit_inicio_sesion = _to_str(
            dato.get("cuit_inicio_sesion")
            or dato.get("cuit_inicio")
            or dato.get("cuit_login")
            or dato.get("cuit_representante", "")
        )
        representado_nombre = (
            _to_str(
                dato.get("representado_nombre")
                or dato.get("nombre_representado")
                or dato.get("representado")
                or dato.get("nombre", "")
            )
            or "Representado"
        )
        representado_cuit = _to_str(
            dato.get("representado_cuit")
            or dato.get("cuit_representado")
            or dato.get("representadocuit")
            or dato.get("cuit", "")
        )
        contrasena = _to_str(dato.get("contrasena") or dato.get("clave") or dato.get("clave_fiscal", ""))

        descarga_emitidos = _to_bool(dato.get("descarga_emitidos", ""), default=False)
        descarga_recibidos = _to_bool(dato.get("descarga_recibidos", ""), default=False)

        label = f"{representado_nombre} ({representado_cuit})" if representado_cuit else representado_nombre
        _log_separator(label, log_fn)
        _log_info(f"Periodo: {desde} - {hasta}", log_fn)
        _log_info(f"CUIT inicio sesion: {cuit_inicio_sesion}", log_fn)
        _log_info(
            f"Descarga emitidos: {descarga_emitidos} | Descarga recibidos: {descarga_recibidos}",
            log_fn,
        )

        try:
            response = consulta_mc(
                desde,
                hasta,
                cuit_inicio_sesion,
                representado_nombre,
                representado_cuit,
                contrasena,
                descarga_emitidos,
                descarga_recibidos,
                carga_minio=True,
                carga_json=False,
                log_fn=log_fn,
            )

            if not response.get("success", False):
                error_msg = response.get("error", response.get("detail", response.get("message", "Error desconocido")))
                errores2.append(
                    {
                        "request": {
                            "desde": desde,
                            "hasta": hasta,
                            "cuit_inicio_sesion": cuit_inicio_sesion,
                            "representado_nombre": representado_nombre,
                            "representado_cuit": representado_cuit,
                            "descarga_emitidos": descarga_emitidos,
                            "descarga_recibidos": descarga_recibidos,
                        },
                        "error": str(error_msg),
                    }
                )
                _log_error(f"Error en la consulta: {error_msg}", log_fn)
                if progress_callback:
                    progress_callback(idx, total_filas)
                continue

            if "error" in response and response["error"]:
                error_list = response["error"]
                if isinstance(error_list, list) and error_list:
                    _log_info(f"Advertencia(s): {', '.join(error_list)}", log_fn)
                elif error_list:
                    _log_info(f"Advertencia: {error_list}", log_fn)

            _log_info(f"Claves en response: {list(response.keys())}", log_fn)

            archivos_a_descargar = []
            archivos_info = []

            if descarga_emitidos:
                ubicacion_deseada = _to_str(dato.get("ubicacion_emitidos", ""))
                nombre_emitidos = _to_str(dato.get("nombre_emitidos", "")) or "Emitidos"

                ubicacion_emitidos = crear_directorio_seguro(
                    ubicacion_deseada,
                    representado_nombre,
                    representado_cuit=representado_cuit,
                    nombre_archivo=nombre_emitidos,
                    cuit_representante=cuit_inicio_sesion,
                    log_fn=log_fn,
                )
                _log_info(f"Carpeta emitidos: {ubicacion_emitidos}", log_fn)

                _log_info("Emitidos: verificando campo MinIO", log_fn)
                _log_info(
                    "Campo 'mis_comprobantes_emitidos_url_minio' existe: "
                    f"{'mis_comprobantes_emitidos_url_minio' in response}",
                    log_fn,
                )
                if "mis_comprobantes_emitidos_url_minio" in response:
                    url = response["mis_comprobantes_emitidos_url_minio"]
                    _log_info(f"URL: {url[:100] if url else 'None'}...", log_fn)

                if "mis_comprobantes_emitidos_url_minio" in response and response["mis_comprobantes_emitidos_url_minio"]:
                    zip_path = os.path.join(ubicacion_emitidos, f"{nombre_emitidos}_temp.zip")
                    csv_path = os.path.join(ubicacion_emitidos, f"{nombre_emitidos}.csv")

                    archivos_a_descargar.append(
                        {
                            "url": response["mis_comprobantes_emitidos_url_minio"],
                            "destino": zip_path,
                        }
                    )

                    archivos_info.append(
                        {
                            "zip": zip_path,
                            "csv": csv_path,
                            "tipo": "emitidos",
                        }
                    )
                    _log_info("Agregado a lista de descarga", log_fn)
                else:
                    _log_info("No hay URL de MinIO para emitidos", log_fn)

            if descarga_recibidos:
                ubicacion_deseada = _to_str(dato.get("ubicacion_recibidos", ""))
                nombre_recibidos = _to_str(dato.get("nombre_recibidos", "")) or "Recibidos"

                ubicacion_recibidos = crear_directorio_seguro(
                    ubicacion_deseada,
                    representado_nombre,
                    representado_cuit=representado_cuit,
                    nombre_archivo=nombre_recibidos,
                    cuit_representante=cuit_inicio_sesion,
                    log_fn=log_fn,
                )
                _log_info(f"Carpeta recibidos: {ubicacion_recibidos}", log_fn)

                _log_info("Recibidos: verificando campo MinIO", log_fn)
                _log_info(
                    "Campo 'mis_comprobantes_recibidos_url_minio' existe: "
                    f"{'mis_comprobantes_recibidos_url_minio' in response}",
                    log_fn,
                )
                if "mis_comprobantes_recibidos_url_minio" in response:
                    url = response["mis_comprobantes_recibidos_url_minio"]
                    _log_info(f"URL: {url[:100] if url else 'None'}...", log_fn)

                if "mis_comprobantes_recibidos_url_minio" in response and response["mis_comprobantes_recibidos_url_minio"]:
                    zip_path = os.path.join(ubicacion_recibidos, f"{nombre_recibidos}_temp.zip")
                    csv_path = os.path.join(ubicacion_recibidos, f"{nombre_recibidos}.csv")

                    archivos_a_descargar.append(
                        {
                            "url": response["mis_comprobantes_recibidos_url_minio"],
                            "destino": zip_path,
                        }
                    )

                    archivos_info.append(
                        {
                            "zip": zip_path,
                            "csv": csv_path,
                            "tipo": "recibidos",
                        }
                    )
                    _log_info("Agregado a lista de descarga", log_fn)
                else:
                    _log_info("No hay URL de MinIO para recibidos", log_fn)

            if archivos_a_descargar:
                _log_info(f"Descargando {len(archivos_a_descargar)} archivo(s) desde MinIO...", log_fn)
                resultados_descarga = descargar_archivos_minio_concurrente(archivos_a_descargar, log_fn=log_fn)

                _log_info("Extrayendo archivos CSV de los ZIPs...", log_fn)
                for info in archivos_info:
                    if os.path.exists(info["zip"]):
                        if extraer_csv_de_zip(info["zip"], info["csv"], log_fn=log_fn):
                            try:
                                os.remove(info["zip"])
                            except Exception:
                                pass
                        else:
                            _log_error(f"No se pudo extraer {info['tipo']}", log_fn)
                    else:
                        _log_error(f"No se descargo el ZIP para {info['tipo']}", log_fn)

                exitosos = sum(1 for r in resultados_descarga if r["success"])
                fallidos = len(resultados_descarga) - exitosos
                _log_info(f"Descargas completadas: {exitosos} exitosas, {fallidos} fallidas", log_fn)
            else:
                _log_info("No hay archivos de MinIO para descargar", log_fn)

            _log_info(f"Procesamiento completado para {representado_nombre}", log_fn)
            if progress_callback:
                progress_callback(idx, total_filas)

        except Exception as e:
            error_msg = f"Error en {representado_nombre} - {representado_cuit}: {str(e)}"
            errores.append(error_msg)
            _log_error(error_msg, log_fn)
            if progress_callback:
                progress_callback(idx, total_filas)

    if errores:
        with open("errores.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(errores))
        _log_info(f"Se registraron {len(errores)} errores en errores.txt", log_fn)

    if errores2:
        with open("errores.json", "w", encoding="utf-8") as f:
            json.dump(errores2, f, ensure_ascii=False, indent=2)
        _log_info(f"Se registraron {len(errores2)} errores de API en errores.json", log_fn)

    _log_message(f"{'-' * 60}\nProcesamiento masivo finalizado\n{'-' * 60}", log_fn)

    try:
        from tkinter import messagebox

        total_procesados = len(filas_a_procesar)
        exitosos = total_procesados - len(errores) - len(errores2)

        mensaje = "Procesamiento completado\n\n"
        mensaje += f"Total procesados: {total_procesados}\n"
        mensaje += f"Exitosos: {exitosos}\n"

        if errores:
            mensaje += f"Errores de ejecución: {len(errores)}\n"
        if errores2:
            mensaje += f"Errores de API: {len(errores2)}\n"

        if errores or errores2:
            mensaje += "\nRevisa los archivos de errores para más detalles."
            messagebox.showwarning("Procesamiento Finalizado", mensaje)
        else:
            mensaje += "\n¡Todos los archivos se descargaron correctamente!"
            messagebox.showinfo("Procesamiento Exitoso", mensaje)
    except ImportError:
        pass
