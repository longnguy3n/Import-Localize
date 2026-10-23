from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_app


def test_build_path_excludes_unrelated_dll_directories(monkeypatch):
    monkeypatch.setattr(build_app.sys, "platform", "win32")
    monkeypatch.setenv("PATH", r"C:\Poppler\bin;C:\OtherQt\bin")
    monkeypatch.setenv("PYTHONPATH", "unexpected-python-packages")
    monkeypatch.setenv("QT_PLUGIN_PATH", "unexpected-qt-plugins")
    environment = build_app.isolated_build_environment()
    assert "Poppler" not in environment["PATH"]
    assert "OtherQt" not in environment["PATH"]
    assert "System32" in environment["PATH"]
    assert "PYTHONPATH" not in environment
    assert "QT_PLUGIN_PATH" not in environment
    assert "Poppler" in os.environ["PATH"]  # Does not change the host environment.


def test_zero_exit_without_report_is_not_a_success(monkeypatch, tmp_path):
    monkeypatch.setattr(build_app.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stderr=b""))
    with pytest.raises(build_app.BuildError, match="EXE lỗi"):
        build_app.verify_frozen_app(tmp_path)


def test_frozen_check_requires_rendered_window_and_expected_platform(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        report = {"status": "ok", "main_window_rendered": True, "csv_comparison": True,
                  "offline_language_detection": True, "tls_context": True,
                  "platform": kwargs["env"]["QT_QPA_PLATFORM"], "qt_version": "test"}
        Path(command[-1]).write_text(json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr=b"")
    monkeypatch.setattr(build_app.subprocess, "run", fake_run)
    reports = build_app.verify_frozen_app(tmp_path)
    assert reports and all(report["main_window_rendered"] for report in reports)


def test_build_rejects_executable_without_tls_check(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        report = {"status": "ok", "main_window_rendered": True, "csv_comparison": True,
                  "offline_language_detection": True, "platform": kwargs["env"]["QT_QPA_PLATFORM"]}
        Path(command[-1]).write_text(json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr=b"")
    monkeypatch.setattr(build_app.subprocess, "run", fake_run)
    with pytest.raises(build_app.BuildError, match="EXE lỗi"):
        build_app.verify_frozen_app(tmp_path)


def test_runtime_ssl_data_preserves_policy_file_and_rejects_missing_file(monkeypatch, tmp_path):
    module = tmp_path / "ssl.py"
    module.write_text("# loads codex-rejected-cas.pem", encoding="utf-8")
    monkeypatch.setattr(build_app.ssl, "__file__", str(module))
    with pytest.raises(build_app.BuildError, match="thiếu file SSL"):
        build_app.runtime_ssl_data()
    certificate = tmp_path / "codex-rejected-cas.pem"
    certificate.write_text("public certificate fixture", encoding="utf-8")
    assert build_app.runtime_ssl_data() == [(certificate, ".")]


def test_standard_python_needs_no_extra_ssl_file(monkeypatch, tmp_path):
    module = tmp_path / "ssl.py"
    module.write_text("# standard Python ssl", encoding="utf-8")
    monkeypatch.setattr(build_app.ssl, "__file__", str(module))
    assert build_app.runtime_ssl_data() == []


def test_tls_context_checks_certificate_verification_without_network(monkeypatch):
    from import_localize.app.self_test import check_tls_context
    import socket
    def no_network(*args, **kwargs):
        pytest.fail("TLS context check must work offline")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    check_tls_context()


def test_qt_import_failure_returns_report_and_nonzero_exit(tmp_path):
    fake_package = tmp_path / "PySide6"
    fake_package.mkdir()
    (fake_package / "__init__.py").write_text("raise ImportError('simulated Qt DLL failure')", encoding="utf-8")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(tmp_path)
    report = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(ROOT / "src/main.py"), "--self-test", str(report)],
                            env=environment, capture_output=True, timeout=20)
    assert result.returncode == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "simulated Qt DLL failure" in payload["error"]


def test_no_bundle_oauth_does_not_read_or_package_configured_client(monkeypatch, tmp_path):
    import zipfile

    work = tmp_path / "work"
    monkeypatch.setattr(build_app, "PYINSTALLER_WORK_DIR", work)
    monkeypatch.setattr(build_app, "RELEASE_DIR", tmp_path / "release")
    for name in ("ensure_dependencies", "validate_project", "compile_source"):
        monkeypatch.setattr(build_app, name, lambda: None)
    for name in ("update_version", "update_default_repository"):
        monkeypatch.setattr(build_app, name, lambda value: None)
    monkeypatch.setattr(build_app, "resolve_github_repository", lambda value: value)
    monkeypatch.setattr(build_app, "generate_icon", lambda: tmp_path / "icon.ico")
    def forbidden_client_read(*args, **kwargs):
        pytest.fail("--no-bundle-oauth must not read configured credentials")
    monkeypatch.setattr(build_app, "resolve_oauth_client", forbidden_client_read)
    def fake_packager(command, **kwargs):
        for source, destination in build_app.runtime_ssl_data():
            sep = ";" if sys.platform.startswith("win") else ":"
            index = command.index(f"{source}{sep}{destination}")
            assert command[index - 1] == "--add-data"
        output = work / "dist" / build_app.APP_NAME
        output.mkdir(parents=True)
        (output / "Import_Localize.exe").write_bytes(b"test executable")
    monkeypatch.setattr(build_app, "run", fake_packager)
    monkeypatch.setattr(build_app, "verify_frozen_app", lambda output: [{"status": "ok"}])
    archive = build_app.build("1.10.0", oauth_client=tmp_path / "private.json",
                              no_bundle_oauth=True, github_repository="longnguy3n/Import-Localize")
    with zipfile.ZipFile(archive) as package:
        assert "oauth_client.json" not in package.namelist()
        manifest = json.loads(package.read("build_manifest.json"))
        assert manifest["oauth_client_bundled"] is False
