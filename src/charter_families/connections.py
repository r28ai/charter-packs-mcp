# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Which apps a family server can reach, and handing stored credentials to the packs.

Three sources, in this order of precedence:

1. **The environment** — a variable set in the client's config wins, always. An
   app whose packs were configured from it at startup is left alone.
2. **The keychain** — what ``login`` or the ``connect`` tool stored. Read at
   startup, and again whenever a call fails for want of a credential, so an app
   connected mid-session works on the next call without a restart.
3. **Nothing** — the tool is still listed, and calling it says how to connect.

A stored value reaches a pack the way that pack already takes one: its
``configure(api_key)``, its ``configure(credential_provider)``, or the
environment variables it reads on every call. No pack knows this module exists.
"""

from __future__ import annotations

import importlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

from charter import CredentialError
from charter.auth import StaticTokenProvider, TokenGrant

from charter_families.apps import App, app_for_pack
from charter_families.oauth import PublicClient, RefreshingGrant

__all__ = ["Connections", "grant_record", "public_client"]


def _module(pack: str) -> Any:
    return importlib.import_module(f"charter.packs.{pack}")


def _pack_configured(pack: str) -> bool:
    """Whether a pack can already authenticate: configured in code or from its variables."""
    module = _module(pack)
    for attr in ("_credentials", "_headers"):
        holder = getattr(module, attr, None)
        if holder is not None and hasattr(holder, "is_configured"):
            return bool(holder.is_configured)
    return False


def public_client(app: App, client_id: str, client_secret: Optional[str] = None) -> PublicClient:
    sign_in = app.sign_in
    assert sign_in is not None
    return PublicClient(
        authorization_endpoint=sign_in.authorization_endpoint,
        token_endpoint=sign_in.token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        scope_param=sign_in.scope_param,
        scope_separator=sign_in.scope_separator,
        response_root=sign_in.response_root,
        authorization_params=dict(sign_in.authorization_params),
    )


def grant_record(client_id: str, grant: TokenGrant) -> Dict[str, Any]:
    return {
        "type": "oauth",
        "client_id": client_id,
        "access_token": grant.access_token,
        "refresh_token": grant.refresh_token,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "scopes": list(grant.scopes),
    }


def _grant(record: Mapping[str, Any]) -> TokenGrant:
    expires = record.get("expires_at")
    return TokenGrant(
        access_token=record["access_token"],
        refresh_token=record.get("refresh_token"),
        expires_at=datetime.fromisoformat(expires) if expires else None,
        scopes=list(record.get("scopes") or []),
    )


class Connections:
    """The apps one server's packs belong to, and where each one's credential came from."""

    def __init__(
        self,
        packs: Sequence[str],
        *,
        store: Optional[Any] = None,
        environ: Optional[MutableMapping[str, str]] = None,
    ) -> None:
        self.apps: List[App] = []
        for pack in packs:
            app = app_for_pack(pack)
            if app not in self.apps:
                self.apps.append(app)
        self.packs = tuple(packs)
        self._store = store
        self._environ = os.environ if environ is None else environ
        # Decided once, before anything here installs a value: what the
        # environment (or the host's own code) already configured is theirs.
        self.from_env = {
            app.key
            for app in self.apps
            if any(_pack_configured(p) for p in app.packs if p in self.packs)
        }
        self._installed: Dict[str, str] = {}
        self._refreshers: Dict[str, RefreshingGrant] = {}

    @property
    def store(self) -> Any:
        if self._store is None:
            from charter_families.keychain import open_store

            self._store = open_store()
        return self._store

    # -- reading state ---------------------------------------------------------

    def state(self, app: App) -> str:
        if app.key in self.from_env:
            return "set in the environment"
        if app.key in self._installed:
            return "connected"
        return "not connected"

    def missing(self) -> List[App]:
        return [app for app in self.apps if self.state(app) == "not connected"]

    def load(self) -> List[str]:
        """Install whatever the store holds that is new. Returns the apps it changed."""
        changed: List[str] = []
        for app in self.apps:
            if app.key in self.from_env:
                continue
            raw = self.store.get(app.key)
            if not raw or raw == self._installed.get(app.key):
                continue
            self.install(app, json.loads(raw))
            self._installed[app.key] = raw
            changed.append(app.key)
        return changed

    # -- writing state ---------------------------------------------------------

    def save(self, app: App, record: Mapping[str, Any]) -> None:
        raw = json.dumps(record)
        self.store.set(app.key, raw)
        self.install(app, record)
        self._installed[app.key] = raw
        self.from_env.discard(app.key)

    def forget(self, app: App) -> None:
        self.store.delete(app.key)
        self._installed.pop(app.key, None)
        self._refreshers.pop(app.key, None)

    def install(self, app: App, record: Mapping[str, Any]) -> None:
        """Hand ``record`` to every pack ``app`` covers, the way each pack takes credentials."""
        kind = record.get("type")
        if kind == "key":
            values: Mapping[str, str] = record["values"]
            if app.install == "env":
                self._environ.update(values)
                return
            value = values[app.fields[0].env]
            for pack in app.packs:
                module = _module(pack)
                if app.install == "api_key":
                    module.configure(value)
                else:
                    module.configure(StaticTokenProvider(value))
            return
        if kind == "google":
            self._environ.update(
                {
                    "GOOGLE_CLIENT_ID": record["client_id"],
                    "GOOGLE_CLIENT_SECRET": record["client_secret"],
                    "GOOGLE_REFRESH_TOKEN": record["refresh_token"],
                }
            )
            return
        if kind == "oauth":
            grant = _grant(record)
            provider: Any
            if grant.refresh_token and grant.expires_at is not None:
                client = public_client(app, record["client_id"])

                def persist(
                    new: TokenGrant, app: App = app, client_id: str = record["client_id"]
                ) -> None:
                    raw = json.dumps(grant_record(client_id, new))
                    self.store.set(app.key, raw)
                    self._installed[app.key] = raw

                provider = RefreshingGrant(client, grant, on_refresh=persist)
                self._refreshers[app.key] = provider
            else:
                provider = StaticTokenProvider(grant.access_token)
            for pack in app.packs:
                module = _module(pack)
                if app.install == "api_key":
                    # Linear takes a personal key raw and an OAuth token as Bearer.
                    module.configure(f"Bearer {grant.access_token}")
                else:
                    module.configure(provider)
            return
        raise CredentialError(f"unrecognised stored credential for {app.name}: {kind!r}")

    async def before_call(self, pack: str) -> None:
        """Renew a sign-in an API-key pack holds as a static header (Linear's OAuth token)."""
        try:
            app = app_for_pack(pack)
        except KeyError:
            return
        refresher = self._refreshers.get(app.key)
        if refresher is None or app.install != "api_key":
            return
        grant = await refresher.current()
        for p in app.packs:
            _module(p).configure(f"Bearer {grant.access_token}")
