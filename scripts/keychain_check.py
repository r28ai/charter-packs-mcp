# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Store, read back from another process, and forget, through this machine's own keychain.

    python scripts/keychain_check.py "Windows Credential Manager"

The argument is what the store must turn out to be. CI runs this on every OS and on
three kinds of Linux machine (see .github/workflows/ci.yml); the unit tests stand
each keychain in with a fake, and this is what says the real ones behave. Every
value written is fake, and every one is removed at the end.
"""

from __future__ import annotations

import subprocess
import sys

from charter import CredentialError

from charter_packs_mcp import FAMILIES, tools_for
from charter_packs_mcp.apps import APPS
from charter_packs_mcp.connections import Connections
from charter_packs_mcp.keychain import WINDOWS_ENTRY_LIMIT, open_store
from charter_packs_mcp.signin import google_scopes

FAMILY = "support"  # nine Google scopes, the most any family asks for, and Linear's key


def cli(*args: str) -> str:
    done = subprocess.run(
        [sys.executable, "-m", "charter_packs_mcp", FAMILY, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if done.returncode != 0:
        raise SystemExit(f"`{' '.join(args)}` failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout


def main() -> None:
    expected = sys.argv[1]
    store = open_store()
    print(f"store: {store.location}")
    if expected not in store.location:
        raise SystemExit(f"expected {expected!r}")

    packs = sorted({t.pack for t in tools_for([FAMILIES[FAMILY]]) if t.pack})
    connections = Connections(packs, store=store)
    # The largest entry a family writes: its Google grant, with a refresh token at
    # the 512 bytes Google allows. This is the one Credential Manager could refuse.
    google = {
        "type": "google",
        "client_id": "0" * 12 + "-" + "x" * 32 + ".apps.googleusercontent.com",
        "client_secret": "GOCSPX-" + "x" * 28,
        "refresh_token": "1//" + "x" * 509,
        "scopes": google_scopes(packs),
    }
    connections.save(APPS["google"], google)
    connections.save(APPS["linear"], {"type": "key", "values": {"LINEAR_API_KEY": "lin_api_ci"}})
    print("stored: Google, with a 512-character refresh token, and a Linear key")

    line = next(x for x in cli("status").splitlines() if x.startswith("Connected:"))
    if "Google" not in line or "Linear" not in line:
        raise SystemExit(f"another process did not read both back: {line!r}")
    print(f"another process reads them: {line}")

    if "Windows" in expected:
        try:
            store.set("ci-oversize", "x" * (WINDOWS_ENTRY_LIMIT + 200))
        except CredentialError as exc:
            print(f"over Credential Manager's limit, refused and said so: {exc}")
        else:
            store.delete("ci-oversize")
            raise SystemExit("Credential Manager took an entry over the limit this code assumes")

    cli("logout", "google", "linear")
    if store.get("google") is not None or store.get("linear") is not None:
        raise SystemExit("logout in another process left an entry behind")
    print("another process forgot them: done")


if __name__ == "__main__":
    main()
