#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

dist_path="$project_root/Ejecutable"
work_path="$project_root/temp_build"
temp_examples_path="$work_path/ejemplos_api"

pyinstaller="pyinstaller"
if [ -x "$project_root/venv/bin/pyinstaller" ]; then
  pyinstaller="$project_root/venv/bin/pyinstaller"
fi

python_cmd="python3"
if [ -x "$project_root/venv/bin/python" ]; then
  python_cmd="$project_root/venv/bin/python"
elif ! command -v "$python_cmd" >/dev/null 2>&1; then
  python_cmd="python"
fi

if ! command -v "$pyinstaller" >/dev/null 2>&1; then
  echo "Error: pyinstaller no encontrado. Activa el venv o instala pyinstaller." >&2
  exit 1
fi

if ! command -v "$python_cmd" >/dev/null 2>&1; then
  echo "Error: python no encontrado. Activa el venv o instala Python." >&2
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

echo "=== Generando examples en carpeta temporal ==="

install -d "$work_path"
rm -rf "$temp_examples_path"
(
  cd "$work_path"
  PROJECT_ROOT="$project_root" "$python_cmd" - <<'PY'
import os
import sys

project_root = os.environ["PROJECT_ROOT"]
sys.path.insert(0, project_root)

from mrbot_app.examples import ensure_example_excels

ensure_example_excels()
PY
)

echo "=== Copiando archivos adicionales ==="

install -d "$dist_path/bin"
cp -a "$project_root/bin/." "$dist_path/bin/"

if [ -d "$temp_examples_path" ]; then
  install -d "$dist_path/ejemplos_api"
  cp -a "$temp_examples_path/." "$dist_path/ejemplos_api/"
fi

if [ -f "$project_root/.env.example" ]; then
  cp -f "$project_root/.env.example" "$dist_path/.env"
fi

echo "Ejecutable creado en: $dist_path"
