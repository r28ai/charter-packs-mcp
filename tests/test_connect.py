"""Connecting apps: public-client OAuth, the keychain store, and the server that uses them."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from charter import CredentialError
from charter.auth import TokenGrant

from charter_families import FAMILIES, _session, tools_for
from charter_families.apps import APPS, LOOPBACK_REDIRECT
from charter_families.connections import Connections, grant_record
from charter_families.keychain import FileStore, open_store
from charter_families.oauth import DeviceFlow, PublicClient, RefreshingGrant
from charter_families.signin import ConnectTool, SetupPrompt, login, status_text

LINEAR = PublicClient(
    authorization_endpoint="https://linear.app/oauth/authorize",
    token_endpoint="https://api.linear.app/oauth/token",
    client_id="lin-client",
    scope_separator=",",
)
SLACK = PublicClient(
    authorization_endpoint="https://slack.com/oauth/v2/authorize",
    token_endpoint="https://slack.com/api/oauth.v2.access",
    client_id="slack-client",
    scope_param="user_scope",
    scope_separator=",",
    response_root="authed_user",
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


# -- the protocol ------------------------------------------------------------------


def test_the_authorization_url_carries_pkce_and_the_server_s_own_scope_spelling():
    request = SLACK.authorize(["chat:write", "users:read"], LOOPBACK_REDIRECT)
    query = parse_qs(urlparse(request.url).query)
    assert query["user_scope"] == ["chat:write,users:read"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [LOOPBACK_REDIRECT]
    assert query["state"] == [request.state]
    assert request.code_verifier and query["code_challenge"][0] != request.code_verifier


@respx.mock
async def test_a_public_client_exchanges_without_a_secret_and_reads_slack_s_shape():
    route = respx.post("https://slack.com/api/oauth.v2.access").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "authed_user": {"access_token": "xoxp-1", "scope": "chat:write,users:read"},
            },
        )
    )
    grant = await SLACK.exchange("c0de", code_verifier="v", redirect_uri=LOOPBACK_REDIRECT)
    form = parse_qs(route.calls.last.request.content.decode())
    assert "client_secret" not in form
    assert form["code_verifier"] == ["v"] and form["client_id"] == ["slack-client"]
    assert grant.access_token == "xoxp-1"
    assert grant.scopes == ["chat:write", "users:read"]


@respx.mock
async def test_a_200_that_says_ok_false_is_a_refusal():
    respx.post("https://slack.com/api/oauth.v2.access").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "invalid_code"})
    )
    with pytest.raises(CredentialError, match="invalid_code"):
        await SLACK.exchange("c0de", code_verifier="v", redirect_uri=LOOPBACK_REDIRECT)


@respx.mock
async def test_a_rotating_refresh_keeps_the_new_token_and_a_plain_one_keeps_the_old():
    old = TokenGrant(access_token="a1", refresh_token="r1")
    route = respx.post("https://api.linear.app/oauth/token")
    route.mock(
        return_value=httpx.Response(
            200, json={"access_token": "a2", "refresh_token": "r2", "expires_in": 86400}
        )
    )
    assert (await LINEAR.refresh(old)).refresh_token == "r2"
    route.mock(return_value=httpx.Response(200, json={"access_token": "a3", "expires_in": 86400}))
    assert (await LINEAR.refresh(old)).refresh_token == "r1"


@respx.mock
async def test_a_refreshing_grant_renews_once_for_concurrent_calls_and_hands_the_grant_on():
    route = respx.post("https://api.linear.app/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "new", "refresh_token": "r2", "expires_in": 86400}
        )
    )
    stored = []
    expired = TokenGrant(
        access_token="old",
        refresh_token="r1",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    grant = RefreshingGrant(LINEAR, expired, on_refresh=stored.append)
    tokens = await asyncio.gather(*(grant.get_credentials("linear") for _ in range(5)))
    assert {t.token for t in tokens} == {"new"}
    assert route.call_count == 1
    assert [g.refresh_token for g in stored] == ["r2"]


@respx.mock
async def test_the_device_flow_waits_out_pending_and_slow_down():
    respx.post("https://github.com/login/device/code").mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "d",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "interval": 5,
            },
        )
    )
    respx.post("https://github.com/login/oauth/access_token").mock(
        side_effect=[
            httpx.Response(200, json={"error": "authorization_pending"}),
            httpx.Response(200, json={"error": "slow_down", "interval": 10}),
            httpx.Response(200, json={"access_token": "gho_x", "scope": "repo,read:user"}),
        ]
    )
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    flow = DeviceFlow(
        "https://github.com/login/device/code",
        "https://github.com/login/oauth/access_token",
        "gh-client",
    )
    code = await flow.start(["repo"])
    assert code.user_code == "ABCD-1234"
    grant = await flow.poll(code, sleep=sleep)
    assert grant.access_token == "gho_x"
    assert waits == [5, 5, 10]


# -- the store ---------------------------------------------------------------------


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
async def test_a_linear_sign_in_is_sent_as_bearer_and_renewed_before_it_lapses(store):
    _unconfigure("linear")
    soon = datetime.now(timezone.utc) + timedelta(seconds=30)
    record = grant_record(
        "lin-client", TokenGrant(access_token="old", refresh_token="r1", expires_at=soon)
    )
    store.set("linear", json.dumps(record))
    connections = Connections(["linear"], store=store, environ={})
    connections.load()
    respx.post("https://api.linear.app/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "new", "refresh_token": "r2", "expires_in": 86400}
        )
    )
    api = respx.post("https://api.linear.app/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"viewer": {"id": "u1"}}})
    )
    import charter.packs.linear as linear

    await connections.before_call("linear")
    await linear.viewer.ainvoke({})
    assert api.calls.last.request.headers["authorization"] == "Bearer new"
    assert json.loads(store.get("linear"))["refresh_token"] == "r2"  # the rotated one, written back


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


@respx.mock
async def test_a_browser_sign_in_completes_through_the_loopback(store, monkeypatch):
    _unconfigure("linear")
    monkeypatch.setenv("LINEAR_CLIENT_ID", "lin-client")
    respx.route(host="127.0.0.1").pass_through()
    respx.post("https://api.linear.app/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "lin_oauth", "refresh_token": "r1", "expires_in": 86400}
        )
    )
    respx.post("https://api.linear.app/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"viewer": {"id": "u1"}}})
    )
    connections = Connections(["linear"], store=store, environ={})

    def browser(url):  # the user approves; Linear redirects back to the loopback
        query = parse_qs(urlparse(url).query)
        callback = f"{LOOPBACK_REDIRECT}?code=c0de&state={query['state'][0]}"
        asyncio.get_running_loop().create_task(_get(callback))

    tool = ConnectTool(connections, "uvx github-linear-mcp", open_browser=browser)
    reply = await tool.call({"app": "linear"})
    assert "Opened the Linear sign-in" in reply
    for _ in range(50):
        if connections.state(APPS["linear"]) == "connected":
            break
        await asyncio.sleep(0.05)
    assert connections.state(APPS["linear"]) == "connected"
    assert json.loads(store.get("linear"))["access_token"] == "lin_oauth"


async def _get(url):
    async with httpx.AsyncClient() as client:
        await client.get(url)


async def test_connect_explains_a_key_and_never_asks_for_it(store):
    _unconfigure("stripe")
    connections = Connections(["stripe"], store=store, environ={})
    reply = await ConnectTool(connections, "uvx stripe-billing-ops-mcp").call({"app": "stripe"})
    assert "https://dashboard.stripe.com/apikeys" in reply
    assert "uvx stripe-billing-ops-mcp login stripe" in reply


async def test_connect_offers_no_sign_in_until_a_client_id_is_registered(store, monkeypatch):
    monkeypatch.delenv("LINEAR_CLIENT_ID", raising=False)
    connections = Connections(["linear"], store=store, environ={})
    reply = await ConnectTool(connections, "uvx x").call({"app": "linear"})
    assert "needs a key" in reply


def test_the_opening_status_says_how_to_connect_and_forbids_keys_in_chat(store):
    _unconfigure("stripe", "linear")
    connections = Connections(["stripe", "linear"], store=store, environ={})
    text = status_text(connections, "uvx x")
    assert "Stripe: needs a key from https://dashboard.stripe.com/apikeys" in text
    assert "Never ask the user to paste a key" in text


def test_the_setup_prompt_sends_keys_to_the_terminal():
    text = SetupPrompt("uvx support-inbox-mcp").render()
    assert "`uvx support-inbox-mcp login <app>`" in text
    assert "Do not ask me to paste a key" in text


async def test_the_server_carries_instructions_and_the_connect_tool(store):
    pytest.importorskip("mcp", reason="needs the [mcp] extra")
    _unconfigure("stripe")
    from charter.adapters.mcp import build_server

    connections = Connections(["stripe"], store=store, environ={})
    tool = ConnectTool(connections, "uvx x")
    server = build_server(
        [], name="t", instructions="status here", local_tools=[tool], prompts=[SetupPrompt("uvx x")]
    )
    assert server.instructions == "status here"
    listed = {t.name: t for t in await server.list_tools()}
    assert listed["connect"].annotations.read_only_hint is False
    result = await server.call_tool("connect", {})
    assert "Stripe" in result.content[0].text
    assert [p.name for p in await server.list_prompts()] == ["setup"]
