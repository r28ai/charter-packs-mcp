# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Write one publishable directory per family: a thin package, its README and its server.json.

Each family ships as its own small package, so it has its own name on PyPI, its
own repository and its own listing in an MCP directory. That is distribution:
a directory is searched by the job and the apps, and "GitHub + Linear" finds a
reader that "Charter" does not. The package itself is a dozen lines that run
``charter_families`` with one family name, so the tools, the prompts and their
tests all stay in this repository.

Usage::

    uv run python scripts/generate.py                 # ../charter-mcp-families
    uv run python scripts/generate.py --out /some/dir

Nothing is published. Each directory is ready for ``git init``, ``uv build``,
``uv publish`` and ``mcp-publisher publish`` once ``charter-families`` is on PyPI.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from charter import schema_tokens

from charter_families import FAMILIES, Family
from charter_families.apps import APPS, App, Field, app_for_pack
from charter_families.signin import SetupPrompt

ROOT = Path(__file__).resolve().parent.parent

# Each family package depends on the engine, and the engine on Charter. Capped
# at the next minor because pre-1.0 a minor may break the API, and a family
# package should not be the thing that finds out.
FAMILIES_REQUIREMENT = "charter-families>=0.1.0,<0.2"
VERSION = "0.1.0"
GITHUB_ORG = "r28ai"
SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
DOCS = "https://docs.r28.ai/charter"


@dataclass(frozen=True)
class Listing:
    package: str  # the PyPI name, the repository name and the command
    key: str  # the key a client config names the server under
    title: str
    tagline: str  # server.json's description, so short


LISTINGS: Dict[str, Listing] = {
    "engineering": Listing(
        "github-linear-mcp",
        "dev",
        "GitHub + Linear Dev Workflows",
        "CI failures, PRs and security alerts become Linear issues and Slack posts, evidence attached.",
    ),
    "product": Listing(
        "product-manager-mcp",
        "pm",
        "Product Manager Workflows",
        "Calls, specs and feedback become deduped Linear issues, PRDs and weekly project updates.",
    ),
    "sales": Listing(
        "sales-prep-mcp",
        "sales",
        "Sales Prep and Follow-up",
        "Pre-call briefs, follow-up emails, enriched lead sheets and payment links, from your calendar.",
    ),
    "marketing": Listing(
        "marketing-ops-mcp",
        "marketing",
        "Marketing Ops",
        "Shipped work becomes blog drafts; competitor pricing, mentions and webinars run on schedule.",
    ),
    "support": Listing(
        "support-inbox-mcp",
        "support",
        "Support Inbox to Linear",
        "Support email becomes Linear bugs, refunds get handled, and fixed bugs get a reply in-thread.",
    ),
    "finance": Listing(
        "stripe-billing-ops-mcp",
        "billing",
        "Stripe Billing Ops",
        "Invoices from real work, failed-payment follow-ups, revenue sheets and dispute evidence.",
    ),
    "commerce": Listing(
        "shopify-ops-mcp",
        "shop",
        "Shopify Store Ops",
        "Low-stock reorders, where-is-my-order replies, daily sales digests and catalogue imports.",
    ),
    "ops": Listing(
        "chief-of-staff-mcp",
        "cos",
        "Chief of Staff",
        "Morning brief, meeting prep, action items to owners and the weekly update, from your tools.",
    ),
    "research": Listing(
        "web-research-to-docs-mcp",
        "research",
        "Web Research to Docs",
        "Competitor watch, cited research reports, paper alerts and market maps, filed where you read.",
    ),
    "people": Listing(
        "recruiting-ops-mcp",
        "hiring",
        "Recruiting and Onboarding",
        "Applications to a candidate sheet, interview scheduling, debriefs and a new hire's day one.",
    ),
    "agency": Listing(
        "freelancer-ops-mcp",
        "freelance",
        "Freelancer and Agency Ops",
        "Client onboarding, invoices from calendar and commits, status reports and overdue chasers.",
    ),
}

APP_NAMES = {
    "gmail": "Gmail",
    "gcalendar": "Google Calendar",
    "gsheets": "Google Sheets",
    "gdocs": "Google Docs",
    "gdrive": "Google Drive",
    "gforms": "Google Forms",
    "slack": "Slack",
    "github": "GitHub",
    "stripe": "Stripe",
    "linear": "Linear",
    "shopify": "Shopify",
    "firecrawl": "Firecrawl",
    "notion": "Notion",
    "granola": "Granola",
    "tavily": "Tavily",
}

GOOGLE = APPS["google"].packs

# What a person would pass as `details` to each family's first workflow, for the README.
EXAMPLE_DETAILS = {
    "engineering": "repo acme/api, Linear team ENG, post in #eng-alerts",
    "product": "this week's customer calls, Linear team PROD",
    "sales": "tomorrow's calls only, skip internal ones",
    "marketing": "everything shipped since the 1st",
    "support": "the support@ inbox, Linear team SUP",
    "finance": "client Acme, repo acme/site, last week",
    "commerce": "anything under 10 units, supplier sheet 'POs'",
    "ops": "post it to #me",
    "research": "competitors acme.com and globex.com",
    "people": "the jobs@ inbox, sheet 'Candidates 2026'",
    "agency": "new client Acme Ltd, $2,000 deposit",
}


def family_apps(family: Family) -> List[App]:
    """The apps a family connects, in the order its workflows first reach them."""
    out: List[App] = []
    for pack in family.packs:
        app = app_for_pack(pack)
        if app not in out:
            out.append(app)
    return out


def how_it_connects(app: App) -> str:
    if app.sign_in is None:
        return f"Your own key ([get one]({app.key_url})), entered once"
    return f"Browser sign-in, over your own OAuth client ([make one]({app.guide}))"


def module_name(listing: Listing) -> str:
    return listing.package.replace("-", "_")


def apps_phrase(family: Family) -> str:
    names = [APP_NAMES[p] for p in family.packs]
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]


def runs_without_google(family: Family) -> int:
    return sum(
        1 for w in family.workflows if not any(a in GOOGLE or a == "granola" for a in w.apps)
    )


def check(family: Family, listing: Listing) -> None:
    """The constraints a listing has to meet before it can be published."""
    assert len(listing.tagline) <= 100, f"{listing.package}: tagline over 100 characters"
    # A host composes `mcp__<key>__<pack>_<tool>` and a function name stops at 64.
    for step in family.steps:
        composed = f"mcp__{listing.key}__{step.replace('.', '_', 1)}"
        assert len(composed) <= 64, f"{listing.package}: {composed} is {len(composed)} characters"


def key_fields(family: Family) -> List[Tuple[App, Field]]:
    """The values a client's own settings can hold — every app's key path."""
    return [(app, field) for app in family_apps(family) for field in app.fields]


def _input_id(field: Field) -> str:
    return field.env.lower().replace("_", "-")


def readme(family: Family, listing: Listing) -> str:
    key, pkg = listing.key, listing.package
    tools = family.tools()
    tokens = sum(schema_tokens(t) for t in tools)
    apps = family_apps(family)
    secret_fields = [(a, f) for a, f in key_fields(family) if f.secret]
    plain_fields = [(a, f) for a, f in key_fields(family) if not f.secret]

    out: List[str] = [
        f"<!-- mcp-name: io.github.{GITHUB_ORG}/{pkg} -->",
        f"# {listing.title}",
        "",
        listing.tagline,
        "",
        f"An MCP server with **{len(family.workflows)} workflows** across {apps_phrase(family)}. "
        "Each workflow is a prompt your agent runs as a slash command, over the "
        f"{len(tools)} tools it needs and no others.",
        "",
        "```bash",
        f"claude mcp add {key} -- uvx {pkg}",
        "```",
        "",
        f"Then ask your agent to **connect your apps**, or run `/mcp__{key}__setup`.",
        "",
        "## Connect your apps",
        "",
        'Ask the agent to connect one ("connect Linear"). It tells you where to get that '
        "app's key and the command that stores it, and the next call works, with no restart. "
        "The agent never asks for a key in the chat.",
        "",
        "Or connect everything this server uses from a terminal:",
        "",
        "```bash",
        f"uvx {pkg} login            # each app in turn",
        f"uvx {pkg} login stripe     # just one",
        f"uvx {pkg} status           # what is connected",
        "```",
        "",
        "Tokens and keys go to your operating system's keychain (macOS Keychain, Windows "
        "Credential Manager, the Secret Service on Linux), and are checked with one read-only "
        "call to the app's own API before they are kept. Every key, token and OAuth client "
        "is yours: we register no app with any of these services, and nothing passes "
        "through a server of ours, because there isn't one.",
        "",
        "| App | How it connects | Or set |",
        "|---|---|---|",
    ]
    for app in apps:
        variables = ", ".join(f"`{f.env}`" for f in app.fields)
        note = f" {app.note}" if app.note else ""
        out.append(f"| {app.name} | {how_it_connects(app)}.{note} | {variables} |")

    out += [
        "",
        "A variable set in your client's config always wins over the keychain.",
        "",
        "## Workflows",
        "",
        "| Workflow | What you get | Apps |",
        "|---|---|---|",
    ]
    for w in family.workflows:
        names = ", ".join(APP_NAMES[a] for a in w.apps)
        out.append(f"| **{w.title}** <br>`{w.name}` | {w.why} | {names} |")

    vscode = {
        "inputs": [
            {
                "type": "promptString",
                "id": _input_id(f),
                "description": f"{a.name}: {f.label}",
                "password": True,
            }
            for a, f in secret_fields
        ],
        "servers": {
            key: {
                "type": "stdio",
                "command": "uvx",
                "args": [pkg],
                "env": {f.env: "${input:" + _input_id(f) + "}" for _, f in secret_fields}
                | {f.env: "" for _, f in plain_fields},
            }
        },
    }
    out += [
        "",
        "Every prompt takes one optional argument, `details`: the repo, team, channel, "
        "customer or date range you mean, so the agent does not have to ask. In Claude "
        "Code, put it in quotes, or only its first word arrives:",
        "",
        "```",
        f'/mcp__{key}__{family.workflows[0].name} "{EXAMPLE_DETAILS[family.key]}"',
        "```",
        "",
        "Reads run without asking. Before anything that creates, sends, changes or "
        "deletes, the prompt tells the agent to show you the call and wait.",
        "",
        f"{runs_without_google(family)} of the {len(family.workflows)} workflows need no "
        "Google or Granola credential.",
        "",
        "## Other clients",
        "",
        "**Claude Desktop**: install the `.mcpb` from the "
        f"[latest release](https://github.com/{GITHUB_ORG}/{pkg}/releases/latest). Claude "
        "asks for any keys in its own settings and keeps them in your keychain.",
        "",
        "**VS Code** (`.vscode/mcp.json`): VS Code asks for each key the first time the "
        "server starts and stores it securely. Leave out any you stored with `login`.",
        "",
        "```json",
        json.dumps(vscode, indent=2),
        "```",
        "",
        "**Cursor** (`.cursor/mcp.json`) and **Codex** (`~/.codex/config.toml`) start it the "
        "same way:",
        "",
        "```json",
        json.dumps({"mcpServers": {key: {"command": "uvx", "args": [pkg]}}}, indent=2),
        "```",
        "",
        "```toml",
        f"[mcp_servers.{key}]",
        'command = "uvx"',
        f'args = ["{pkg}"]',
        "```",
        "",
        f"Name the server `{key}`. A host builds each tool's name from that key, and "
        "a longer one can push a tool past the 64 characters a function name allows.",
        "",
        "## Built with Charter",
        "",
        f"Every tool here is a [Charter](https://github.com/{GITHUB_ORG}/charter) "
        "declaration: a Pydantic schema saying where each field goes on the wire. "
        "Charter's runtime builds the request, attaches and refreshes the credential, "
        "and trims the response before the model reads it. It runs in your process, "
        "with no proxy and no telemetry.",
        "",
        f"The {len(tools)} tool schemas come to {tokens:,} tokens.",
        "",
        "The same tools work in your own agent, without MCP:",
        "",
        "```python",
        "from charter.adapters.openai import to_openai_tools",
        "from charter_families import FAMILIES",
        "",
        f'tools = FAMILIES["{family.key}"].tools()',
        "definitions = to_openai_tools(tools)   # or charter.adapters.langchain",
        "```",
        "",
        f"Need an API that isn't here? [Write a pack]({DOCS}/start/coding-agents): "
        "your coding agent writes the declarations, and Charter's conformance suite "
        "checks them.",
        "",
        "<details>",
        f"<summary>All {len(tools)} tools</summary>",
        "",
    ]
    for pack in family.packs:
        names = [s.split(".", 1)[1] for s in family.steps if s.split(".", 1)[0] == pack]
        out.append(f"- **{APP_NAMES[pack]}**: " + ", ".join(f"`{pack}_{n}`" for n in names))
    out += ["", "</details>", "", "## License", "", "Apache 2.0.", ""]
    return "\n".join(out)


def manifest(family: Family, listing: Listing) -> str:
    """The MCPB manifest: Claude Desktop installs the bundle and asks for keys in its own UI."""
    fields = key_fields(family)
    user_config = {
        _input_id(f).replace("-", "_"): {
            "type": "string",
            "title": f"{a.name}: {f.label}",
            "description": (
                f"Optional. Your own OAuth client, made at {a.key_url}; with it set, ask "
                f"Claude to connect {a.name}."
                if a.sign_in
                else f"Optional. Get it at {a.key_url}"
            ),
            "sensitive": f.secret,
            "required": False,
        }
        for a, f in fields
    }
    doc = {
        "manifest_version": "0.4",
        "name": listing.package,
        "display_name": listing.title,
        "version": VERSION,
        "description": listing.tagline,
        "author": {"name": "R28 AI, Inc.", "url": "https://r28.ai"},
        "repository": {"type": "git", "url": f"https://github.com/{GITHUB_ORG}/{listing.package}"},
        "homepage": f"https://github.com/{GITHUB_ORG}/{listing.package}",
        "license": "Apache-2.0",
        "keywords": ["charter", *(APP_NAMES[p].lower() for p in family.packs)],
        "server": {
            "type": "uv",
            "entry_point": "src/server.py",
            "mcp_config": {
                "command": "uv",
                "args": ["run", "--directory", "${__dirname}", "src/server.py"],
                "env": {
                    f.env: "${user_config." + _input_id(f).replace("-", "_") + "}"
                    for _, f in fields
                },
            },
        },
        # The server offers these itself; the manifest lists them for the directory.
        "prompts": [
            {
                "name": "setup",
                "description": "Connect the apps this server uses.",
                "text": SetupPrompt(f"uvx {listing.package}").render(),
            }
        ]
        + [{"name": w.name, "description": w.why, "text": w.render()} for w in family.workflows],
        "user_config": user_config,
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def server_py(listing: Listing) -> str:
    return "\n".join(
        [
            "# SPDX-FileCopyrightText: 2026 R28 AI, Inc.",
            "# SPDX-License-Identifier: Apache-2.0",
            "",
            '"""Entry point for the Claude Desktop bundle (MCPB, server type `uv`)."""',
            "",
            f"from {module_name(listing)} import main",
            "",
            "raise SystemExit(main())",
            "",
        ]
    )


def pyproject(family: Family, listing: Listing) -> str:
    keywords = ["mcp", "mcp-server", "ai-agents", "charter"] + [
        APP_NAMES[p].lower().replace("google ", "google-") for p in family.packs
    ]
    return "\n".join(
        [
            "[build-system]",
            'requires = ["hatchling"]',
            'build-backend = "hatchling.build"',
            "",
            "[project]",
            f'name = "{listing.package}"',
            f'version = "{VERSION}"',
            f"description = {json.dumps(listing.tagline)}",
            'readme = "README.md"',
            'license = { text = "Apache-2.0" }',
            'requires-python = ">=3.10"',
            'authors = [{ name = "R28 AI, Inc.", email = "oss@r28.ai" }]',
            "keywords = [" + ", ".join(json.dumps(k) for k in keywords) + "]",
            f'dependencies = ["{FAMILIES_REQUIREMENT}"]',
            "",
            "[project.urls]",
            f'Repository = "https://github.com/{GITHUB_ORG}/{listing.package}"',
            f'Charter = "https://github.com/{GITHUB_ORG}/charter"',
            f'Documentation = "{DOCS}"',
            "",
            "[project.scripts]",
            f'{listing.package} = "{module_name(listing)}:main"',
            "",
            "[tool.hatch.build.targets.wheel]",
            f'packages = ["src/{module_name(listing)}"]',
            "",
        ]
    )


def package_init(family: Family, listing: Listing) -> str:
    return "\n".join(
        [
            "# SPDX-FileCopyrightText: 2026 R28 AI, Inc.",
            "# SPDX-License-Identifier: Apache-2.0",
            "",
            f'"""{listing.title}: the `{family.key}` family of Charter, served over MCP."""',
            "",
            "from __future__ import annotations",
            "",
            "import sys",
            "from typing import List, Optional",
            "",
            "",
            "def main(argv: Optional[List[str]] = None) -> int:",
            '    """`uvx PKG` serves; `uvx PKG login [app]`, `status` and `logout` connect apps."""',
            "    from charter_families import main as run",
            "",
            "    args = sys.argv[1:] if argv is None else argv",
            "    return run(",
            f'        ["{family.key}", *args, "--name", "{listing.key}", "--command", "uvx {listing.package}"]',
            "    )",
            "",
        ]
    )


def package_main(listing: Listing) -> str:
    return "\n".join(
        [
            "# SPDX-FileCopyrightText: 2026 R28 AI, Inc.",
            "# SPDX-License-Identifier: Apache-2.0",
            "",
            f"from {module_name(listing)} import main",
            "",
            "raise SystemExit(main())",
            "",
        ]
    )


def server_json(family: Family, listing: Listing) -> str:
    env = [
        {
            "name": f.env,
            "description": f"{a.name}: {f.label}. Optional: `{listing.package} login` stores it in the keychain instead.",
            "isRequired": False,
            "isSecret": f.secret,
        }
        for a, f in key_fields(family)
    ]
    doc = {
        "$schema": SCHEMA,
        "name": f"io.github.{GITHUB_ORG}/{listing.package}",
        "title": listing.title,
        "description": listing.tagline,
        "version": VERSION,
        "repository": {
            "url": f"https://github.com/{GITHUB_ORG}/{listing.package}",
            "source": "github",
        },
        "packages": [
            {
                "registryType": "pypi",
                "identifier": listing.package,
                "version": VERSION,
                "transport": {"type": "stdio"},
                "environmentVariables": env,
            }
        ],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


GITIGNORE = "\n".join(
    ["__pycache__/", "*.pyc", ".venv/", "dist/", "build/", "*.egg-info/", ".env", ""]
)


def index() -> str:
    lines = [
        "# Charter MCP families",
        "",
        "One directory per family, each a repository and a PyPI package of its own.",
        "Generated by `scripts/generate.py` in the charter-families repo; edit the",
        "catalogue there (`src/charter_families/catalogue.py`), not these files.",
        "",
        "| Directory | Workflows | Tools | Tokens | Without Google/Granola | Apps |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for key, family in FAMILIES.items():
        listing = LISTINGS[key]
        tools = family.tools()
        lines.append(
            f"| `{listing.package}` | {len(family.workflows)} | {len(tools)} | "
            f"{sum(schema_tokens(t) for t in tools):,} | {runs_without_google(family)} | "
            f"{', '.join(APP_NAMES[p] for p in family.packs)} |"
        )
    lines += [
        "",
        "Every app connects with the user's own key, token or OAuth client. There is no",
        "app to register with any service before a release.",
        "",
        "## Publishing one",
        "",
        "1. Release Charter 0.3.0 (MCP prompts and instructions), then `charter-families`",
        f"   from its own repo (`{FAMILIES_REQUIREMENT}`).",
        f"2. `cd <dir> && git init && gh repo create {GITHUB_ORG}/<dir> --public --source . --push`",
        "3. `uv build && uv publish`",
        "4. `mcp-publisher login github && mcp-publisher publish` (reads `server.json`; the",
        "   `mcp-name` comment at the top of the README is what proves the PyPI package is yours)",
        "5. `npx @anthropic-ai/mcpb pack` and attach the `.mcpb` to a GitHub release, for",
        "   Claude Desktop. Then submit it to Anthropic's extensions directory.",
        "6. Submit the repository to the directories that index by repo: Smithery, Glama,",
        "   PulseMCP, mcp.so, and a PR to awesome-mcp-servers.",
        "",
    ]
    return "\n".join(lines)


def write(out: Path) -> List[Path]:
    written: List[Path] = []
    out.mkdir(parents=True, exist_ok=True)
    for key, family in FAMILIES.items():
        listing = LISTINGS[key]
        check(family, listing)
        base = out / listing.package
        src = base / "src" / module_name(listing)
        src.mkdir(parents=True, exist_ok=True)
        files = {
            base / "README.md": readme(family, listing),
            base / "pyproject.toml": pyproject(family, listing),
            base / "server.json": server_json(family, listing),
            base / ".gitignore": GITIGNORE,
            base / "manifest.json": manifest(family, listing),
            base / "src" / "server.py": server_py(listing),
            src / "__init__.py": package_init(family, listing),
            src / "__main__.py": package_main(listing),
        }
        for path, text in files.items():
            path.write_text(text)
            written.append(path)
        shutil.copyfile(ROOT / "LICENSE", base / "LICENSE")
        written.append(base / "LICENSE")
    (out / "README.md").write_text(index())
    written.append(out / "README.md")
    return written


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT.parent / "charter-mcp-families")
    args = parser.parse_args(argv)
    missing = set(FAMILIES) ^ set(LISTINGS)
    if missing:
        print(f"families and listings disagree: {sorted(missing)}", file=sys.stderr)
        return 1
    written = write(args.out)
    print(f"wrote {len(written)} files for {len(FAMILIES)} families under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
