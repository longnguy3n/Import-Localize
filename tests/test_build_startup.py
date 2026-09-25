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
                  "platform": kwargs["env"]["QT_QPA_PLATFORM"], "qt_version": "test"}
        Path(command[-1]).write_text(json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr=b"")
    monkeypatch.setattr(build_app.subprocess, "run", fake_run)
    reports = build_app.verify_frozen_app(tmp_path)
    assert reports and all(report["main_window_rendered"] for report in reports)


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
