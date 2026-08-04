from __future__ import annotations

import hashlib
from threading import RLock
from typing import Any


class EditorPermissionSessionCache:
    """In-memory Editor permission cache keyed by spreadsheet and OAuth identity.

    The cache intentionally has no persistence. Closing the application starts a
    new session and therefore requires a fresh permission check.
    """

    def __init__(self, scope_version: int = 1):
        self.scope_version = int(scope_version)
        self._values: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def _credential_fingerprint(self, credentials: Any) -> str:
        client_id = str(getattr(credentials, "client_id", "") or "")
        refresh_token = str(getattr(credentials, "refresh_token", "") or "")
        access_token = str(getattr(credentials, "token", "") or "")
        identity_token = refresh_token or access_token
        material = f"{client_id}|{identity_token}|{self.scope_version}".encode(
            "utf-8"
        )
        return hashlib.sha256(material).hexdigest()

    def _key(self, credentials: Any, spreadsheet_id: str) -> tuple[str, str]:
        return (
            str(spreadsheet_id),
            self._credential_fingerprint(credentials),
        )

    def get(self, credentials: Any, spreadsheet_id: str) -> str | None:
        with self._lock:
            return self._values.get(self._key(credentials, spreadsheet_id))

    def remember(
        self,
        credentials: Any,
        spreadsheet_id: str,
        spreadsheet_name: str,
    ) -> None:
        with self._lock:
            self._values[self._key(credentials, spreadsheet_id)] = str(
                spreadsheet_name
            )

    def forget(self, credentials: Any, spreadsheet_id: str) -> None:
        with self._lock:
            self._values.pop(self._key(credentials, spreadsheet_id), None)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)
