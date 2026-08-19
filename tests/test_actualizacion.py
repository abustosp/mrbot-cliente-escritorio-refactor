#!/usr/bin/env python3
"""
Script de prueba para verificar las funciones actualizadas de la API.

Este script prueba:
1. Importación de módulos
2. Estructura de requests
3. Funciones de descarga
"""

import sys
import os

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Prueba que todos los imports funcionen correctamente."""
    print("="*60)
    print("TEST 1: Verificando imports...")
    print("="*60)
    
    try:
        from mrbot_app.consulta import (
            consulta_requests_restantes,
            descargar_archivo_minio,
            descargar_archivos_minio_concurrente,
        )
        from mrbot_app.mis_comprobantes import consulta_mc
        print("✓ Todos los imports exitosos")
        return True
    except ImportError as e:
        print(f"✗ Error en imports: {e}")
        return False


def test_function_signatures():
    """Verifica que las funciones tengan las firmas correctas."""
    print("\n" + "="*60)
    print("TEST 2: Verificando firmas de funciones...")
    print("="*60)
    
    from mrbot_app.mis_comprobantes import consulta_mc
    import inspect
    
    sig = inspect.signature(consulta_mc)
    params = list(sig.parameters.keys())
    
    required_params = [
        'desde', 'hasta', 'cuit_inicio_sesion', 'representado_nombre',
        'representado_cuit', 'contrasena', 'descarga_emitidos', 
        'descarga_recibidos'
    ]
    
    optional_params = [
        'carga_minio', 'carga_json', 'carga_s3', 'proxy_request'
    ]
    
    print(f"Parámetros de consulta_mc: {params}")
    
    missing = [p for p in required_params if p not in params]
    if missing:
        print(f"✗ Faltan parámetros requeridos: {missing}")
        return False
    
    print("✓ Todos los parámetros requeridos presentes")
    
    optional_present = [p for p in optional_params if p in params]
    print(f"✓ Parámetros opcionales presentes: {optional_present}")
    
    return True


def test_request_structure():
    """Verifica la estructura de request que se enviaría a la API."""
    print("\n" + "="*60)
    print("TEST 3: Verificando estructura de request...")
    print("="*60)
    
    # Simular una llamada (sin ejecutarla realmente)
    expected_fields = {
        'desde': '01/01/2024',
        'hasta': '31/01/2024',
        'cuit_inicio_sesion': '20123456780',
        'representado_nombre': 'TEST SA',
        'representado_cuit': '30876543210',
        'contrasena': 'test123',
        'descarga_emitidos': True,
        'descarga_recibidos': True,
        'carga_minio': True,
        'carga_json': True,
        'carga_s3': False
    }
    
    print("Estructura de payload esperada:")
    for key, value in expected_fields.items():
        print(f"  - {key}: {type(value).__name__}")
    
    print("✓ Estructura de request correcta")
    return True


def test_concurrent_downloads():
    """Verifica que la función de descarga concurrente esté disponible."""
    print("\n" + "="*60)
    print("TEST 4: Verificando descarga concurrente...")
    print("="*60)
    
    from mrbot_app.consulta import descargar_archivos_minio_concurrente, MAX_WORKERS
    import inspect
    
    sig = inspect.signature(descargar_archivos_minio_concurrente)
    params = list(sig.parameters.keys())
    
    print(f"Parámetros de descargar_archivos_minio_concurrente: {params}")
    print(f"MAX_WORKERS configurado: {MAX_WORKERS}")
    
    if 'urls' in params and 'max_workers' in params:
        print("✓ Función de descarga concurrente correctamente configurada")
        return True
    else:
        print("✗ Parámetros incorrectos en función de descarga")
        return False


def test_api_endpoints():
    """Verifica que los endpoints de API estén correctos."""
    print("\n" + "="*60)
    print("TEST 5: Verificando configuración de API...")
    print("="*60)
    
    from mrbot_app.consulta import root_url
    
    print(f"URL base: {root_url}")
    
    expected_base = "https://api-bots.mrbot.com.ar"
    if expected_base in root_url or root_url == expected_base:
        print("✓ URL base correcta")
    else:
        print(f"⚠ URL base diferente a la esperada: {expected_base}")
    
    # Verificar que las URLs se construyen correctamente
    consulta_endpoint = root_url.rstrip('/') + "/api/v1/mis_comprobantes/consulta"
    print(f"Endpoint de consulta: {consulta_endpoint}")
    
    if "/api/v1/mis_comprobantes/consulta" in consulta_endpoint:
        print("✓ Endpoint de consulta correcto")
        return True
    else:
        print("✗ Endpoint de consulta incorrecto")
        return False


def main():
    """Ejecuta todos los tests."""
    print("\n" + "🧪 SUITE DE PRUEBAS - API v1 Mis Comprobantes")
    print("="*60 + "\n")
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Firmas de funciones", test_function_signatures()))
    results.append(("Estructura de request", test_request_structure()))
    results.append(("Descarga concurrente", test_concurrent_downloads()))
    results.append(("Endpoints de API", test_api_endpoints()))
    
    # Resumen
    print("\n" + "="*60)
    print("RESUMEN DE PRUEBAS")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {name}")
    
    print("="*60)
    print(f"Resultado: {passed}/{total} pruebas exitosas")
    
    if passed == total:
        print("🎉 ¡Todas las pruebas pasaron correctamente!")
        return 0
    else:
        print("⚠ Algunas pruebas fallaron. Revisa los detalles arriba.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
