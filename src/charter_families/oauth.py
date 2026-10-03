# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Native apps: signing in from a terminal or a desktop, with no secret to ship.

RFC 8252 is how an installed application does OAuth. The application is a
*public* client: it ships to every user, so it cannot keep a secret, and it
proves the code it trades was the one it asked for with PKCE (RFC 7636) instead.
That is what lets one registered client ID be printed in open-source code and
used by everyone, the way ``gh auth login`` and VS Code's GitHub sign-in work.

Two grants cover the APIs Charter ships:

- **Authorization code with a loopback redirect** — the browser comes back to
  ``http://127.0.0.1:<port>/callback`` on the user's own machine. Linear and
  Slack accept it from a public client. Google's desktop clients carry a
  ``client_secret`` that Google itself says is not secret, so
  :class:`PublicClient` sends one when it is given one.
- **Device authorization** (RFC 8628) — the user types a short code at a URL.
  GitHub's ``gh`` uses it, and it needs nothing but a client ID.

What lives here is protocol, the same line ``charter.auth.OAuth2Flow`` draws: the
authorization URL, the code exchange, the refresh, the device poll. The browser,
the listener on 127.0.0.1 and where tokens are kept are the host's.
:mod:`charter_families` is one host.

Responses are read in one place, :func:`_grant_from`, because two of the three
servers bend the standard shape: Slack answers HTTP 200 with ``ok: false`` and
puts a user's token under ``authed_user``, and GitHub answers a pending device
poll with an ``error`` that is not a failure.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional, Union
from urllib.parse import urlencode

import httpx
from charter import CredentialError
from charter.auth import AuthorizationRequest, Credentials, TokenGrant

__all__ = [
    "DeviceCode",
    "DeviceFlow",
    "PublicClient",
    "RefreshingGrant",
]

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _grant_from(
    body: Mapping[str, Any], *, root: Optional[str] = None, previous: Optional[TokenGrant] = None
) -> TokenGrant:
    """A token response as a :class:`TokenGrant`, or the server's refusal as an error."""
    if body.get("ok") is False or "error" in body:
        detail = body.get("error_description") or ""
        raise CredentialError(
            f"sign-in refused: {body.get('error', 'unknown error')}"
            + (f" — {detail}" if detail else "")
        )
    node: Mapping[str, Any] = body.get(root, {}) if root else body
    token = node.get("access_token")
    if not token:
        raise CredentialError("sign-in returned no access token")
    expires_in = node.get("expires_in")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    scope = node.get("scope") or ""
    scopes = [s for s in str(scope).replace(",", " ").split() if s]
    return TokenGrant(
        access_token=token,
        # A server that does not rotate leaves the refresh token out of a
        # refresh response; the one already held stays good.
        refresh_token=node.get("refresh_token") or (previous.refresh_token if previous else None),
        expires_at=expires_at,
        scopes=scopes or (previous.scopes if previous else []),
        raw=dict(body),
    )


async def _post(
    url: str, form: Mapping[str, str], client: Optional[httpx.AsyncClient], timeout: int
) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if client is not None:
        response = await client.post(url, data=dict(form), headers=headers, timeout=timeout)
    else:
        async with httpx.AsyncClient(timeout=timeout) as owned:
            response = await owned.post(url, data=dict(form), headers=headers)
    try:
        body = response.json()
    except ValueError as exc:
        raise CredentialError(
            f"sign-in failed: {url} answered {response.status_code} with no JSON"
        ) from exc
    if not isinstance(body, dict):
        raise CredentialError(f"sign-in failed: {url} answered with {type(body).__name__}")
    if response.status_code >= 400 and "error" not in body:
        body = {**body, "error": f"HTTP {response.status_code}"}
    return body


@dataclass(frozen=True)
class PublicClient:
    """One registered client of one authorization server, used from a user's machine.

    ``scope_param`` and ``scope_separator`` exist for the servers that spell
    scopes their own way: Linear joins them with commas, and Slack asks for a
    user's scopes under ``user_scope`` because a public client may not request
    a bot's. ``response_root`` names where the token sits in the response when
    it is not at the top (Slack's ``authed_user``).
    """

    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    client_secret: Optional[str] = None
    scope_param: str = "scope"
    scope_separator: str = " "
    response_root: Optional[str] = None
    authorization_params: Mapping[str, str] = field(default_factory=dict)
    timeout: int = 20

    def __post_init__(self) -> None:
        if not self.client_id:
            raise CredentialError("PublicClient requires a client_id")

    def authorize(
        self, scopes: Iterable[str], redirect_uri: str, *, state: Optional[str] = None
    ) -> AuthorizationRequest:
        """The URL to open, with PKCE S256 and a fresh ``state``. Pure — no I/O."""
        verifier, challenge = _pkce()
        state = state or secrets.token_urlsafe(32)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            self.scope_param: self.scope_separator.join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **self.authorization_params,
        }
        return AuthorizationRequest(
            url=f"{self.authorization_endpoint}?{urlencode(params)}",
            state=state,
            code_verifier=verifier,
        )

    def _form(self, **fields: str) -> Dict[str, str]:
        form = {"client_id": self.client_id, **fields}
        if self.client_secret:
            form["client_secret"] = self.client_secret
        return form

    async def exchange(
        self,
        code: str,
        *,
        code_verifier: str,
        redirect_uri: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> TokenGrant:
        """Trade the callback's code for tokens. The verifier stands in for a secret."""
        body = await _post(
            self.token_endpoint,
            self._form(
                grant_type="authorization_code",
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            ),
            client,
            self.timeout,
        )
        return _grant_from(body, root=self.response_root)

    async def refresh(
        self, grant: TokenGrant, *, client: Optional[httpx.AsyncClient] = None
    ) -> TokenGrant:
        """A new access token from ``grant``'s refresh token, keeping it if none is sent back."""
        if not grant.refresh_token:
            raise CredentialError("this sign-in has no refresh token; sign in again")
        body = await _post(
            self.token_endpoint,
            self._form(grant_type="refresh_token", refresh_token=grant.refresh_token),
            client,
            self.timeout,
        )
        return _grant_from(body, root=self.response_root, previous=grant)


@dataclass(frozen=True)
class DeviceCode:
    """What the user is shown: a code to type and the page to type it on."""

    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass(frozen=True)
class DeviceFlow:
    """The device authorization grant (RFC 8628), as GitHub serves it."""

    device_endpoint: str
    token_endpoint: str
    client_id: str
    timeout: int = 20

    async def start(
        self, scopes: Iterable[str], *, client: Optional[httpx.AsyncClient] = None
    ) -> DeviceCode:
        body = await _post(
            self.device_endpoint,
            {"client_id": self.client_id, "scope": " ".join(scopes)},
            client,
            self.timeout,
        )
        if "error" in body:
            raise CredentialError(f"sign-in refused: {body['error']}")
        return DeviceCode(
            device_code=body["device_code"],
            user_code=body["user_code"],
            verification_uri=body.get("verification_uri") or body["verification_url"],
            expires_in=int(body.get("expires_in", 900)),
            interval=int(body.get("interval", 5)),
        )

    async def poll(
        self,
        code: DeviceCode,
        *,
        client: Optional[httpx.AsyncClient] = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> TokenGrant:
        """Wait for the user to approve, at the pace the server asks for."""
        interval = code.interval
        waited = 0
        while waited < code.expires_in:
            await sleep(interval)
            waited += interval
            body = await _post(
                self.token_endpoint,
                {
                    "client_id": self.client_id,
                    "device_code": code.device_code,
                    "grant_type": DEVICE_GRANT,
                },
                client,
                self.timeout,
            )
            error = body.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval = int(body.get("interval", interval + 5))
                continue
            return _grant_from(body)
        raise CredentialError("the sign-in code expired before it was approved; start again")


OnGrant = Callable[[TokenGrant], Union[None, Awaitable[None]]]


class RefreshingGrant:
    """A :class:`~charter.auth.CredentialProvider` over a public client's grant.

    Renews the access token ``leeway_seconds`` before it lapses and hands every
    new grant to ``on_refresh``, which is where a host persists it: Linear
    rotates its refresh token on every use, so a grant not written back is a
    sign-in lost by tomorrow. One refresh at a time — concurrent calls wait for
    the one in flight rather than spending the refresh token twice.
    """

    def __init__(
        self,
        client: PublicClient,
        grant: TokenGrant,
        *,
        on_refresh: Optional[OnGrant] = None,
        leeway_seconds: int = 90,
        http: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._client = client
        self._grant = grant
        self._on_refresh = on_refresh
        self._leeway = timedelta(seconds=leeway_seconds)
        self._http = http
        self._lock = asyncio.Lock()
        self._stale = False

    @property
    def grant(self) -> TokenGrant:
        return self._grant

    def _expiring(self) -> bool:
        expires_at = self._grant.expires_at
        return self._stale or (
            expires_at is not None and datetime.now(timezone.utc) >= expires_at - self._leeway
        )

    async def current(self) -> TokenGrant:
        """The grant, renewed first if it is about to lapse."""
        if not self._expiring():
            return self._grant
        async with self._lock:
            if self._expiring():
                self._grant = await self._client.refresh(self._grant, client=self._http)
                self._stale = False
                if self._on_refresh is not None:
                    outcome = self._on_refresh(self._grant)
                    if asyncio.iscoroutine(outcome):
                        await outcome
        return self._grant

    async def get_credentials(self, provider: str) -> Credentials:
        grant = await self.current()
        return Credentials(token=grant.access_token, expires_at=grant.expires_at)

    def invalidate(self, credentials: Credentials) -> None:
        """The API rejected the token, so renew it on the next call."""
        if credentials.token == self._grant.access_token and self._grant.refresh_token:
            self._stale = True
