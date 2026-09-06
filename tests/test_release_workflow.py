from __future__ import annotations

import importlib.util
from pathlib import Path
import re
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release-zips-on-tag.yml"
SCANNER = ROOT / ".github" / "scripts" / "scan_release_secrets.py"
WORKFLOW_TEXT = WORKFLOW.read_text(encoding="utf-8")


def _load_scanner():
    spec = importlib.util.spec_from_file_location("release_secret_scanner", SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_triggers_existing_date_and_explicit_rollback_tags():
    assert "- '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'" in WORKFLOW_TEXT
    assert "- '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]'" in WORKFLOW_TEXT
    assert "- 'v1-rollback-v2.*'" in WORKFLOW_TEXT


def test_tag_validation_is_anchored_and_sets_rollback_rc_prerelease():
    assert "[[ \"$TAG\" =~ ^[0-9]{8}(_[0-9]{6})?$ ]]" in WORKFLOW_TEXT
    assert "[[ \"$TAG\" =~ ^v1-rollback-v2\\.[0-9]+\\.[0-9]+(-rc\\.[0-9]+)?$ ]]" in WORKFLOW_TEXT
    assert "RELEASE_KIND=\"rollback\"" in WORKFLOW_TEXT
    assert "PRERELEASE=\"true\"" in WORKFLOW_TEXT
    assert "REF_TYPE=\"${GITHUB_REF_TYPE:-}\"" in WORKFLOW_TEXT
    assert "set -euo pipefail" in WORKFLOW_TEXT

    rollback_tag = re.compile(r"^v1-rollback-v2\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$")
    assert rollback_tag.fullmatch("v1-rollback-v2.0.0")
    assert rollback_tag.fullmatch("v1-rollback-v2.12.34-rc.5")
    assert not rollback_tag.fullmatch("v1-rollback-v2.12")
    assert not rollback_tag.fullmatch("v1-rollback-v2.12.34-rc")
    assert not rollback_tag.fullmatch("v1-rollback-v2.12.34-rc.0.extra")


def test_workflow_publishes_zip_and_sha256_for_both_platforms():
    assert "sha256sum \"$ZIP_NAME\"" in WORKFLOW_TEXT
    assert "Get-FileHash -LiteralPath $destZip -Algorithm SHA256" in WORKFLOW_TEXT
    assert "mrbot-refactored.${{ env.APP_VERSION }}.Linux.zip.sha256" in WORKFLOW_TEXT
    assert "mrbot-refactored.${{ env.APP_VERSION }}.Windows.zip.sha256" in WORKFLOW_TEXT
    assert "release-assets/**/*.sha256" in WORKFLOW_TEXT
    assert "prerelease: ${{ needs.validate-tag.outputs.prerelease }}" in WORKFLOW_TEXT


def test_workflow_does_not_copy_env_and_scans_both_packages():
    assert 'cp -a "Ejecutable/.env"' not in WORKFLOW_TEXT
    assert 'Copy-Item ".\\Ejecutable\\.env"' not in WORKFLOW_TEXT
    assert WORKFLOW_TEXT.count("scan_release_secrets.py") == 2
    assert "$LASTEXITCODE -ne 0" in WORKFLOW_TEXT


def test_scanner_rejects_env_names_before_content_access():
    scanner = _load_scanner()
    assert scanner.is_env_file(Path(".env"))
    assert scanner.is_env_file(Path(".env.production"))
    assert scanner.is_env_file(Path("settings.env"))
    assert not scanner.is_env_file(Path("settings.ini"))
    assert "if is_env_file(path):" in SCANNER.read_text(encoding="utf-8")
    assert "path.read_bytes()" in SCANNER.read_text(encoding="utf-8")


def test_scanner_fails_closed_on_secret_like_content():
    scanner = _load_scanner()
    with TemporaryDirectory() as package_dir:
        package = Path(package_dir)
        (package / "safe-name.bin").write_bytes(b"AKIA1234567890ABCDEF")

        try:
            scanner.scan(package)
        except scanner.ScanError:
            pass
        else:
            raise AssertionError("El escáner debe fallar ante contenido sensible")


def test_scanner_accepts_non_secret_package_content():
    scanner = _load_scanner()
    with TemporaryDirectory() as package_dir:
        package = Path(package_dir)
        (package / "safe-name.bin").write_bytes(b"release payload")

        assert scanner.scan(package) == 1
