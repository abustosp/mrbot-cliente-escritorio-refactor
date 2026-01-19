$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$distPath = Join-Path $projectRoot "Ejecutable"
$workPath = Join-Path $projectRoot "temp_build"

# Detectar PyInstaller
$pyinstaller = "pyinstaller"
if (Test-Path "$projectRoot\venv\Scripts\pyinstaller.exe") {
    $pyinstaller = "$projectRoot\venv\Scripts\pyinstaller.exe"
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

# Copiar carpetas y archivos adicionales
Write-Host "=== Copiando archivos adicionales ===" -ForegroundColor Cyan

# Copiar bin/
New-Item -ItemType Directory -Force -Path (Join-Path $distPath "bin") | Out-Null
Copy-Item ".\bin\*" (Join-Path $distPath "bin") -Force -Recurse

# Copiar ejemplos_api/
if (Test-Path ".\ejemplos_api") {
    New-Item -ItemType Directory -Force -Path (Join-Path $distPath "ejemplos_api") | Out-Null
    Copy-Item ".\ejemplos_api\*" (Join-Path $distPath "ejemplos_api") -Force -Recurse
}

# Copiar .env.example como .env
if (Test-Path ".\.env.example") {
    Copy-Item ".\.env.example" (Join-Path $distPath ".env") -Force
}

Write-Host "Ejecutable creado en: $distPath" -ForegroundColor Green
