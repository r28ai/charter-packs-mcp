"""Connecting apps: keys, Google's sign-in over the user's own client, the keychain store,
and the server that uses them."""

from __future__ import annotations

import asyncio
import importlib
import io
import json
import os
import stat
import sys
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from charter import CredentialError

from charter_families import FAMILIES, _session, main, tools_for
from charter_families.apps import APPS, LOOPBACK_REDIRECT
from charter_families.connections import Connections
from charter_families.keychain import WINDOWS_ENTRY_LIMIT, FileStore, KeychainStore, open_store
from charter_families.signin import (
    ConnectTool,
    Loopback,
    SetupPrompt,
    StatusTool,
    google_scopes,
    login,
    status_text,
)


@pytest.fixture(autouse=True)
def _packs_left_as_found():
    """Connecting configures packs globally; put every one back."""
    saved = {}
    for name in ("linear", "stripe", "github", "slack", "notion", "firecrawl", "tavily", "granola"):
        module = importlib.import_module(f"charter.packs.{name}")
        for attr, field in (("_headers", "_api_key"), ("_credentials", "_provider")):
            holder = getattr(module, attr, None)
            if holder is not None and hasattr(holder, field):
                saved[(holder, field)] = getattr(holder, field)
    yield
    for (holder, field), value in saved.items():
        setattr(holder, field, value)


@pytest.fixture
def store(tmp_path):
    return FileStore(tmp_path / "credentials.json")


def _unconfigure(*packs):
    for name in packs:
        module = importlib.import_module(f"charter.packs.{name}")
        if hasattr(module, "_headers"):
            module._headers._api_key = None
        if hasattr(module, "_credentials"):
            module._credentials._provider = None


# -- the store ---------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="no POSIX modes; the profile's ACL protects it")
def test_the_file_store_is_readable_by_its_owner_alone(store):
    store.set("stripe", "{}")
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600
    assert store.get("stripe") == "{}"
    store.delete("stripe")
    assert store.get("stripe") is None


def test_the_file_can_be_forced_for_a_machine_with_no_keychain(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARTER_CREDENTIALS_FILE", str(tmp_path / "c.json"))
    assert isinstance(open_store(), FileStore)


def _backend(module, **methods):
    """A keyring backend as keyring's own module names it, without that OS to hand."""
    attrs = {k: staticmethod(v) if callable(v) else v for k, v in methods.items()}
    return type("Keyring", (), {"__module__": module, **attrs})()


def _keyring_module(backend):
    return type(
        "keyring",
        (),
        {
            "get_keyring": staticmethod(lambda: backend),
            "get_password": staticmethod(lambda s, n: backend.get_password(s, n)),
            "set_password": staticmethod(lambda s, n, v: backend.set_password(s, n, v)),
        },
    )


@pytest.mark.parametrize(
    "module, name",
    [
        # The class is `Keyring` on both, which printed "Stored in the Keyring keychain".
        ("keyring.backends.macOS", "the macOS Keychain"),
        ("keyring.backends.SecretService", "the Secret Service"),
        ("keyring.backends.Windows", "Windows Credential Manager"),
    ],
)
def test_the_keychain_is_named_the_way_its_users_know_it(module, name):
    assert KeychainStore(_keyring_module(_backend(module))).location == name


def test_a_chain_of_keychains_is_named_by_the_one_it_writes_to():
    # A Linux desktop with KWallet and the Secret Service both usable gets a chainer.
    chain = _backend(
        "keyring.backends.chainer",
        backends=[_backend("keyring.backends.SecretService"), _backend("keyring.backends.kwallet")],
    )
    assert KeychainStore(_keyring_module(chain)).location == "the Secret Service"


def _locked(*args):
    from keyring.errors import KeyringLocked

    raise KeyringLocked("Failed to unlock the collection!")


@pytest.mark.parametrize("why", ["locked", "null"])
def test_a_keychain_that_cannot_keep_anything_falls_back_to_the_file(
    why, tmp_path, monkeypatch, capsys
):
    import keyring
    from keyring.backends import null

    # Locked: a Secret Service over SSH, nobody at the screen to unlock it. Null:
    # keyring's backend that accepts every write and keeps none.
    backend = _backend("keyring.backends.SecretService", get_password=_locked)
    monkeypatch.setattr(
        keyring, "get_keyring", lambda: null.Keyring() if why == "null" else backend
    )
    monkeypatch.delenv("CHARTER_CREDENTIALS_FILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = open_store()
    assert isinstance(store, FileStore)
    assert store.path == tmp_path / "charter" / "credentials.json"
    assert str(store.path) in capsys.readouterr().err


@respx.mock
async def test_a_keychain_that_refuses_an_entry_is_reported_not_raised():
    _unconfigure("stripe")

    def refuse(*args):  # what pywin32 raises for an entry over Credential Manager's limit
        raise OSError(1783, "CredWrite", "The stub received bad data.")

    backend = _backend(
        "keyring.backends.Windows", get_password=lambda s, n: None, set_password=refuse
    )
    connections = Connections(["stripe"], store=KeychainStore(_keyring_module(backend)), environ={})
    respx.get("https://api.stripe.com/v1/balance").mock(return_value=httpx.Response(200, json={}))
    said = []
    code = await login(
        connections,
        ["stripe"],
        command="x",
        open_browser=lambda url: None,
        ask_secret=lambda prompt: "sk_good",
        say=said.append,
        interactive=True,
    )
    assert code == 1
    assert any(
        "Windows Credential Manager would not store it" in line
        and "CHARTER_CREDENTIALS_FILE" in line
        for line in said
    )


def test_status_prints_to_a_windows_pipe(tmp_path, monkeypatch):
    # Windows encodes a piped stdout as cp1252, which has no "→", and Granola's
    # instructions have one: `support status` raised in CI on windows-latest.
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setenv("CHARTER_CREDENTIALS_FILE", str(tmp_path / "c.json"))
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)
    assert main(["support", "status"]) == 0
    out.flush()
    assert "Settings → Connectors" in out.buffer.getvalue().decode("utf-8")


def test_every_family_s_google_grant_fits_one_windows_credential():
    # Credential Manager keeps 2,560 bytes of UTF-16 per entry. Google allows a
    # refresh token up to 512 bytes; the client ID and secret are the lengths
    # Google issues today. A family that asks for more scopes is what would break it.
    for name, family in FAMILIES.items():
        record = {
            "type": "google",
            "client_id": "0" * 12 + "-" + "x" * 32 + ".apps.googleusercontent.com",
            "client_secret": "GOCSPX-" + "x" * 28,
            "refresh_token": "1//" + "x" * 509,
            "scopes": google_scopes([t.pack for t in tools_for([family]) if t.pack]),
        }
        assert len(json.dumps(record)) <= WINDOWS_ENTRY_LIMIT, name


# -- connections -------------------------------------------------------------------


def test_the_environment_wins_over_the_store(store, monkeypatch):
    _unconfigure("stripe")
    import charter.packs.stripe as stripe

    stripe.configure("sk_from_env")
    store.set("stripe", json.dumps({"type": "key", "values": {"STRIPE_API_KEY": "sk_stored"}}))
    connections = Connections(["stripe"], store=store, environ={})
    assert connections.load() == []
    assert connections.state(APPS["stripe"]) == "set in the environment"
    assert stripe._headers._api_key == "sk_from_env"


@respx.mock
async def test_a_stored_key_reaches_the_wire(store):
    _unconfigure("stripe")
    store.set("stripe", json.dumps({"type": "key", "values": {"STRIPE_API_KEY": "sk_test_1"}}))
    connections = Connections(["stripe"], store=store, environ={})
    assert connections.load() == ["stripe"]
    route = respx.get("https://api.stripe.com/v1/balance").mock(
        return_value=httpx.Response(200, json={})
    )
    import charter.packs.stripe as stripe

    await stripe.balance_retrieve.ainvoke({})
    assert route.calls.last.request.headers["authorization"] == "Bearer sk_test_1"


@respx.mock
async def test_an_app_connected_mid_session_works_on_the_next_call_without_a_restart(store):
    _unconfigure("stripe")
    tools = [t for t in tools_for([FAMILIES["finance"]]) if t.pack == "stripe"]
    connections = Connections(["stripe"], store=store, environ={})
    session = _session(tools, connections, "uvx stripe-billing-ops-mcp")

    with pytest.raises(CredentialError, match="Stripe is not connected.*login stripe"):
        await session.dispatch("stripe_balance_retrieve", {})

    store.set("stripe", json.dumps({"type": "key", "values": {"STRIPE_API_KEY": "sk_test_2"}}))
    respx.get("https://api.stripe.com/v1/balance").mock(
        return_value=httpx.Response(200, json={"available": []})
    )
    assert await session.dispatch("stripe_balance_retrieve", {}) is not None


# -- signing in --------------------------------------------------------------------


@respx.mock
async def test_login_checks_a_key_before_storing_it(store):
    _unconfigure("stripe")
    connections = Connections(["stripe"], store=store, environ={})
    respx.get("https://api.stripe.com/v1/balance").mock(
        return_value=httpx.Response(401, json={"error": {}})
    )
    said = []
    code = await login(
        connections,
        ["stripe"],
        command="x",
        open_browser=lambda url: None,
        ask_secret=lambda prompt: "sk_bad",
        say=said.append,
        interactive=True,
    )
    assert code == 1 and store.get("stripe") is None
    assert any("did not accept" in line for line in said)

    respx.get("https://api.stripe.com/v1/balance").mock(return_value=httpx.Response(200, json={}))
    code = await login(
        connections,
        ["stripe"],
        command="x",
        open_browser=lambda url: None,
        ask_secret=lambda prompt: "sk_good",
        say=said.append,
        interactive=True,
    )
    assert code == 0
    assert json.loads(store.get("stripe"))["values"] == {"STRIPE_API_KEY": "sk_good"}


async def test_login_never_prompts_without_a_terminal(store):
    _unconfigure("stripe")
    connections = Connections(["stripe"], store=store, environ={})
    said = []
    code = await login(connections, ["stripe"], command="uvx x", say=said.append, interactive=False)
    assert code == 1
    assert any("run `uvx x login stripe` in a terminal" in line for line in said)


def test_no_app_signs_in_through_a_client_we_registered():
    """Every credential is the user's own: Google's sign-in is the only one, over their client."""
    assert [a.key for a in APPS.values() if a.sign_in is not None] == ["google"]
    assert {f.env for f in APPS["google"].fields} == {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"}


@pytest.fixture
def no_google_grant(monkeypatch):
    for name in ("GOOGLE_REFRESH_TOKEN", "GOOGLE_TOKEN_FILE", "GOOGLE_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@respx.mock
async def test_a_google_sign_in_completes_through_the_loopback(store, monkeypatch, no_google_grant):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "users-own-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "users-own-secret")
    respx.route(host="127.0.0.1").pass_through()
    token = respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "ya29", "refresh_token": "r1", "expires_in": 3599}
        )
    )
    connections = Connections(["gmail"], store=store, environ={})
    asked = []

    def browser(url):  # the user approves; Google redirects back to the loopback
        query = parse_qs(urlparse(url).query)
        asked.append(query)
        callback = f"{LOOPBACK_REDIRECT}?code=c0de&state={query['state'][0]}"
        asyncio.get_running_loop().create_task(_get(callback))

    tool = ConnectTool(connections, "uvx support-inbox-mcp", open_browser=browser)
    reply = await tool.call({"app": "google"})
    assert "Opened the Google sign-in" in reply
    # A Web application client gets Google's error page and no callback; say what to do.
    assert "redirect_uri_mismatch" in reply and LOOPBACK_REDIRECT in reply
    for _ in range(50):
        if connections.state(APPS["google"]) == "connected":
            break
        await asyncio.sleep(0.05)
    assert connections.state(APPS["google"]) == "connected"

    query = asked[0]
    assert query["client_id"] == ["users-own-client"]
    assert query["access_type"] == ["offline"] and query["code_challenge_method"] == ["S256"]
    form = parse_qs(token.calls.last.request.content.decode())
    assert form["client_secret"] == ["users-own-secret"] and form["code_verifier"]
    stored = json.loads(store.get("google"))
    assert stored["client_id"] == "users-own-client" and stored["refresh_token"] == "r1"


async def test_the_loopback_closes_with_the_browser_s_spare_connection_open():
    # Browsers open a spare connection beside the one the callback comes on and may
    # never send on it. Closing the listener waited for it, so the login hung after
    # the callback had been answered; a live Chrome sign-in turned this up.
    spare = []

    async def sign_in():
        async with Loopback(port=0) as loopback:
            port = loopback._server.sockets[0].getsockname()[1]
            spare.append(await asyncio.open_connection("127.0.0.1", port))
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /callback?code=c0de&state=s HTTP/1.1\r\nHost: x\r\n\r\n")
            return await loopback.wait(5)

    assert await asyncio.wait_for(sign_in(), 5) == {"code": "c0de", "state": "s"}
    assert await spare[0][0].read() == b""  # closed by the listener, not left to the process


async def test_google_asks_for_the_user_s_own_client_first(store, monkeypatch, no_google_grant):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    connections = Connections(["gmail"], store=store, environ={})
    reply = await ConnectTool(connections, "uvx x").call({"app": "google"})
    assert "own Google OAuth client" in reply and "uvx x login google" in reply


async def _get(url):
    async with httpx.AsyncClient() as client:
        await client.get(url)


async def test_connect_explains_a_key_and_never_asks_for_it(store):
    _unconfigure("stripe")
    connections = Connections(["stripe"], store=store, environ={})
    reply = await ConnectTool(connections, "uvx stripe-billing-ops-mcp").call({"app": "stripe"})
    assert "https://dashboard.stripe.com/apikeys" in reply
    assert "uvx stripe-billing-ops-mcp login stripe" in reply


@pytest.mark.parametrize("app", ["github", "linear", "slack"])
async def test_github_linear_and_slack_connect_with_the_user_s_own_key(store, monkeypatch, app):
    for field in APPS[app].fields:
        monkeypatch.delenv(field.env, raising=False)
    _unconfigure(app)
    connections = Connections([app], store=store, environ={})
    reply = await ConnectTool(connections, "uvx x").call({"app": app})
    assert "needs a key from" in reply and f"uvx x login {app}" in reply


def test_the_opening_status_says_how_to_connect_and_forbids_keys_in_chat(store):
    _unconfigure("stripe", "linear")
    connections = Connections(["stripe", "linear"], store=store, environ={})
    text = status_text(connections, "uvx x")
    assert "Stripe: needs a key from https://dashboard.stripe.com/apikeys" in text
    assert "Never ask the user to paste a key" in text


def test_the_setup_prompt_sends_keys_to_the_terminal():
    text = SetupPrompt("uvx support-inbox-mcp").render()
    assert "`connection_status`" in text
    assert "`uvx support-inbox-mcp login <app>`" in text
    assert "Do not ask me to paste a key" in text


async def test_the_server_carries_instructions_and_both_connection_tools(store):
    """`connection_status` is read-only and `connect` is not.

    `codex exec` refuses every tool not marked read-only, so while the status came
    from `connect` with no arguments, a Codex agent could not see it at all.
    """
    pytest.importorskip("mcp", reason="needs the [mcp] extra")
    _unconfigure("stripe")
    from charter.adapters.mcp import build_server

    connections = Connections(["stripe"], store=store, environ={})
    connect = ConnectTool(connections, "uvx x")
    server = build_server(
        [],
        name="t",
        instructions="status here",
        local_tools=[connect, StatusTool(connections, "uvx x", connect)],
        prompts=[SetupPrompt("uvx x")],
    )
    assert server.instructions == "status here"
    listed = {t.name: t for t in await server.list_tools()}
    assert listed["connection_status"].annotations.read_only_hint is True
    assert listed["connect"].annotations.read_only_hint is False
    assert listed["connect"].input_schema["required"] == ["app"]
    result = await server.call_tool("connection_status", {})
    assert "Stripe: needs a key from" in result.content[0].text
    assert [p.name for p in await server.list_prompts()] == ["setup"]


async def test_the_status_reports_a_sign_in_that_failed_in_the_background(store):
    connections = Connections(["stripe"], store=store, environ={})
    connect = ConnectTool(connections, "uvx x")
    connect.errors["google"] = "no answer from the browser"
    reply = await StatusTool(connections, "uvx x", connect).call({})
    assert "Last sign-in errors: google: no answer from the browser" in reply
