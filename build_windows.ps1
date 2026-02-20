$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$distPath = Join-Path $projectRoot "Ejecutable"
$workPath = Join-Path $projectRoot "temp_build"
$tempExamplesPath = Join-Path $workPath "ejemplos_api"

# Detectar PyInstaller
$pyinstaller = "pyinstaller"
if (Test-Path "$projectRoot\venv\Scripts\pyinstaller.exe") {
    $pyinstaller = "$projectRoot\venv\Scripts\pyinstaller.exe"
}

$pythonCmd = "python"
if (Test-Path "$projectRoot\venv\Scripts\python.exe") {
    $pythonCmd = "$projectRoot\venv\Scripts\python.exe"
}

if ($pyinstaller -eq "pyinstaller" -and -not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "Error: pyinstaller no encontrado. Activa el venv o instala pyinstaller."
}

if ($pythonCmd -eq "python" -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Error: python no encontrado. Activa el venv o instala Python."
}

Write-Host "=== Compilando MrBot ===" -ForegroundColor Cyan

# Ruta absoluta del icono
$iconPath = Join-Path $projectRoot "bin\ABP-blanco-en-fondo-negro.ico"

& $pyinstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --distpath "$distPath" `
  --workpath "$workPath" `
  --specpath "$workPath" `
  --name "mrbot" `
  --icon "$iconPath" `
  ".\mrbot.py"

if (-not $?) {
    throw "Error durante la compilación con PyInstaller"
}

Write-Host "=== Generando examples en carpeta temporal ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $workPath | Out-Null
if (Test-Path $tempExamplesPath) {
    Remove-Item $tempExamplesPath -Force -Recurse
}

$generateExamplesCode = @"
import os
import sys

project_root = os.environ["PROJECT_ROOT"]
sys.path.insert(0, project_root)

from mrbot_app.examples import ensure_example_excels

ensure_example_excels()
"@

Push-Location $workPath
$previousProjectRoot = $env:PROJECT_ROOT
try {
    $env:PROJECT_ROOT = $projectRoot
    & $pythonCmd -c $generateExamplesCode
    if (-not $?) {
        throw "Error generando los examples en carpeta temporal"
    }
}
finally {
    if ($null -ne $previousProjectRoot) {
        $env:PROJECT_ROOT = $previousProjectRoot
    }
    else {
        Remove-Item Env:PROJECT_ROOT -ErrorAction SilentlyContinue
    }
    Pop-Location
}

# Copiar carpetas y archivos adicionales
Write-Host "=== Copiando archivos adicionales ===" -ForegroundColor Cyan

# Copiar bin/
New-Item -ItemType Directory -Force -Path (Join-Path $distPath "bin") | Out-Null
Copy-Item ".\bin\*" (Join-Path $distPath "bin") -Force -Recurse

# Copiar ejemplos_api/ generado en carpeta temporal
if (Test-Path $tempExamplesPath) {
    New-Item -ItemType Directory -Force -Path (Join-Path $distPath "ejemplos_api") | Out-Null
    Copy-Item (Join-Path $tempExamplesPath "*") (Join-Path $distPath "ejemplos_api") -Force -Recurse
}

# Copiar .env.example como .env
if (Test-Path ".\.env.example") {
    Copy-Item ".\.env.example" (Join-Path $distPath ".env") -Force
}

Write-Host "Ejecutable creado en: $distPath" -ForegroundColor Green
