from __future__ import annotations

from dataclasses import dataclass

from import_localize.services.session_permission_cache import (
    EditorPermissionSessionCache,
)


@dataclass
class FakeCredentials:
    client_id: str = "desktop-client"
    refresh_token: str = "refresh-account-a"
    token: str = "access-token"


def test_permission_is_reused_for_same_sheet_and_account():
    cache = EditorPermissionSessionCache(scope_version=1)
    credentials = FakeCredentials()

    assert cache.get(credentials, "sheet-1") is None
    cache.remember(credentials, "sheet-1", "DG_Localization")

    assert cache.get(credentials, "sheet-1") == "DG_Localization"
    assert len(cache) == 1


def test_each_sheet_has_an_independent_entry():
    cache = EditorPermissionSessionCache(scope_version=1)
    credentials = FakeCredentials()
    cache.remember(credentials, "sheet-1", "Sheet One")
    cache.remember(credentials, "sheet-2", "Sheet Two")

    assert cache.get(credentials, "sheet-1") == "Sheet One"
    assert cache.get(credentials, "sheet-2") == "Sheet Two"
    assert len(cache) == 2


def test_changing_account_does_not_reuse_old_permission():
    cache = EditorPermissionSessionCache(scope_version=1)
    account_a = FakeCredentials(refresh_token="refresh-account-a")
    account_b = FakeCredentials(refresh_token="refresh-account-b")
    cache.remember(account_a, "sheet-1", "DG_Localization")

    assert cache.get(account_b, "sheet-1") is None


def test_forget_and_clear_remove_entries():
    cache = EditorPermissionSessionCache(scope_version=1)
    credentials = FakeCredentials()
    cache.remember(credentials, "sheet-1", "Sheet One")
    cache.remember(credentials, "sheet-2", "Sheet Two")

    cache.forget(credentials, "sheet-1")
    assert cache.get(credentials, "sheet-1") is None
    assert cache.get(credentials, "sheet-2") == "Sheet Two"

    cache.clear()
    assert len(cache) == 0
