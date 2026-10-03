# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Connecting an app: a key for most, a browser sign-in for Google.

Two entry points share everything below:

- ``login`` from a terminal — ``github-linear-mcp login`` connects each app
  the server uses, in turn. Keys are read with ``getpass``, so they are never
  echoed, logged or sent anywhere but the API that issued them.
- the ``connect`` tool, which the agent calls. For a key it explains where to
  get one and where it goes — it never asks for one, because a key typed into a
  chat is a key in a transcript. For Google, once the person's own OAuth client
  is set, it starts the browser sign-in and returns at once; the sign-in
  finishes in the background and the next call picks it up. Where every app
  stands is ``connection_status``, which changes nothing and is marked so.

Every credential is checked with one read-only call to its own API before it is
stored, so a wrong key is caught here rather than on the first real call.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set
from urllib.parse import parse_qs, urlparse

from charter import APIError, CharterError, CredentialError
from charter.auth import AuthorizationRequest, OAuth2Flow, states_match

from charter_families.apps import (
    APPS,
    GOOGLE_CHECKS,
    LOOPBACK_PORT,
    LOOPBACK_REDIRECT,
    NO_SUCH_ID,
    App,
)
from charter_families.connections import Connections

__all__ = [
    "ConnectTool",
    "SetupPrompt",
    "StatusTool",
    "how_to_connect",
    "login",
    "status_report",
    "status_text",
]

# Google answers a client that does not accept the loopback redirect on its own
# page, so the callback never comes. A Desktop app client accepts it; a Web
# application client — common among people who already made one — does not.
_REDIRECT_HINT = (
    "If Google says redirect_uri_mismatch, the OAuth client is a Web application: "
    f"add {LOOPBACK_REDIRECT} to its Authorized redirect URIs, or make a Desktop app "
    "client instead."
)

_PAGE = (
    "<!doctype html><meta charset=utf-8><title>Charter</title>"
    "<body style='font:16px system-ui;margin:4em auto;max-width:32em'>"
    "<h1 style='font-size:20px'>{title}</h1><p>{body}</p></body>"
)


# -- the loopback listener -------------------------------------------------------


class Loopback:
    """One callback on 127.0.0.1, answered once (RFC 8252 §7.3)."""

    def __init__(self, port: int = LOOPBACK_PORT) -> None:
        self.port = port
        self._result: asyncio.Future[Dict[str, str]] = asyncio.get_running_loop().create_future()
        self._server: Optional[asyncio.AbstractServer] = None
        self._open: Set[asyncio.StreamWriter] = set()

    async def __aenter__(self) -> Loopback:
        try:
            self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
        except OSError as exc:
            raise CredentialError(
                f"port {self.port} on 127.0.0.1 is in use, and it is the address this "
                "sign-in is registered with. Close whatever holds it and try again."
            ) from exc
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._server is not None:
            self._server.close()
            # A browser opens spare connections beside the one it sends the callback
            # on, and may never use them. Since 3.12 wait_closed() waits for every
            # connection, so one left open hung the login; one closed only when the
            # process exited printed a TypeError from inside asyncio after "Connected".
            for writer in list(self._open):
                writer.transport.abort()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._open.add(writer)
        try:
            line = (await reader.readline()).decode("latin-1")
            if not line:  # a spare connection, closed without a request
                return
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass
            parts = line.split(" ")
            target = urlparse(parts[1] if len(parts) > 1 else "/")
            if target.path != "/callback":
                status, title, body = "404 Not Found", "Not found", ""
            else:
                params = {k: v[0] for k, v in parse_qs(target.query).items()}
                if "error" in params:
                    status, title, body = "200 OK", "Not connected", params["error"]
                else:
                    status, title = "200 OK", "Connected"
                    body = "You can close this tab and go back to your agent."
                if not self._result.done():
                    self._result.set_result(params)
            page = _PAGE.format(title=title, body=body).encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(page)}\r\nConnection: close\r\n\r\n".encode()
                + page
            )
            await writer.drain()
        finally:
            self._open.discard(writer)
            writer.close()

    async def wait(self, timeout: float = 300) -> Dict[str, str]:
        try:
            return await asyncio.wait_for(asyncio.shield(self._result), timeout)
        except asyncio.TimeoutError as exc:
            raise CredentialError(
                f"no answer from the browser within five minutes; start again. {_REDIRECT_HINT}"
            ) from exc


def _code_from(params: Mapping[str, str], request: AuthorizationRequest) -> str:
    if "error" in params:
        raise CredentialError(f"sign-in refused: {params['error']}")
    if not states_match(request.state, params.get("state", "")):
        raise CredentialError("sign-in answered with the wrong state; start again")
    if not params.get("code"):
        raise CredentialError("sign-in returned no code; start again")
    return params["code"]


# -- checking and storing --------------------------------------------------------


async def verify(
    app: App, packs: Sequence[str] = (), granted: Optional[Sequence[str]] = None
) -> List[str]:
    """One read-only call to the app's own API, with the credential just installed.

    Raises if the app refuses the credential. Returns what is worth saying about
    one it accepted: for Google, each API among ``packs`` still turned off.
    """
    if app.key == "google":
        return await _check_google(packs, granted)
    if app.check is None:
        return []
    from charter_families import _tool

    step, args = app.check
    try:
        await _tool(step).ainvoke(dict(args))
    except CharterError as exc:
        raise CredentialError(f"{app.name} did not accept that credential: {exc}") from exc
    return []


async def _check_google(packs: Sequence[str], granted: Optional[Sequence[str]]) -> List[str]:
    """A read from each Google API the server calls, with the grant just made."""
    from charter_families import _tool

    notes: List[str] = []
    for pack in packs:
        if pack not in GOOGLE_CHECKS:
            continue
        step, args, api, service = GOOGLE_CHECKS[pack]
        tool = _tool(step)
        if granted and not set(tool.scopes) <= set(granted):
            continue  # a scope the person unticked, which the sign-in already said
        try:
            await tool.ainvoke(dict(args))
        except CredentialError as exc:  # the grant itself: a revoked token, a wrong secret
            raise CredentialError(f"Google did not accept the sign-in: {exc}") from exc
        except APIError as exc:
            if exc.status_code == 404 and NO_SUCH_ID in args.values():
                continue  # it looked for the ID that cannot exist, so it is on
            body = exc.body.lower()
            if exc.status_code == 403 and (
                "service_disabled" in body or "has not been used" in body
            ):
                notes.append(
                    f"The {api} is turned off in the Google Cloud project your OAuth client "
                    "belongs to, so its tools will answer 403 until it is on: "
                    f"https://console.cloud.google.com/apis/library/{service}"
                )
            else:
                notes.append(f"The {api} did not answer as expected: {exc}")
        except CharterError as exc:
            notes.append(f"The {api} could not be checked: {exc}")
    return notes


async def _store_checked(
    connections: Connections, app: App, record: Mapping[str, Any]
) -> List[str]:
    previous = connections.store.get(app.key)
    connections.install(app, record)
    try:
        notes = await verify(app, connections.packs, record.get("scopes"))
    except CredentialError:
        if previous:
            import json

            connections.install(app, json.loads(previous))
        raise
    connections.save(app, record)
    return notes


# -- the flows -------------------------------------------------------------------


def google_scopes(packs: Sequence[str]) -> List[str]:
    """The scopes the Google tools this server serves declare — no wider consent than that."""
    from charter.auth import scopes_for

    from charter_families import _module_tools

    return scopes_for([t for p in packs if p in APPS["google"].packs for t in _module_tools(p)])


async def _google_sign_in(
    connections: Connections,
    app: App,
    *,
    client_id: str,
    client_secret: str,
    scopes: Sequence[str],
    open_browser: Callable[[str], Any],
    announce: Callable[[str], None],
) -> List[str]:
    """The browser sign-in, over the person's own OAuth client, back to the loopback.

    Returns, and announces, each Google API the server calls that is turned off.
    """
    assert app.sign_in is not None
    flow = OAuth2Flow(
        app.sign_in,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=LOOPBACK_REDIRECT,
    )
    request = flow.authorize(scopes)
    async with Loopback() as loopback:
        announce(
            f"Opening your browser to sign in to {app.name}. {_REDIRECT_HINT}\n"
            f"If it does not open:\n{request.url}"
        )
        open_browser(request.url)
        params = await loopback.wait()
    # Raises on a grant with no refresh token, which would die within the hour.
    grant = await flow.exchange(_code_from(params, request), code_verifier=request.code_verifier)
    dropped = sorted(set(scopes) - set(grant.scopes)) if grant.scopes else []
    if dropped:
        announce("Not granted, so the tools needing them will answer 403: " + ", ".join(dropped))
    record = {
        "type": "google",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": grant.refresh_token,
        "scopes": grant.scopes,
    }
    notes = await _store_checked(connections, app, record)
    for note in notes:
        announce(note)
    return notes


def _google_client(environ: Mapping[str, str]) -> tuple[str, str]:
    return environ.get("GOOGLE_CLIENT_ID", ""), environ.get("GOOGLE_CLIENT_SECRET", "")


def how_to_connect(app: App, command: str, *, environ: Optional[Mapping[str, str]] = None) -> str:
    """One sentence on how to connect ``app``, for the model or for a person."""
    env = os.environ if environ is None else environ
    if app.sign_in is not None:
        if all(_google_client(env)):
            return f"call the `connect` tool with app={app.key!r}; it opens a browser sign-in"
        return (
            f"needs the user's own Google OAuth client, made once in about ten minutes "
            f"({app.guide}); then they run `{command} login {app.key}` in a terminal"
        )
    fields = ", ".join(f.env for f in app.fields)
    return (
        f"needs a key from {app.key_url}; the user runs `{command} login {app.key}` in a "
        f"terminal, or sets {fields} in this server's config"
    )


def status_text(connections: Connections, command: str) -> str:
    """Where each app stands — the server's opening instructions and the `connect` tool's answer."""
    lines: List[str] = []
    ready = [a.name for a in connections.apps if connections.state(a) != "not connected"]
    if ready:
        lines.append("Connected: " + ", ".join(ready) + ".")
    missing = connections.missing()
    if not missing:
        lines.append("Every app this server uses is connected.")
        return "\n".join(lines)
    lines.append("Not connected yet:")
    for app in missing:
        line = f"- {app.name}: {how_to_connect(app, command)}."
        if app.note:
            line += f" {app.note}"
        lines.append(line)
    lines.append(
        "Never ask the user to paste a key or token into the chat. A tool for an app that "
        "is not connected stays listed, and fails with a message saying how to connect it."
    )
    return "\n".join(lines)


# -- the terminal ----------------------------------------------------------------


async def login(
    connections: Connections,
    apps: Sequence[str],
    *,
    command: str,
    open_browser: Callable[[str], Any] = webbrowser.open,
    ask: Callable[[str], str] = input,
    ask_secret: Callable[[str], str] = getpass.getpass,
    say: Callable[[str], None] = print,
    interactive: Optional[bool] = None,
) -> int:
    """Connect ``apps`` (every unconnected one when empty), one after another."""
    tty: bool = sys.stdin.isatty() if interactive is None else interactive
    chosen = [APPS[a] for a in apps] if apps else connections.missing()
    unknown = [a for a in apps if a not in {x.key for x in connections.apps}]
    if unknown:
        say(
            f"This server does not use {', '.join(unknown)}. It uses: "
            + ", ".join(a.key for a in connections.apps)
        )
        return 2
    if not chosen:
        say("Every app this server uses is already connected.")
        return 0
    failures = 0
    for app in chosen:
        say(f"\n{app.name}")
        try:
            await _login_one(
                connections,
                app,
                command=command,
                open_browser=open_browser,
                ask=ask,
                ask_secret=ask_secret,
                say=say,
                interactive=tty,
            )
            say(f"  Connected. Stored in {connections.store.location}.")
        except CredentialError as exc:
            failures += 1
            say(f"  Not connected: {exc}")
    return 1 if failures else 0


async def _login_one(
    connections: Connections,
    app: App,
    *,
    command: str,
    open_browser: Callable[[str], Any],
    ask: Callable[[str], str],
    ask_secret: Callable[[str], str],
    say: Callable[[str], None],
    interactive: bool,
) -> None:
    if app.sign_in is not None:
        cid, secret = _google_client(os.environ)
        if not (cid and secret):
            if not interactive:
                raise CredentialError(f"run `{command} login {app.key}` in a terminal")
            say(f"  {app.name} needs your own OAuth client, made once: {app.guide}")
            cid = cid or ask("  OAuth client ID: ").strip()
            secret = secret or ask_secret("  OAuth client secret (hidden): ").strip()
            if not (cid and secret):
                raise CredentialError("nothing entered")
        await _google_sign_in(
            connections,
            app,
            client_id=cid,
            client_secret=secret,
            scopes=google_scopes(connections.packs),
            open_browser=open_browser,
            announce=lambda m: say("  " + m),
        )
        return
    if not interactive:
        raise CredentialError(
            f"a key is asked for at a prompt; run `{command} login {app.key}` in a terminal"
        )
    say(f"  Opening {app.key_url}" + (f" — {app.note}" if app.note else ""))
    open_browser(app.key_url)
    values: Dict[str, str] = {}
    for field in app.fields:
        prompt = f"  {field.label}{' (hidden)' if field.secret else ''}: "
        value = (ask_secret(prompt) if field.secret else ask(prompt)).strip()
        if not value:
            raise CredentialError("nothing entered")
        values[field.env] = value
    await _store_checked(connections, app, {"type": "key", "values": values})


# -- the agent's side: one tool and one prompt -----------------------------------


@dataclass
class ConnectTool:
    """The ``connect`` tool: start connecting one app.

    Not read-only, because for Google it starts a sign-in that stores a credential.
    Where each app stands is :class:`StatusTool`'s, which is read-only, so a client
    that refuses every other tool without asking — ``codex exec`` — can still see it.
    """

    connections: Connections
    command: str
    open_browser: Callable[[str], Any] = webbrowser.open
    name: str = "connect"
    read_only: bool = False

    def __post_init__(self) -> None:
        self._tasks: Set[asyncio.Task[None]] = set()
        # Sign-ins that failed in the background, by app, for the status to report.
        self.errors: Dict[str, str] = {}
        self.notes: Dict[str, str] = {}  # what a sign-in that succeeded still wants said

    @property
    def description(self) -> str:
        return (
            "Connect one app this server uses. For an app that issues keys, says where to "
            "get one and the terminal command that stores it. For Google, once the user's "
            "own OAuth client is set, starts the browser sign-in and returns at once: the "
            "user approves in the browser and the next call works. To see which apps are "
            "connected, call `connection_status`. Never ask the user for a key in the chat."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "enum": [a.key for a in self.connections.apps],
                    "description": "The app to connect.",
                }
            },
            "required": ["app"],
            "additionalProperties": False,
        }

    async def call(self, arguments: Mapping[str, Any]) -> str:
        self.connections.load()
        key = arguments.get("app")
        if not key:  # the schema requires one; answer with the status rather than fail
            return status_report(self.connections, self.command, self.errors, self.notes)
        if key not in {a.key for a in self.connections.apps}:
            return f"This server does not use {key!r}."
        app = APPS[key]
        if self.connections.state(app) != "not connected":
            return f"{app.name} is already {self.connections.state(app)}. To switch accounts, the user runs `{self.command} login {key}`."
        cid, secret = _google_client(os.environ)
        if app.sign_in is None or not (cid and secret):
            note = f" {app.note}" if app.note else ""
            return f"{app.name} {how_to_connect(app, self.command)}.{note}"
        self.errors.pop(key, None)
        self.notes.pop(key, None)
        opened: List[str] = []
        self._spawn(
            key,
            _google_sign_in(
                self.connections,
                app,
                client_id=cid,
                client_secret=secret,
                scopes=google_scopes(self.connections.packs),
                open_browser=self.open_browser,
                announce=opened.append,
            ),
        )
        await asyncio.sleep(0.2)  # long enough for the listener to bind and the URL to be built
        if key in self.errors:
            return f"{app.name} sign-in could not start: {self.errors[key]}"
        url = opened[0].rsplit("\n", 1)[-1] if opened else ""
        return (
            f"Opened the {app.name} sign-in in the user's browser. Once they approve, "
            f"{app.name} is connected and its tools work on the next call. {_REDIRECT_HINT}"
            + (f" If the browser did not open, the user visits: {url}" if url else "")
        )

    def _spawn(self, key: str, coro: Any) -> None:
        async def run() -> None:
            try:
                notes = await coro
            except Exception as exc:  # reported by `connection_status`
                self.errors[key] = str(exc)
            else:
                if notes:
                    self.notes[key] = " ".join(notes)

        task = asyncio.get_running_loop().create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


@dataclass
class StatusTool:
    """The ``connection_status`` tool: which apps are connected, and how to connect the rest.

    Read-only, so every client runs it without asking. It is the same report the
    server opens with, read again, plus any sign-in that failed in the background.
    """

    connections: Connections
    command: str
    connect: ConnectTool
    name: str = "connection_status"
    read_only: bool = True
    description: str = (
        "See which apps this server is connected to, and how to connect each one that "
        "is not. Changes nothing."
    )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def call(self, arguments: Mapping[str, Any]) -> str:
        self.connections.load()
        return status_report(
            self.connections, self.command, self.connect.errors, self.connect.notes
        )


def status_report(
    connections: Connections,
    command: str,
    errors: Mapping[str, str],
    notes: Optional[Mapping[str, str]] = None,
) -> str:
    """:func:`status_text`, plus how the sign-ins since it was last read went."""
    text = status_text(connections, command)
    if errors:
        text += "\nLast sign-in errors: " + "; ".join(f"{k}: {v}" for k, v in errors.items())
    if notes:
        text += "\nConnected, with a warning: " + "; ".join(f"{k}: {v}" for k, v in notes.items())
    return text


@dataclass(frozen=True)
class SetupPrompt:
    """``/setup``: walk the user through connecting every app this server uses."""

    command: str
    name: str = "setup"
    title: str = "Connect your apps"
    description: str = "Connect every app this server uses, the quickest way each one allows."

    def render(self, details: str = "") -> str:
        text = (
            "Help me connect the apps this server uses.\n\n"
            "1. Call `connection_status` to see what is connected.\n"
            "2. For each app it lists as not connected, call `connect` with that app. Where that "
            "opens a browser sign-in, tell me to approve it, then move on.\n"
            "3. Where an app needs a key, tell me the page to get it from and the exact command "
            f"to run in my terminal (`{self.command} login <app>`). Do not ask me to paste a "
            "key into this chat.\n"
            "4. Call `connection_status` again and tell me what is still missing."
        )
        if details.strip():
            text += f"\n\nContext from me: {details.strip()}"
        return text
