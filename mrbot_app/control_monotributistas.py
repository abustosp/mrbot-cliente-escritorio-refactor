import os
import json
import glob
import re
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List, Tuple
from urllib.parse import urlparse

from openpyxl import load_workbook, Workbook

from mrbot_app.mis_comprobantes import consulta_mc, crear_directorio_seguro, extraer_csv_de_zip, FALLBACK_BASE_DIR
from mrbot_app.consulta import descargar_archivos_minio_concurrente
from mrbot_app.helpers import format_date_str, safe_post, build_headers, ensure_trailing_slash
from mrbot_app.formatos import (
    aplicar_formato_encabezado,
    aplicar_formato_moneda,
    autoajustar_columnas,
    agregar_filtros,
    alinear_columnas
)

NOTAS_DE_CREDITO = [3, 8, 13, 21, 38, 43, 44, 48, 53, 90, 110, 112, 113, 114, 119, 203, 208, 213]

def _log_message(message: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    if log_fn:
        log_fn(message)
    else:
        print(message)

def _log_info(message: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    _log_message(f"INFO: {message}", log_fn)

def _log_error(message: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    _log_message(f"ERROR: {message}", log_fn)

def _normalizar_si_no(valor: Any) -> str:
    if isinstance(valor, str):
        v = valor.lower().strip()
        if v in ["si", "s", "yes", "y", "true", "1"]:
            return "si"
    elif isinstance(valor, (bool, int)):
        if valor:
            return "si"
    return "no"

def procesar_descarga_mc(
    row: pd.Series,
    log_fn: Optional[Callable[[str], None]] = None
) -> None:
    """
    Procesa la descarga de Mis Comprobantes para un contribuyente.
    Utiliza las variables de entorno para credenciales (como consulta_mc original).
    """
    cuit_representante = str(row.get('CUIT_Representante', '')).strip()
    clave_representante = str(row.get('Clave_representante', '')).strip()
    cuit_representado = str(row.get('CUIT_Representado', '')).strip()
    nombre_representado = str(row.get('Denominacion_MC', '')).strip() or "Contribuyente"

    desde = format_date_str(row.get('Desde_MC', ''))
    hasta = format_date_str(row.get('Hasta_MC', ''))

    descarga_MC = _normalizar_si_no(row.get('Descarga_MC'))
    descarga_MC_emitidos = _normalizar_si_no(row.get('Descarga_MC_emitidos'))
    descarga_MC_recibidos = _normalizar_si_no(row.get('Descarga_MC_recibidos'))

    ubicacion_base = str(row.get('Ubicacion_Descarga_MC', '')).strip()

    if descarga_MC != 'si':
        _log_info(f"Saltando descarga MC para CUIT {cuit_representado}", log_fn)
        return

    descargar_emitidos = (descarga_MC_emitidos == 'si')
    descargar_recibidos = (descarga_MC_recibidos == 'si')

    if not descargar_emitidos and not descargar_recibidos:
        _log_info(f"No hay tipos de comprobantes seleccionados para descargar (MC) para {cuit_representado}", log_fn)
        return

    _log_info(f"Procesando MC: {nombre_representado} ({cuit_representado}) - Periodo: {desde} a {hasta}", log_fn)

    try:
        response = consulta_mc(
            desde=desde,
            hasta=hasta,
            cuit_inicio_sesion=cuit_representante,
            representado_nombre=nombre_representado,
            representado_cuit=cuit_representado,
            contrasena=clave_representante,
            descarga_emitidos=descargar_emitidos,
            descarga_recibidos=descargar_recibidos,
            carga_minio=True,
            carga_json=False,
            log_fn=log_fn
        )

        if not response.get("success", False):
            error_msg = response.get("error", response.get("detail", "Error desconocido"))
            _log_error(f"API Error MC: {error_msg}", log_fn)
            return

        # Determine download directory
        if not ubicacion_base:
            ubicacion_base = crear_directorio_seguro(
                "", # Let it fallback
                nombre_representado,
                representado_cuit=cuit_representado,
                cuit_representante=cuit_representante,
                log_fn=log_fn
            )
        else:
             os.makedirs(ubicacion_base, exist_ok=True)

        # Standard structure from external repo: [Base]/extraido/*.csv
        # But we need to download ZIPs first.
        # External repo:
        #   descargas_mc/[CUIT]_[Nombre]/[archivo].zip
        #   descargas_mc/[CUIT]_[Nombre]/extraido/

        # We will follow this structure relative to ubicacion_base

        archivos_a_descargar = []
        extraido_dir = os.path.join(ubicacion_base, "extraido")

        if descargar_emitidos and response.get("mis_comprobantes_emitidos_url_minio"):
            url = response["mis_comprobantes_emitidos_url_minio"]
            zip_path = os.path.join(ubicacion_base, "Emitidos.zip")
            csv_path = os.path.join(extraido_dir, "MCE.csv") # Name might need timestamp/random to avoid collisions if multiple
            # External repo extracts with "unzip_and_rename" logic or similar.
            # Here we use extraer_csv_de_zip which takes dest csv path.
            # To avoid overwriting if running multiple times/types, we might want to preserve name from URL or add suffix.
            # But control logic expects to find CSVs in 'extraido' folder.

            # Using filename from URL
            filename_zip = os.path.basename(urlparse(url).path) or "Emitidos.zip"
            zip_path = os.path.join(ubicacion_base, filename_zip)

            # Name for extracted CSV: same as zip base name
            csv_name = os.path.splitext(filename_zip)[0] + ".csv"
            csv_path = os.path.join(extraido_dir, csv_name)

            archivos_a_descargar.append({"url": url, "destino": zip_path, "csv_destino": csv_path})

        if descargar_recibidos and response.get("mis_comprobantes_recibidos_url_minio"):
            url = response["mis_comprobantes_recibidos_url_minio"]
            filename_zip = os.path.basename(urlparse(url).path) or "Recibidos.zip"
            zip_path = os.path.join(ubicacion_base, filename_zip)
            csv_name = os.path.splitext(filename_zip)[0] + ".csv"
            csv_path = os.path.join(extraido_dir, csv_name)

            archivos_a_descargar.append({"url": url, "destino": zip_path, "csv_destino": csv_path})

        if archivos_a_descargar:
            _log_info(f"Descargando {len(archivos_a_descargar)} archivos MC...", log_fn)
            # Adapt structure for downloader
            download_items = [{"url": item["url"], "destino": item["destino"]} for item in archivos_a_descargar]
            results = descargar_archivos_minio_concurrente(download_items, log_fn=log_fn)

            for item in archivos_a_descargar:
                if os.path.exists(item["destino"]):
                    _log_info(f"Extrayendo CSV de {os.path.basename(item['destino'])}", log_fn)
                    if extraer_csv_de_zip(item["destino"], item["csv_destino"], log_fn):
                        # Optionally remove zip
                        # os.remove(item["destino"])
                        pass

    except Exception as e:
        _log_error(f"Excepcion en proceso MC: {e}", log_fn)


def _is_pdf_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    clean = url.strip()
    if not clean.lower().startswith("http"):
        return False
    lowered = clean.lower()
    if "minio" in lowered:
        return True
    return lowered.split("?")[0].endswith(".pdf")

def _collect_pdf_items(data: Any) -> List[Tuple[str, Dict[str, Any]]]:
    # Reuse logic from RcelWindow
    if not isinstance(data, dict):
        return []
    collected: List[Tuple[str, Dict[str, Any]]] = []

    def _extract_item_pdf_url(item: Dict[str, Any]) -> Optional[str]:
        for key in ("URL_MINIO", "url_minio", "url_pdf", "link_pdf", "url", "link"):
            url = item.get(key)
            if _is_pdf_url(url):
                return str(url).strip()
        for value in item.values():
            if _is_pdf_url(value):
                return str(value).strip()
        return None

    for key in ("facturas_emitidas", "facturas_recibidas", "comprobantes", "facturas"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            url = _extract_item_pdf_url(item)
            if url:
                collected.append((url, item))
    return collected

def procesar_descarga_rcel(
    row: pd.Series,
    config: Tuple[str, str, str],
    log_fn: Optional[Callable[[str], None]] = None
) -> None:
    """
    Procesa la descarga de RCEL.
    config: (base_url, api_key, email)
    """
    base_url, api_key, email = config

    cuit_representante = str(row.get('CUIT_Representante', '')).strip()
    clave_representante = str(row.get('Clave_representante', '')).strip()
    cuit_representado = str(row.get('CUIT_Representado', '')).strip()
    nombre_rcel = str(row.get('Denominacion_RCEL', '')).strip() or "Contribuyente"

    desde = format_date_str(row.get('Desde_RCEL', ''))
    hasta = format_date_str(row.get('Hasta_RCEL', ''))

    descarga_RCEL = _normalizar_si_no(row.get('Descarga_RCEL'))
    ubicacion_base = str(row.get('Ubicacion_Descarga_RCEL', '')).strip()

    if descarga_RCEL != 'si':
        _log_info(f"Saltando descarga RCEL para CUIT {cuit_representado}", log_fn)
        return

    _log_info(f"Procesando RCEL: {nombre_rcel} ({cuit_representado}) - Periodo: {desde} a {hasta}", log_fn)

    url_api = ensure_trailing_slash(base_url) + "api/v1/rcel/consulta"
    headers = build_headers(api_key, email)

    payload = {
        "desde": desde,
        "hasta": hasta,
        "cuit_representante": cuit_representante,
        "nombre_rcel": nombre_rcel,
        "representado_cuit": cuit_representado,
        "clave": clave_representante,
        "b64_pdf": False,
        "minio_upload": True,
    }

    try:
        # Log request (redacted)
        safe_payload = payload.copy()
        safe_payload['clave'] = '***'
        _log_message(f"RCEL Request: {json.dumps(safe_payload, default=str)}", log_fn)

        response = safe_post(url_api, headers, payload)
        data = response.get("data")

        if not response.get("success") and not data:
             _log_error(f"API Error RCEL: {response.get('message', 'Unknown error')}", log_fn)
             return

        # Determine download directory
        if not ubicacion_base:
            # Fallback structure: descargas/RCEL/[CUIT]
            ubicacion_base = os.path.join("descargas", "RCEL", cuit_representado)

        os.makedirs(ubicacion_base, exist_ok=True)

        # Collect PDFs and metadata
        pdf_items = _collect_pdf_items(data)

        if not pdf_items:
            _log_info("No se encontraron comprobantes RCEL con PDF para descargar.", log_fn)
            return

        _log_info(f"Se encontraron {len(pdf_items)} comprobantes RCEL.", log_fn)

        # Download PDFs
        download_items = []
        for url, meta in pdf_items:
            filename = os.path.basename(urlparse(url).path) or "factura.pdf"
            dest = os.path.join(ubicacion_base, filename)
            download_items.append({"url": url, "destino": dest})

        results = descargar_archivos_minio_concurrente(download_items, log_fn=log_fn)

        # Save JSON metadata for each downloaded file
        saved_jsons = 0
        for item in download_items:
            dest_pdf = item["destino"]
            if os.path.exists(dest_pdf):
                # Find metadata
                meta = next((m for u, m in pdf_items if u == item["url"]), None)
                if meta:
                    json_name = os.path.splitext(os.path.basename(dest_pdf))[0] + ".json"
                    json_path = os.path.join(ubicacion_base, json_name)
                    try:
                        with open(json_path, "w", encoding="utf-8") as f:
                            json.dump(meta, f, ensure_ascii=False, indent=2)
                        saved_jsons += 1
                    except Exception as e:
                        _log_error(f"Error guardando JSON {json_name}: {e}", log_fn)

        _log_info(f"Descargas RCEL completadas: {len(results)}. JSONs guardados: {saved_jsons}", log_fn)

    except Exception as e:
        _log_error(f"Excepcion en proceso RCEL: {e}", log_fn)

def leer_archivos_csv_batch(archivos_mc: List[str], log_fn: Optional[Callable[[str], None]] = None) -> pd.DataFrame:
    dataframes = []
    for f in archivos_mc:
        if not os.path.isfile(f):
            continue
        try:
            # Attempt reading with different encodings/separators if needed, but control.py used sep=';', decimal=','
            data = pd.read_csv(f, sep=';', decimal=',', encoding='utf-8-sig')
            if data.empty:
                continue

            data['Archivo'] = os.path.basename(f)

            # Logic from control.py
            partes_archivo = data["Archivo"].str.split("-")
            # control.py assumes format: [Something]-[Something]-[Something]-[Something]-[CUIT]-[Cliente].csv or similar
            # Actually, `get_unique_filename` might have changed the name.
            # But the content of CSV usually has columns that matter.
            # control.py relies on filename to get "Fin CUIT" and "Cliente".
            # "partes_archivo.str[4]" implies at least 5 parts.
            # If our filename doesn't match, this will fail.
            # The CSVs from MC usually have standard names like:
            # "Mis Comprobantes Emitidos - 2024-01-01 - 2024-12-31 - 20123456789.csv" (example)
            # control.py seems to expect a specific format.
            # Let's look at `control.py`:
            # partes_archivo = data["Archivo"].str.split("-")
            # data['Fin CUIT'] = partes_archivo.str[4].str.strip().astype(np.int64)
            # data['Cliente'] = partes_archivo.str[5].str.strip().str.replace('.csv','', regex=True)

            # If we renamed files differently in `procesar_descarga_mc`, this will break.
            # `procesar_descarga_mc` used `filename_zip` from URL.
            # MinIO URLs often have names like "MCE-20123456789-20240101-20241231.zip" or similar?
            # Or maybe "20123456789-MCE-..."

            # If parsing fails, we should try to extract from content if possible, but MC csv doesn't always have client CUIT/Name in rows (it has user's CUIT).
            # But wait, `data['CUIT Cliente']` and `data['Cliente']` seem to be the represented entity.
            # In `control.py`, it uses filename.

            # Let's try to be robust. If splits are not enough, maybe regex.
            # Or just use the file parent folder name if available?
            # But here we are reading many files in batch, potentially from different clients.

            # Let's assume the filename format is preserved from MinIO and matches what control.py expects OR we adjust.
            # If not, we might need to rely on the folder structure if `leer_archivos_csv_batch` is called per client?
            # No, `control()` receives a list of ALL files.

            # Workaround: Check if we can extract from filename safely.

            try:
                data['Fin CUIT'] = partes_archivo.str[4].str.strip().astype(np.int64)
                data['CUIT Cliente'] = partes_archivo.str[4].str.strip().astype(np.int64)
                if len(data["Archivo"].iloc[0].split("-")) > 5:
                     data['Cliente'] = partes_archivo.str[5].str.strip().str.replace('.csv','', regex=True)
                else:
                     data['Cliente'] = "Desconocido"
            except Exception:
                # Fallback: try to extract from folder name?
                # or just use a placeholder
                 data['Fin CUIT'] = 0
                 data['CUIT Cliente'] = 0
                 data['Cliente'] = "Desconocido"

            es_emitido = 'Denominación Receptor' in data.columns
            es_recibido = 'Denominación Emisor' in data.columns

            if es_emitido:
                data['Nro. Doc. Receptor/Emisor'] = data['Denominación Receptor'] # Wait, control.py mapped 'Nro. Doc. Receptor' -> 'Nro. Doc. Receptor/Emisor'??
                # control.py:
                # data['Nro. Doc. Receptor/Emisor'] = data['Nro. Doc. Receptor']
                # data['Denominación Receptor/Emisor'] = data['Denominación Receptor']
                data['Nro. Doc. Receptor/Emisor'] = data.get('Nro. Doc. Receptor', '')
                data['Denominación Receptor/Emisor'] = data.get('Denominación Receptor', '')
            elif es_recibido:
                data['Nro. Doc. Receptor/Emisor'] = data.get('Nro. Doc. Emisor', '')
                data['Denominación Receptor/Emisor'] = data.get('Denominación Emisor', '')

            cols = [
                'Fecha de Emisión', 'Tipo de Comprobante', 'Punto de Venta',
                'Número Desde', 'Número Hasta', 'Cód. Autorización',
                'Tipo Cambio', 'Moneda',
                'Imp. Neto Gravado Total', 'Imp. Neto No Gravado',
                'Imp. Op. Exentas', 'Otros Tributos', 'Total IVA', 'Imp. Total',
                'Nro. Doc. Receptor/Emisor', 'Denominación Receptor/Emisor',
                'Archivo', 'CUIT Cliente', 'Fin CUIT', 'Cliente'
            ]
            # Ensure columns exist
            for c in cols:
                if c not in data.columns:
                    data[c] = 0 if 'Imp.' in c or 'Total' in c else ''

            data = data[cols]
            dataframes.append(data)
        except Exception as e:
            _log_error(f"Error leyendo CSV {f}: {e}", log_fn)
            continue

    if dataframes:
        return pd.concat(dataframes, ignore_index=True)
    return pd.DataFrame()

def leer_archivos_json_batch(archivos_json: List[str], log_fn: Optional[Callable[[str], None]] = None) -> pd.DataFrame:
    registros = []
    for factura in archivos_json:
        if not os.path.isfile(factura):
            continue
        try:
            with open(factura, 'r', encoding='utf-8-sig') as f:
                data_dict = json.load(f)

            data_dict['Archivo PDF'] = os.path.basename(factura)

            # Extract CUIT from filename if possible. control.py: partes = ... split("-")[0]
            partes = data_dict['Archivo PDF'].split("-")
            if len(partes) >= 1 and partes[0].isdigit():
                data_dict['CUIT Cliente'] = int(partes[0].strip())
                data_dict['Fin CUIT'] = int(partes[0].strip())

            # Extract Client from parent dir
            try:
                parent = os.path.basename(os.path.dirname(factura))
                # control.py: split("_", 1)[1]
                if "_" in parent:
                    data_dict['Cliente'] = parent.split("_", 1)[1]
                else:
                    data_dict['Cliente'] = parent
            except Exception:
                pass

            registros.append(data_dict)
        except Exception as e:
             _log_error(f"Error leyendo JSON {factura}: {e}", log_fn)

    if registros:
        return pd.DataFrame(registros)
    return pd.DataFrame()

def generar_reporte_control(
    archivos_mc: List[str],
    archivos_json: List[str],
    path_categorias: str,
    output_path: str,
    log_fn: Optional[Callable[[str], None]] = None
) -> None:
    """
    Core logic for generating the report.
    """
    _log_info("Iniciando generación de reporte...", log_fn)

    if not os.path.exists(path_categorias):
        _log_error(f"No se encontró archivo de categorías: {path_categorias}", log_fn)
        return

    try:
        categorias = pd.read_excel(path_categorias, sheet_name='Categorias')

        # Read dates
        # control.py logic: sheet 'Rango de Fechas', A2 and B2.
        # pandas read_excel with header=None, skiprows=1 means A2 is at iloc[0,0] if we read col 0.
        fecha_inicial_raw = pd.read_excel(path_categorias, sheet_name='Rango de Fechas', header=None, skiprows=1, usecols=[0]).iloc[0,0]
        fecha_final_raw = pd.read_excel(path_categorias, sheet_name='Rango de Fechas', header=None, skiprows=1, usecols=[1]).iloc[0,0]

        # Ensure datetime
        fecha_inicial = pd.to_datetime(fecha_inicial_raw, dayfirst=True)
        fecha_final = pd.to_datetime(fecha_final_raw, dayfirst=True)

        _log_info(f"Rango fechas control: {fecha_inicial.date()} - {fecha_final.date()}", log_fn)

        consolidado = leer_archivos_csv_batch(archivos_mc, log_fn)
        info_facturas_pdf = leer_archivos_json_batch(archivos_json, log_fn)

        if consolidado.empty:
            _log_info("No se encontraron datos en los archivos CSV (MC).", log_fn)
            return

        # Rename columns to shorter names for processing
        consolidado.rename(columns={
            'Fecha de Emisión': 'Fecha',
            'Tipo de Comprobante': 'Tipo',
            'Imp. Neto Gravado Total': 'Imp. Neto Gravado',
            'Total IVA': 'IVA'
        }, inplace=True)

        # Process amounts
        columnas_numericas = ['Imp. Neto Gravado', 'Imp. Neto No Gravado', 'Imp. Op. Exentas', 'Otros Tributos', 'IVA', 'Imp. Total']
        # Convert to float (handling commas)
        for col in columnas_numericas:
            if col in consolidado.columns:
                 # Clean string if needed
                 if consolidado[col].dtype == object:
                      consolidado[col] = consolidado[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                      consolidado[col] = pd.to_numeric(consolidado[col], errors='coerce').fillna(0)

        if 'Tipo Cambio' in consolidado.columns:
             if consolidado['Tipo Cambio'].dtype == object:
                  consolidado['Tipo Cambio'] = consolidado['Tipo Cambio'].astype(str).str.replace(',', '.', regex=False)
                  consolidado['Tipo Cambio'] = pd.to_numeric(consolidado['Tipo Cambio'], errors='coerce').fillna(1)
             consolidado.loc[consolidado['Tipo Cambio'] == 0, 'Tipo Cambio'] = 1

             for col in columnas_numericas:
                 if col in consolidado.columns:
                     consolidado[col] = consolidado[col] * consolidado['Tipo Cambio']

        # Handle Credit Notes
        consolidado.loc[consolidado['Tipo'].isin(NOTAS_DE_CREDITO), columnas_numericas] *= -1

        # Drop unused
        consolidado.drop(['Imp. Neto Gravado', 'Imp. Neto No Gravado', 'Imp. Op. Exentas', 'IVA'], axis=1, inplace=True, errors='ignore')

        # MC column (extracted from filename part 1?)
        # control.py: consolidado['MC'] = consolidado['Archivo'].str.split("-").str[1].str.strip()
        # Dependent on filename format. Safe to skip or try.
        try:
             consolidado['MC'] = consolidado['Archivo'].str.split("-").str[1].str.strip()
        except:
             consolidado['MC'] = ""

        # Build AUX
        # CUIT_Emisor-COD(3)-PtoVenta(5)-Numero(8)
        # Fin CUIT is emisor
        consolidado['AUX'] = (
            consolidado['Fin CUIT'].astype(int).astype(str) + "-" +
            consolidado['Tipo'].astype(int).astype(str).str.zfill(3) + "-" +
            consolidado['Punto de Venta'].astype(int).astype(str).str.zfill(5) + "-" +
            consolidado['Número Desde'].astype(int).astype(str).str.zfill(8)
        )

        if not info_facturas_pdf.empty:
             consolidado = pd.merge(consolidado, info_facturas_pdf[['AUX', 'Desde', 'Hasta', 'Archivo PDF']], how='left', on='AUX')
        else:
             consolidado['Desde'] = pd.NaT
             consolidado['Hasta'] = pd.NaT
             consolidado['Archivo PDF'] = None

        consolidado['Cruzado'] = np.where(consolidado['Archivo PDF'].notnull(), 'Si', 'No')

        # Dates processing
        consolidado['Fecha'] = pd.to_datetime(consolidado['Fecha'], format='ISO8601', errors='coerce')
        if 'Desde' in consolidado.columns:
             consolidado['Desde'] = pd.to_datetime(consolidado['Desde'], dayfirst=True, errors='coerce')
        if 'Hasta' in consolidado.columns:
             consolidado['Hasta'] = pd.to_datetime(consolidado['Hasta'], dayfirst=True, errors='coerce')

        consolidado['Desde'] = consolidado['Desde'].fillna(consolidado['Fecha'])
        consolidado['Hasta'] = consolidado['Hasta'].fillna(consolidado['Fecha'])

        # Filter by dates? control.py has a commented out line for this. I'll skip.

        # Pro-rating
        consolidado['Fecha Inicial'] = fecha_inicial
        consolidado['Fecha_Inicial_max'] = consolidado[['Fecha Inicial', 'Desde']].max(axis=1)
        del consolidado['Fecha Inicial']

        consolidado['Fecha Final'] = fecha_final
        consolidado['Fecha_Final_min'] = consolidado[['Fecha Final', 'Hasta']].min(axis=1)
        del consolidado['Fecha Final']

        consolidado['Dias de facturación'] = (consolidado['Hasta'] - consolidado['Desde']).dt.days + 1
        consolidado['Días Efectivos'] = (consolidado['Fecha_Final_min'] - consolidado['Fecha_Inicial_max']).dt.days + 1
        consolidado.loc[consolidado['Días Efectivos'] < 0, 'Días Efectivos'] = 0

        # Avoid division by zero
        consolidado['Dias de facturación'] = consolidado['Dias de facturación'].replace(0, 1)

        consolidado['Importe por día'] = consolidado['Imp. Total'] / consolidado['Dias de facturación']
        consolidado['Importe Prorrateado'] = consolidado['Importe por día'] * consolidado['Días Efectivos']

        # Pivot Table
        tabla_dinamica = pd.pivot_table(
            consolidado,
            values=['Importe Prorrateado', 'Tipo'],
            index=['Cliente', 'MC'],
            aggfunc={'Importe Prorrateado': 'sum', 'Tipo': 'count'}
        )
        tabla_dinamica.rename(columns={'Tipo': 'Cantidad de Comprobantes'}, inplace=True)

        # Categorization
        def get_max_ingresos(x):
            matches = categorias.loc[categorias['Ingresos brutos'] >= x, 'Ingresos brutos']
            return matches.iloc[0] if not matches.empty else 0

        def get_categoria(x):
            matches = categorias.loc[categorias['Ingresos brutos'] >= x, 'Categoria']
            return matches.iloc[0] if not matches.empty else "Excedido"

        tabla_dinamica['Ingresos brutos máximos por la categoría'] = tabla_dinamica['Importe Prorrateado'].apply(get_max_ingresos)
        tabla_dinamica['Categoría'] = tabla_dinamica['Importe Prorrateado'].apply(get_categoria)

        # Formatting Dates for export
        for c in ['Desde', 'Hasta', 'Fecha', 'Fecha_Inicial_max', 'Fecha_Final_min']:
             consolidado[c] = consolidado[c].dt.strftime('%d/%m/%Y')

        # Export
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            tabla_dinamica.to_excel(writer, sheet_name='Tabla Dinámica')
            consolidado.to_excel(writer, sheet_name='Consolidado', index=False)

        # Apply Styles
        wb = load_workbook(output_path)

        if 'Tabla Dinámica' in wb.sheetnames:
            ws = wb['Tabla Dinámica']
            aplicar_formato_encabezado(ws)
            aplicar_formato_moneda(ws, 3, 3) # Approx cols
            aplicar_formato_moneda(ws, 5, 5)
            autoajustar_columnas(ws)
            agregar_filtros(ws)

        if 'Consolidado' in wb.sheetnames:
            ws = wb['Consolidado']
            aplicar_formato_encabezado(ws)
            # Apply currency to Imp Total and Prorrateado (find indices or guess)
            # Imp Total is ~14, Importe Prorrateado is last
            # Just applying auto width and header is enough for MVP, or use logic from control.py
            autoajustar_columnas(ws)
            agregar_filtros(ws)

        wb.save(output_path)
        _log_info(f"Reporte generado exitosamente: {output_path}", log_fn)

    except Exception as e:
        _log_error(f"Error generando reporte: {e}", log_fn)
        import traceback
        _log_error(traceback.format_exc(), log_fn)
