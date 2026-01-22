#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

dist_path="$project_root/Ejecutable"
work_path="$project_root/temp_build"

pyinstaller="pyinstaller"
if [ -x "$project_root/venv/bin/pyinstaller" ]; then
  pyinstaller="$project_root/venv/bin/pyinstaller"
fi

if ! command -v "$pyinstaller" >/dev/null 2>&1; then
  echo "Error: pyinstaller no encontrado. Activa el venv o instala pyinstaller." >&2
  exit 1
fi

echo "=== Compilando MrBot ==="

icon_path="$project_root/bin/ABP-blanco-en-fondo-negro.ico"

"$pyinstaller" \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --distpath "$dist_path" \
  --workpath "$work_path" \
  --specpath "$work_path" \
  --name "mrbot" \
  --icon "$icon_path" \
  "$project_root/mrbot.py"

echo "=== Copiando archivos adicionales ==="

install -d "$dist_path/bin"
cp -a "$project_root/bin/." "$dist_path/bin/"

if [ -d "$project_root/ejemplos_api" ]; then
  install -d "$dist_path/ejemplos_api"
  cp -a "$project_root/ejemplos_api/." "$dist_path/ejemplos_api/"
fi

if [ -f "$project_root/.env.example" ]; then
  cp -f "$project_root/.env.example" "$dist_path/.env"
fi

echo "Ejecutable creado en: $dist_path"
