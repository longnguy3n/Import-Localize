from __future__ import annotations

import pytest

from import_localize.services.update_service import (
    UpdateRelease,
    _write_apply_script,
    UpdateError,
    compare_versions,
    is_newer_version,
    normalize_repository,
)


def test_normalize_repository_accepts_slug_and_url():
    assert normalize_repository("owner/repository") == "owner/repository"
    assert (
        normalize_repository("https://github.com/owner/repository.git")
        == "owner/repository"
    )


def test_normalize_repository_rejects_invalid_value():
    with pytest.raises(UpdateError):
        normalize_repository("not-a-repository")


def test_semver_comparison():
    assert compare_versions("1.5.0", "1.4.9") == 1
    assert compare_versions("1.5.0", "1.5.0") == 0
    assert compare_versions("1.5.0-beta.1", "1.5.0") == -1
    assert compare_versions("1.5.0-beta.2", "1.5.0-beta.1") == 1
    assert is_newer_version("2.0.0", "1.9.9") is True


def test_apply_script_contains_ready_handshake_and_rollback(tmp_path):
    stage = tmp_path / "stage"
    payload = tmp_path / "payload"
    target = tmp_path / "target"
    stage.mkdir()
    payload.mkdir()
    target.mkdir()
    release = UpdateRelease(
        repository="owner/repository",
        version="1.6.2",
        tag_name="v1.6.2",
        title="v1.6.2",
        notes="",
        html_url="",
        asset_name="Import_Localize_v1.6.2.zip",
        download_url="https://example.invalid/update.zip",
        checksum_url="https://example.invalid/update.zip.sha256.txt",
        size_bytes=1,
    )
    script = _write_apply_script(
        staging_dir=stage,
        payload_dir=payload,
        target_dir=target,
        release=release,
    )
    content = script.read_text(encoding="utf-8-sig")
    assert "updater_ready.flag" in content
    assert "Test-TargetWritable" in content
    assert "Start-ElevatedUpdater" in content
    assert "backup_current" in content
    assert "Rollback completed" in content
    assert "__RELEASE_VERSION__" not in content
