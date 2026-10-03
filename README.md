# charter-families

Cross-app agent workflows over [Charter](https://github.com/r28ai/charter)'s packs, served as MCP servers.

A Charter pack is one API's tools. A family is the tools one kind of work calls across APIs:
engineering is GitHub, Linear and Slack together, a support inbox is Gmail, Stripe and Linear.
Each family carries the workflows that justify its tools, and its server offers those
workflows as prompts (slash commands in Claude Code) beside exactly the tools they name.

Nothing here is part of the Charter SDK. This package is built on it: every tool is a pack
tool, and the server is Charter's MCP adapter.

```bash
python -m charter_families engineering                 # serve one family over stdio
python -m charter_families support,finance             # two families, one server
python -m charter_families engineering login           # connect the apps it uses
python -m charter_families engineering status          # what is connected
```

| Family | Workflows | Published as |
|---|---:|---|
| engineering | 25 | `github-linear-mcp` |
| product | 20 | `product-manager-mcp` |
| sales | 14 | `sales-prep-mcp` |
| marketing | 13 | `marketing-ops-mcp` |
| support | 12 | `support-inbox-mcp` |
| finance | 14 | `stripe-billing-ops-mcp` |
| commerce | 12 | `shopify-ops-mcp` |
| ops | 20 | `chief-of-staff-mcp` |
| research | 10 | `web-research-to-docs-mcp` |
| people | 8 | `recruiting-ops-mcp` |
| agency | 8 | `freelancer-ops-mcp` |

## Connecting apps

Each server tells the agent at startup which apps are connected and how to connect the rest.
Every credential is the user's own: nothing here is registered with any service, and there is
no server of ours in the path.

- **Keys** (GitHub, Linear, Slack, Stripe, Notion, Firecrawl, Tavily, Granola, Shopify) come
  from the client's config, or from `login`, which asks for them at a hidden prompt.
- **Google** signs in through the user's own OAuth client, with PKCE and a loopback redirect,
  because a shared one would need Google's verification, and for Gmail and Drive a paid
  security assessment.

Whatever `login` or the `connect` tool stores goes to the OS keychain, after one read-only
call to the app's own API confirms it works. A variable set in the client's config always
wins over the keychain.

## Layout

```
src/charter_families/
  catalogue.py    the 156 workflows: title, tools in order, why, cadence
  __init__.py     families, the MCP entry point, login / status / logout
  apps.py         each app: its key, the call that checks it, Google's sign-in server
  connections.py  where each app's credential came from, handed to the packs
  signin.py       `login`, Google's sign-in, the `connect` tool, the `setup` prompt
  keychain.py     the OS keychain, or an owner-only file without one
scripts/generate.py   writes ../charter-mcp-families: one publishable package per family
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
uv run pyright
uv run python scripts/generate.py
```

Every test runs offline against `respx`. Until Charter 0.3.0 is on PyPI, `uv sync` builds
against the Charter checkout beside this one (`../charter`).

## License

Apache 2.0. See [LICENSE](LICENSE).
