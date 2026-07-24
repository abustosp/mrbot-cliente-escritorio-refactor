import os
import sqlite3
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

CATEGORIAS_DB_FILENAME = "categorias_monotributo.db"

def _get_db_path() -> Path:
    return Path.cwd() / CATEGORIAS_DB_FILENAME

def _get_db_url() -> str:
    from mrbot_app.config import CATEGORIAS_MONOTRIBUTO_URL
    return CATEGORIAS_MONOTRIBUTO_URL

def ensure_categorias_db(force: bool = False) -> None:
    db_path = _get_db_path()
    if not force and db_path.exists():
        return
    url = _get_db_url()
    if not url:
        raise ValueError("CATEGORIAS_MONOTRIBUTO_URL no está configurada en .env")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(db_path))

def cargar_categorias(
    fecha_referencia: Optional[date] = None,
) -> pd.DataFrame:
    ensure_categorias_db()
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query("SELECT * FROM categorias", conn)
    conn.close()
    if "categoria" not in df.columns or "ingresos_brutos" not in df.columns:
        raise ValueError("La base de datos de categorías no tiene las columnas esperadas (categoria, ingresos_brutos)")
    if fecha_referencia is not None and "vigencia_desde" in df.columns:
        df["vigencia_desde"] = pd.to_datetime(df["vigencia_desde"], format="%d/%m/%Y", errors="coerce")
        if "vigencia_hasta" in df.columns:
            df["vigencia_hasta"] = pd.to_datetime(df["vigencia_hasta"], format="%d/%m/%Y", errors="coerce")
        ref = pd.Timestamp(fecha_referencia)
        mask = (df["vigencia_desde"] <= ref) & (
            df["vigencia_hasta"].isna() | (df["vigencia_hasta"] >= ref)
        )
        df = df[mask].copy()
    result = df[["categoria", "ingresos_brutos"]].sort_values("categoria")
    result = result.rename(columns={"categoria": "Categoria", "ingresos_brutos": "Ingresos brutos"})
    return result

def obtener_info_categorias() -> dict:
    db_path = _get_db_path()
    if not db_path.exists():
        return {
            "descargada": False,
            "vigencia_desde": None,
            "vigencia_hasta": None,
            "ultima_actualizacion": None,
        }
    ultima_actualizacion = datetime.fromtimestamp(os.path.getmtime(str(db_path)))
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query("SELECT * FROM categorias", conn)
    conn.close()
    if "vigencia_desde" in df.columns:
        df["vigencia_desde_dt"] = pd.to_datetime(df["vigencia_desde"], format="%d/%m/%Y", errors="coerce")
        vigencia_desde = df["vigencia_desde_dt"].min()
    else:
        vigencia_desde = None
    if "vigencia_hasta" in df.columns:
        df["vigencia_hasta_dt"] = pd.to_datetime(df["vigencia_hasta"], format="%d/%m/%Y", errors="coerce")
        vigencia_hasta = df["vigencia_hasta_dt"].max()
    else:
        vigencia_hasta = None
    return {
        "descargada": True,
        "vigencia_desde": vigencia_desde.date() if pd.notna(vigencia_desde) else None,
        "vigencia_hasta": vigencia_hasta.date() if pd.notna(vigencia_hasta) else None,
        "ultima_actualizacion": ultima_actualizacion,
        "cantidad_categorias": len(df),
    }
