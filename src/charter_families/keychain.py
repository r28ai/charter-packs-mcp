# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
The operating system's keychain, for credentials a sign-in produced (``keyring``).

macOS Keychain, Windows Credential Manager, or the Secret Service on Linux, via
``keyring``. Each connected app is one entry under the service ``charter``,
holding a JSON document: an API key, or a grant and when it lapses.

Where there is no keychain — a container, a headless Linux box with no Secret
Service — entries go to a file instead, readable by its owner alone, the way
``gh`` falls back to ``hosts.yml``. ``$CHARTER_CREDENTIALS_FILE`` forces the
file, which is also how a test points this somewhere harmless.

Nothing here is read by the library's core. A pack still reads its environment
variables and its ``configure()``; this store is what :mod:`charter_families`
fills those from when neither was set.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Protocol

__all__ = ["FileStore", "KeychainStore", "SecretStore", "open_store"]

SERVICE = "charter"

# What people call each backend. The class itself is named ``Keyring`` on macOS
# and the Secret Service alike, which printed "Stored in the Keyring keychain".
_BACKEND_NAMES = {
    "keyring.backends.macOS": "the macOS Keychain",
    "keyring.backends.Windows": "Windows Credential Manager",
    "keyring.backends.SecretService": "the Secret Service",
    "keyring.backends.libsecret": "the Secret Service",
    "keyring.backends.kwallet": "KWallet",
}


class SecretStore(Protocol):
    location: str

    def get(self, name: str) -> Optional[str]: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class KeychainStore:
    """Entries in the OS keychain, one per app."""

    def __init__(self, keyring_module: object) -> None:
        self._keyring = keyring_module
        backend = type(keyring_module.get_keyring())  # type: ignore[attr-defined]
        self.location = _BACKEND_NAMES.get(backend.__module__, f"the {backend.__name__} keychain")

    def get(self, name: str) -> Optional[str]:
        return self._keyring.get_password(SERVICE, name)  # type: ignore[attr-defined]

    def set(self, name: str, value: str) -> None:
        self._keyring.set_password(SERVICE, name, value)  # type: ignore[attr-defined]

    def delete(self, name: str) -> None:
        try:
            self._keyring.delete_password(SERVICE, name)  # type: ignore[attr-defined]
        except Exception:  # not there is the outcome asked for
            pass


class FileStore:
    """One JSON file, ``0600`` in a ``0700`` directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.location = str(path)

    def _read(self) -> Dict[str, str]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _write(self, data: Dict[str, str]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp, self.path)

    def get(self, name: str) -> Optional[str]:
        return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        data = self._read()
        data[name] = value
        self._write(data)

    def delete(self, name: str) -> None:
        data = self._read()
        if data.pop(name, None) is not None:
            self._write(data)


def _default_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "charter" / "credentials.json"


def open_store() -> SecretStore:
    """The keychain if there is a usable one, the owner-only file if not."""
    forced = os.environ.get("CHARTER_CREDENTIALS_FILE")
    if forced:
        return FileStore(Path(forced))
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return FileStore(_default_file())
    if isinstance(keyring.get_keyring(), fail.Keyring):
        print(
            f"charter: no keychain available; storing credentials in {_default_file()} (mode 600)",
            file=sys.stderr,
        )
        return FileStore(_default_file())
    return KeychainStore(keyring)
