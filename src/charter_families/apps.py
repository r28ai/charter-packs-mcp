# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
The apps a family server connects, and the best way each one offers.

An app is the unit a person connects: one credential, one or more packs. The six
Google packs are one app, because one grant covers them.

Each app has a key path — the variables its packs already read, and the page
that issues the value — and, where the API allows it, a sign-in that needs
nothing but a click:

- **Linear and Slack**: authorization code with PKCE and a loopback redirect, as a
  public client. Slack's tokens this way are the user's own: a public client may
  not request a bot's scopes, so the agent acts as the person who signed in.
- **GitHub**: the device flow, which is what ``gh auth login`` does.
- **Google**: the same loopback flow over the person's *own* OAuth client. A
  shared one would need Google's verification and, for Gmail and Drive, a paid
  security assessment, so ``GOOGLE_CLIENT_ID`` and ``GOOGLE_CLIENT_SECRET`` come
  from them.

The rest — Stripe, Notion, Firecrawl, Tavily, Granola, Shopify — issue keys and
no OAuth a third party can use, so a key is the whole of their path.

The Charter project's public client IDs are below. A public client has no secret, which is
what makes printing them here safe (RFC 8252). An empty one means the app is
not registered yet, and the sign-in falls back to the key path. Each can be
overridden with its ``*_CLIENT_ID`` variable, for an organisation that only
allows apps it registered itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Mapping, Optional, Tuple

__all__ = ["APPS", "App", "Field", "SignIn", "CLIENT_IDS", "app_for_pack"]

DOCS = "https://docs.r28.ai/charter"

# Registered by the Charter project. Empty until registered: the sign-in is then not offered.
CLIENT_IDS: Dict[str, str] = {
    "github": "",
    "linear": "",
    "slack": "",
}

# The fixed loopback address registered as each public client's redirect.
LOOPBACK_PORT = 47613
LOOPBACK_REDIRECT = f"http://127.0.0.1:{LOOPBACK_PORT}/callback"


@dataclass(frozen=True)
class Field:
    """One value the key path asks for, and the variable it is known by."""

    env: str
    label: str
    secret: bool = True


@dataclass(frozen=True)
class SignIn:
    """How an app signs in from a browser, when it can."""

    kind: Literal["loopback", "device", "google"]
    token_endpoint: str
    scopes: Tuple[str, ...] = ()
    authorization_endpoint: str = ""
    device_endpoint: str = ""
    client_id_env: str = ""
    scope_param: str = "scope"
    scope_separator: str = " "
    response_root: Optional[str] = None
    authorization_params: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class App:
    key: str
    name: str
    packs: Tuple[str, ...]
    fields: Tuple[Field, ...]
    key_url: str
    guide: str
    # How a stored value reaches the packs: a pack's `configure(api_key)`, its
    # `configure(credential_provider)`, or the environment variables it reads
    # on every call.
    install: Literal["api_key", "provider", "env"]
    check: Optional[Tuple[str, Dict[str, object]]] = None
    sign_in: Optional[SignIn] = None
    note: str = ""


APPS: Dict[str, App] = {
    app.key: app
    for app in (
        App(
            "github",
            "GitHub",
            ("github",),
            (Field("GITHUB_TOKEN", "Personal access token"),),
            "https://github.com/settings/tokens/new?description=Charter&scopes=repo,read:user",
            f"{DOCS}/auth/setup/github",
            install="provider",
            check=("github.users_get_authenticated", {}),
            sign_in=SignIn(
                "device",
                token_endpoint="https://github.com/login/oauth/access_token",
                device_endpoint="https://github.com/login/device/code",
                client_id_env="GITHUB_CLIENT_ID",
                scopes=("repo", "read:user"),
            ),
        ),
        App(
            "linear",
            "Linear",
            ("linear",),
            (Field("LINEAR_API_KEY", "Personal API key"),),
            "https://linear.app/settings/account/security",
            f"{DOCS}/packs/linear",
            install="api_key",
            check=("linear.viewer", {}),
            sign_in=SignIn(
                "loopback",
                authorization_endpoint="https://linear.app/oauth/authorize",
                token_endpoint="https://api.linear.app/oauth/token",
                client_id_env="LINEAR_CLIENT_ID",
                scopes=("read", "write"),
                scope_separator=",",
            ),
        ),
        App(
            "slack",
            "Slack",
            ("slack",),
            (Field("SLACK_BOT_TOKEN", "Bot token (xoxb-…)"),),
            f"{DOCS}/auth/setup/slack",
            f"{DOCS}/auth/setup/slack",
            install="provider",
            check=("slack.users_list", {"limit": 1}),
            sign_in=SignIn(
                "loopback",
                authorization_endpoint="https://slack.com/oauth/v2/authorize",
                token_endpoint="https://slack.com/api/oauth.v2.access",
                client_id_env="SLACK_CLIENT_ID",
                # User scopes: a public client may not ask for a bot's.
                scopes=(
                    "channels:history",
                    "channels:read",
                    "channels:write",
                    "chat:write",
                    "groups:history",
                    "groups:read",
                    "groups:write",
                    "im:history",
                    "im:read",
                    "im:write",
                    "mpim:history",
                    "mpim:read",
                    "mpim:write",
                    "reactions:read",
                    "reactions:write",
                    "search:read",
                    "users:read",
                ),
                scope_param="user_scope",
                scope_separator=",",
                response_root="authed_user",
            ),
            note="Signing in acts as you; a bot token from the setup guide posts as itself.",
        ),
        App(
            "google",
            "Google",
            ("gmail", "gcalendar", "gsheets", "gdocs", "gdrive", "gforms"),
            (
                Field("GOOGLE_CLIENT_ID", "OAuth client ID", secret=False),
                Field("GOOGLE_CLIENT_SECRET", "OAuth client secret"),
            ),
            "https://console.cloud.google.com/auth/clients",
            f"{DOCS}/auth/setup/google",
            install="env",
            sign_in=SignIn(
                "google",
                authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
                token_endpoint="https://oauth2.googleapis.com/token",
                authorization_params={"access_type": "offline", "prompt": "consent"},
            ),
        ),
        App(
            "notion",
            "Notion",
            ("notion",),
            (Field("NOTION_API_KEY", "Integration secret (ntn_…)"),),
            "https://www.notion.so/profile/integrations",
            f"{DOCS}/auth/setup/notion",
            install="provider",
            check=("notion.users_retrieve_me", {}),
            note="Then share the pages it should see with the integration.",
        ),
        App(
            "stripe",
            "Stripe",
            ("stripe",),
            (Field("STRIPE_API_KEY", "Secret or restricted key"),),
            "https://dashboard.stripe.com/apikeys",
            f"{DOCS}/packs/stripe",
            install="api_key",
            check=("stripe.balance_retrieve", {}),
        ),
        App(
            "shopify",
            "Shopify",
            ("shopify",),
            (
                Field("SHOPIFY_SHOP", "Store domain (your-store.myshopify.com)", secret=False),
                Field("SHOPIFY_CLIENT_ID", "App client ID", secret=False),
                Field("SHOPIFY_CLIENT_SECRET", "App client secret"),
            ),
            "https://dev.shopify.com/dashboard",
            f"{DOCS}/packs/shopify#getting-the-client-id-and-secret",
            install="env",
            check=("shopify.shop_get", {}),
        ),
        App(
            "firecrawl",
            "Firecrawl",
            ("firecrawl",),
            (Field("FIRECRAWL_API_KEY", "API key"),),
            "https://www.firecrawl.dev/app/api-keys",
            f"{DOCS}/packs/firecrawl",
            install="api_key",
            check=("firecrawl.credit_usage", {}),
        ),
        App(
            "tavily",
            "Tavily",
            ("tavily",),
            (Field("TAVILY_API_KEY", "API key"),),
            "https://app.tavily.com/home",
            f"{DOCS}/packs/tavily",
            install="api_key",
            check=("tavily.usage", {}),
        ),
        App(
            "granola",
            "Granola",
            ("granola",),
            (Field("GRANOLA_API_KEY", "API key"),),
            "https://docs.granola.ai/help-center/sharing/integrations/granola-api",
            f"{DOCS}/packs/granola",
            install="api_key",
            check=("granola.folders_list", {}),
            note="In the Granola app: Settings → Connectors → API keys. Business plan or above.",
        ),
    )
}


def app_for_pack(pack: str) -> App:
    for app in APPS.values():
        if pack in app.packs:
            return app
    raise KeyError(pack)


def client_id(app: App, environ: Mapping[str, str]) -> str:
    """The public client ID to sign in with: the override if set, Charter's own if registered."""
    if app.sign_in is None:
        return ""
    if app.sign_in.kind == "google":
        return environ.get("GOOGLE_CLIENT_ID", "")
    return environ.get(app.sign_in.client_id_env, "") or CLIENT_IDS.get(app.key, "")
