# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
The operating system's keychain, for credentials a sign-in produced (``keyring``).

macOS Keychain, Windows Credential Manager, or the Secret Service on Linux, via
``keyring``. Each connected app is one entry under the service ``charter``,
holding a JSON document: an API key, or a grant and when it lapses.

Where there is no keychain — a container, a headless Linux box with no Secret
Service — or one that does not answer — a Secret Service that is locked with no
one to unlock it, over SSH or from cron — entries go to a file instead,
readable by its owner alone, the way ``gh`` falls back to ``hosts.yml``.
``$CHARTER_CREDENTIALS_FILE`` forces the file, which is also how a test points
this somewhere harmless.

Windows Credential Manager holds at most 2,560 bytes per entry, stored as UTF-16:
1,280 characters. The largest entry a family writes, a Google grant with every
scope a family asks for, is about 720; ``tests/test_connect.py`` keeps it under.

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

from charter import CredentialError

__all__ = ["FileStore", "KeychainStore", "SecretStore", "open_store"]

SERVICE = "charter"

WINDOWS_ENTRY_LIMIT = 1280

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
        backend = keyring_module.get_keyring()  # type: ignore[attr-defined]
        # Where several backends are usable (a Linux desktop with both KWallet and
        # the Secret Service), keyring chains them and writes to the first.
        kind = type((getattr(backend, "backends", None) or [backend])[0])
        self.location = _BACKEND_NAMES.get(kind.__module__, f"the {kind.__name__} keychain")

    # keyring raises its own errors, and the backends below it theirs (D-Bus,
    # pywin32's): none is a CredentialError, which is what `login` reports and the
    # server turns into a sentence for the agent rather than a traceback.
    def get(self, name: str) -> Optional[str]:
        try:
            return self._keyring.get_password(SERVICE, name)  # type: ignore[attr-defined]
        except Exception as exc:
            raise CredentialError(f"{self.location} did not answer: {exc}") from exc

    def set(self, name: str, value: str) -> None:
        try:
            self._keyring.set_password(SERVICE, name, value)  # type: ignore[attr-defined]
        except Exception as exc:
            raise CredentialError(
                f"{self.location} would not store it: {exc}. To keep credentials in an "
                "owner-only file instead, set CHARTER_CREDENTIALS_FILE to its path."
            ) from exc

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
        from keyring.backends import fail, null
    except ImportError:
        return FileStore(_default_file())
    backend = keyring.get_keyring()
    if isinstance(backend, (fail.Keyring, null.Keyring)):  # null stores nothing, silently
        return _fallback("no keychain available")
    try:
        # A Secret Service that is running but locked, or a session bus out of reach,
        # passes the check above and fails on first use: find out now, not mid-login.
        backend.get_password(SERVICE, "-")
    except Exception as exc:
        return _fallback(f"the keychain did not answer ({exc})")
    return KeychainStore(keyring)


def _fallback(reason: str) -> FileStore:
    path = _default_file()
    print(f"charter: {reason}; storing credentials in {path} (mode 600)", file=sys.stderr)
    return FileStore(path)
