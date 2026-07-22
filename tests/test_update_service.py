from __future__ import annotations

import pytest

from import_localize.services.update_service import (
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
