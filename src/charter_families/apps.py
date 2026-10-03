# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
The apps a family server connects, and how each one is connected.

An app is the unit a person connects: one credential, one or more packs. The six
Google packs are one app, because one grant covers them.

Every credential is the person's own, and the Charter project registers no app
with any of these services. GitHub, Linear, Slack, Stripe, Notion, Firecrawl,
Tavily, Granola and Shopify each issue a key or token from their own settings,
and that is the whole of their path.

Google issues no such key, so it signs in through a browser, over the person's
*own* OAuth client: ``GOOGLE_CLIENT_ID`` and ``GOOGLE_CLIENT_SECRET`` come from
them. A shared client would need Google's verification and, for Gmail and
Drive, a paid security assessment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Tuple

from charter.auth import OAuth2Server

__all__ = ["APPS", "App", "Field", "GOOGLE", "app_for_pack"]

DOCS = "https://docs.r28.ai/charter"

# As docs/auth/providers/google.mdx in Charter declares it. Without offline
# access and a forced consent, Google returns no refresh token.
GOOGLE = OAuth2Server(
    issuer="https://accounts.google.com",
    authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    authorization_params={"access_type": "offline", "prompt": "consent"},
)

# Where the browser comes back to. A Desktop app client accepts any port on
# 127.0.0.1; a fixed one lets a Web application client register it too.
LOOPBACK_PORT = 47613
LOOPBACK_REDIRECT = f"http://127.0.0.1:{LOOPBACK_PORT}/callback"


@dataclass(frozen=True)
class Field:
    """One value the key path asks for, and the variable it is known by."""

    env: str
    label: str
    secret: bool = True


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
    # The server a browser sign-in goes to, over the person's own OAuth client.
    # Only Google: everything else issues a key.
    sign_in: Optional[OAuth2Server] = None
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
            note="A bot token from your own Slack app, which the guide sets up in about three minutes.",
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
            sign_in=GOOGLE,
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
