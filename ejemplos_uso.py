#!/usr/bin/env python3
"""
Ejemplo de uso de la API v1 de Mis Comprobantes.

Este script demuestra cómo usar las nuevas funciones actualizadas.
"""

from mrbot_app.consulta import (
    consulta_requests_restantes,
    descargar_archivos_minio_concurrente,
)
from mrbot_app.mis_comprobantes import consulta_mc
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def ejemplo_consulta_simple():
    """
    Ejemplo 1: Consulta simple de comprobantes con descarga desde MinIO.
    """
    print("\n" + "="*60)
    print("EJEMPLO 1: Consulta simple con MinIO")
    print("="*60)
    
    # Parámetros de ejemplo (REEMPLAZAR con datos reales)
    response = consulta_mc(
        desde="01/01/2024",
        hasta="31/01/2024",
        cuit_inicio_sesion="20123456780",
        representado_nombre="EMPRESA EJEMPLO SA",
        representado_cuit="30876543210",
        contrasena="tu_contraseña",
        descarga_emitidos=True,
        descarga_recibidos=True,
        carga_minio=True,  # Obtener URLs de MinIO
        carga_json=True    # Obtener datos en JSON
    )
    
    # Verificar respuesta
    if response.get('success'):
        print("✓ Consulta exitosa")
        
        # URLs de MinIO
        if response.get('mis_comprobantes_emitidos_url_minio'):
            print(f"URL MinIO emitidos: {response['mis_comprobantes_emitidos_url_minio']}")
        
        if response.get('mis_comprobantes_recibidos_url_minio'):
            print(f"URL MinIO recibidos: {response['mis_comprobantes_recibidos_url_minio']}")
        
        # Datos JSON
        if response.get('mis_comprobantes_emitidos_json'):
            print(f"Comprobantes emitidos (JSON): {len(response['mis_comprobantes_emitidos_json'])} registros")
        
        if response.get('mis_comprobantes_recibidos_json'):
            print(f"Comprobantes recibidos (JSON): {len(response['mis_comprobantes_recibidos_json'])} registros")
    else:
        print(f"✗ Error en consulta: {response.get('message')}")
    
    return response


def ejemplo_descarga_minio():
    """
    Ejemplo 2: Descarga de archivos desde MinIO con 10 workers.
    """
    print("\n" + "="*60)
    print("EJEMPLO 2: Descarga concurrente desde MinIO")
    print("="*60)
    
    # Lista de archivos a descargar (URLs de ejemplo)
    archivos = [
        {
            'url': 'https://minio.example.com/bucket/emitidos.zip',
            'destino': './Descargas/emitidos_ejemplo.zip'
        },
        {
            'url': 'https://minio.example.com/bucket/recibidos.zip',
            'destino': './Descargas/recibidos_ejemplo.zip'
        }
    ]
    
    print(f"Descargando {len(archivos)} archivo(s)...")
    print("Workers concurrentes: 10")
    
    # Nota: Este ejemplo no se ejecutará realmente ya que las URLs son de ejemplo
    # Para usar con URLs reales, descomenta la siguiente línea:
    # resultados = descargar_archivos_minio_concurrente(archivos, max_workers=10)
    
    print("\n💡 Para ejecutar, reemplaza las URLs con las obtenidas de la API")


def ejemplo_consulta_completa():
    """
    Ejemplo 3: Flujo completo - consulta + descarga desde MinIO.
    """
    print("\n" + "="*60)
    print("EJEMPLO 3: Flujo completo (consulta + descarga)")
    print("="*60)
    
    # Paso 1: Realizar consulta
    print("\n📡 Paso 1: Consultando API...")
    
    # NOTA: Reemplazar con tus credenciales reales
    response = consulta_mc(
        desde="01/01/2024",
        hasta="31/01/2024",
        cuit_inicio_sesion="20123456780",
        representado_nombre="EMPRESA SA",
        representado_cuit="30876543210",
        contrasena="tu_contraseña",
        descarga_emitidos=True,
        descarga_recibidos=True,
        carga_minio=True,
        carga_json=True,
        carga_s3=False
    )

    if not response.get('success'):
        print(f"✗ Error: {response.get('message')}")
        return
    
    print("✓ Consulta exitosa")
    
    # Paso 2: Preparar lista de descargas
    print("\n📥 Paso 2: Preparando descargas desde MinIO...")
    
    archivos_a_descargar = []
    
    if response.get('mis_comprobantes_emitidos_url_minio'):
        archivos_a_descargar.append({
            'url': response['mis_comprobantes_emitidos_url_minio'],
            'destino': './Descargas/emitidos_minio.zip'
        })
    
    if response.get('mis_comprobantes_recibidos_url_minio'):
        archivos_a_descargar.append({
            'url': response['mis_comprobantes_recibidos_url_minio'],
            'destino': './Descargas/recibidos_minio.zip'
        })
    
    if not archivos_a_descargar:
        print("⚠ No hay archivos de MinIO para descargar")
        return
    
    # Paso 3: Descargar archivos (10 workers concurrentes)
    print(f"\n⬇️  Paso 3: Descargando {len(archivos_a_descargar)} archivo(s)...")
    print("Usando 10 workers concurrentes...")
    
    # NOTA: Descomenta para ejecutar la descarga real
    # resultados = descargar_archivos_minio_concurrente(archivos_a_descargar)
    # 
    # # Mostrar resultados
    # exitosos = sum(1 for r in resultados if r['success'])
    # print(f"\n✓ Descargas completadas: {exitosos}/{len(resultados)} exitosas")
    
    print("\n💡 Para ejecutar, asegúrate de tener credenciales válidas en .env")


def ejemplo_requests_restantes():
    """
    Ejemplo 4: Consultar requests restantes del mes.
    """
    print("\n" + "="*60)
    print("EJEMPLO 4: Consultar requests restantes")
    print("="*60)
    
    mail = os.getenv("MAIL")
    
    if not mail:
        print("⚠ Variable MAIL no configurada en .env")
        return
    
    try:
        response = consulta_requests_restantes(mail)
        
        print(f"Email: {mail}")
        print(f"Consultas disponibles: {response.get('consultas_disponibles')}")
        print(f"Máximas consultas mensuales: {response.get('maximas_consultas_mensuales')}")
        print(f"Consultas realizadas este mes: {response.get('consultas_realizadas_mes_actual')}")
        
    except Exception as e:
        print(f"✗ Error consultando requests: {e}")
        print("💡 Asegúrate de tener API_KEY y MAIL configurados en .env")


def ejemplo_multiples_formatos():
    """
    Ejemplo 5: Obtener comprobantes en múltiples formatos.
    """
    print("\n" + "="*60)
    print("EJEMPLO 5: Múltiples formatos de salida")
    print("="*60)
    
    response = consulta_mc(
        desde="01/01/2024",
        hasta="31/01/2024",
        cuit_inicio_sesion="20123456780",
        representado_nombre="EMPRESA SA",
        representado_cuit="30876543210",
        contrasena="tu_contraseña",
        descarga_emitidos=True,
        descarga_recibidos=False,
        carga_minio=True,   # URLs de MinIO
        carga_json=True,    # Datos en JSON
        carga_s3=True      # URLs de S3
    )

    print("Formatos solicitados:")
    print("  - MinIO: URLs para descarga")
    print("  - JSON: Datos estructurados")
    print("  - S3: URLs alternativas")
    
    print("\n💡 Puedes combinar los formatos según tus necesidades")


def main():
    """Menú principal de ejemplos."""
    print("\n" + "🚀 EJEMPLOS DE USO - API v1 Mis Comprobantes")
    print("="*60)
    
    # Verificar configuración
    if not os.getenv("MAIL") or not os.getenv("API_KEY"):
        print("\n⚠️  IMPORTANTE: Configura tus credenciales en el archivo .env")
        print("Copia .env.example a .env y completa con tus datos:")
        print("  - MAIL: tu email registrado")
        print("  - API_KEY: tu API key")
        print("  - URL: https://api-bots.mrbot.com.ar (por defecto)")
        print("\n" + "="*60)
    
    # Ejecutar ejemplos
    try:
        # Ejemplo 1: Requests restantes (no requiere credenciales AFIP)
        ejemplo_requests_restantes()
        
        # Los demás ejemplos muestran el código pero no se ejecutan
        # ya que requieren credenciales válidas de AFIP
        print("\n" + "="*60)
        print("EJEMPLOS ADICIONALES (requieren credenciales AFIP)")
        print("="*60)
        print("\nLos siguientes ejemplos muestran el código pero no se ejecutan.")
        print("Modifica las credenciales y descomenta el código para usarlos:")
        
        # Mostrar estructura de ejemplos
        print("\n📝 Ejemplo 2: Consulta simple")
        print("   - consulta_mc() con parámetros básicos")
        print("   - Obtener URLs de MinIO y datos JSON")
        
        print("\n📝 Ejemplo 3: Descarga concurrente")
        print("   - descargar_archivos_minio_concurrente()")
        print("   - 10 workers simultáneos")
        
        print("\n📝 Ejemplo 4: Flujo completo")
        print("   - Consulta + descarga automática")
        print("   - Manejo de respuestas")
        
        print("\n📝 Ejemplo 5: Múltiples formatos")
        print("   - MinIO + JSON + S3")
        print("   - Flexibilidad en formatos de salida")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("Verifica tu configuración en .env")
    
    print("\n" + "="*60)
    print("Para más información, consulta el README.md")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
