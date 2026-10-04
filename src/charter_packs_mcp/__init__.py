# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Families — the shipped packs cut by the job rather than by the API.

A pack is one API's tools. A family is the tools one kind of work calls, across
APIs: engineering is GitHub, Linear and Slack together; a support inbox is
Gmail, Stripe and Linear. Each family carries the workflows that justify its
tools, and an MCP server built from one serves those workflows as prompts —
which Claude Code lists as slash commands — beside exactly the tools they name.

    python -m charter_packs_mcp engineering            # serve
    python -m charter_packs_mcp support,finance        # two families, one server
    python -m charter_packs_mcp engineering login      # connect the apps it uses

Nothing here runs a workflow. A prompt is text the client's agent reads: it says
which tools to call and in what order, and the agent decides what to repeat or
skip, so the rule that Charter describes one request holds. What a family fixes
is the surface: every step names a tool a pack ships, and the server offers
those tools and no others.

Two families on one server share their tools rather than listing them twice:
``support,finance`` is the union, and a Linear tool both use is served once.
"""

from __future__ import annotations

import argparse
import importlib
import io
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Sequence, Tuple

from charter import Tool

from charter_packs_mcp.catalogue import CATALOGUE

__all__ = ["FAMILIES", "Family", "Workflow", "main", "resolve", "tools_for", "workflows_for"]

TITLES: Dict[str, str] = {
    "engineering": "Engineering",
    "product": "Product",
    "sales": "Sales",
    "marketing": "Marketing",
    "support": "Customer success",
    "finance": "Finance and RevOps",
    "commerce": "E-commerce",
    "ops": "Founder and ops",
    "research": "Research",
    "people": "People and hiring",
    "agency": "Freelance and agency",
}


def _slug(title: str) -> str:
    text = title.replace("→", " to ").replace("↔", " and ").replace("&", " and ")
    return re.sub(r"[^A-Za-z0-9]+", "_", text.replace("+", " and ")).strip("_").lower()


@dataclass(frozen=True)
class Workflow:
    """One cross-app job: the tools it calls in order, and why it is worth running."""

    family: str
    title: str
    steps: Tuple[str, ...]
    why: str
    cadence: str

    @property
    def name(self) -> str:
        """The prompt name: the title, snake_cased. A host shows it as a slash command."""
        return _slug(self.title)

    @property
    def description(self) -> str:
        return self.why

    @property
    def apps(self) -> Tuple[str, ...]:
        """The packs this workflow touches, in the order it first reaches them."""
        seen: List[str] = []
        for step in self.steps:
            pack = step.split(".", 1)[0]
            if pack not in seen:
                seen.append(pack)
        return tuple(seen)

    def render(self, details: str = "") -> str:
        """The prompt text. Tools are named as the server publishes them, ``pack_tool``."""
        lines = [f"{self.title}. {self.why}", "", "Use these tools, in this order:"]
        lines += [f"{i}. `{step.replace('.', '_', 1)}`" for i, step in enumerate(self.steps, 1)]
        lines += [
            "",
            "Before anything else, check whether any of these tools' apps is not "
            "connected: the server's instructions say, and so does `connection_status`. "
            "If one is not, tell me how to connect it first, before asking me for anything.",
            "Read before you write. Before any call that creates, sends, changes or "
            "deletes something, show me what it will do and wait for my go-ahead, "
            "unless I have told you to go ahead without asking.",
            "If a tool says its app is not connected, tell me how to connect it, as "
            "the tool says, and stop there.",
        ]
        if details.strip():
            lines += ["", f"Context from me: {details.strip()}"]
        return "\n".join(lines)


@dataclass(frozen=True)
class Family:
    """The workflows one kind of work runs, and the tools they call."""

    key: str
    title: str
    workflows: Tuple[Workflow, ...]

    @property
    def steps(self) -> Tuple[str, ...]:
        """Every ``pack.tool`` the workflows name, once each, in first-use order."""
        out: List[str] = []
        for workflow in self.workflows:
            for step in workflow.steps:
                if step not in out:
                    out.append(step)
        return tuple(out)

    @property
    def packs(self) -> Tuple[str, ...]:
        out: List[str] = []
        for step in self.steps:
            pack = step.split(".", 1)[0]
            if pack not in out:
                out.append(pack)
        return tuple(out)

    def tools(self) -> List[Tool]:
        return [_tool(step) for step in self.steps]


def _tool(step: str) -> Tool:
    """The shipped tool a ``pack.tool`` step names: the one in the pack's ``TOOLS``."""
    pack, name = step.split(".", 1)
    module = importlib.import_module(f"charter.packs.{pack}")
    for tool in module.TOOLS:
        if tool.name == name:
            return tool
    raise KeyError(f"{step}: no tool named {name!r} in charter.packs.{pack}.TOOLS")


def _build() -> Dict[str, Family]:
    families: Dict[str, Family] = {}
    for key, entries in CATALOGUE.items():
        workflows = tuple(
            Workflow(
                family=key,
                title=title,
                steps=tuple(step.strip() for step in steps.split(">")),
                why=why,
                cadence=cadence,
            )
            for title, steps, why, cadence in entries
        )
        families[key] = Family(key=key, title=TITLES[key], workflows=workflows)
    return families


FAMILIES: Dict[str, Family] = _build()


def resolve(spec: Iterable[str]) -> List[Family]:
    """Family names, repeated or comma-separated, to families. Unknown names raise."""
    names: List[str] = []
    for item in spec:
        for name in item.split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    unknown = [name for name in names if name not in FAMILIES]
    if unknown:
        raise ValueError(f"unknown family {', '.join(unknown)}; choose from {', '.join(FAMILIES)}")
    if not names:
        raise ValueError(f"name at least one family: {', '.join(FAMILIES)}")
    return [FAMILIES[name] for name in names]


def tools_for(families: Sequence[Family]) -> List[Tool]:
    """The union of the families' tools. A tool two families share is served once."""
    out: List[Tool] = []
    for family in families:
        for tool in family.tools():
            if not any(tool is kept for kept in out):
                out.append(tool)
    return out


def workflows_for(families: Sequence[Family]) -> List[Workflow]:
    return [workflow for family in families for workflow in family.workflows]


def _module_tools(pack: str) -> List[Tool]:
    return list(importlib.import_module(f"charter.packs.{pack}").TOOLS)


def _session(tools: List[Tool], connections: Any, command: str) -> Any:
    """A session that reads new credentials before giving up on a call, and says how to connect."""
    from charter import CredentialError
    from charter.session import ToolSession

    from charter_packs_mcp.apps import app_for_pack
    from charter_packs_mcp.signin import how_to_connect

    class FamilySession(ToolSession):
        async def dispatch(
            self, name: str, arguments: Optional[Dict[str, Any]] = None, **kw: Any
        ) -> Any:
            tool = self.visible().get(name)
            if tool is None or tool.pack is None:
                return await super().dispatch(name, arguments, **kw)
            try:
                return await super().dispatch(name, arguments, **kw)
            except CredentialError as exc:
                # Connected since startup, from a terminal or the `connect` tool?
                if connections.load():
                    return await super().dispatch(name, arguments, **kw)
                app = app_for_pack(tool.pack)
                state = connections.state(app)
                if state == "not connected":
                    message = f"{app.name} is not connected. To connect it: {how_to_connect(app, command)}."
                elif state == "set in the environment":
                    # Say where it came from: "log in again" cannot fix a variable the
                    # client sets, which wins over the keychain for as long as it is set.
                    names = [f.env for f in app.fields if os.environ.get(f.env)]
                    what = " and ".join(f"the {n}" for n in names) or "the credential"
                    message = (
                        f"{app.name} refused {what} set in the client's config for this "
                        f"server ({exc}). Fix or remove it there: while it is set, the "
                        f"keychain is not used, so `{command} login {app.key}` changes nothing."
                    )
                else:
                    message = (
                        f"{app.name} refused the credential `{command} login` stored ({exc}). "
                        f"Reconnect with `{command} login {app.key}`."
                    )
                raise CredentialError(
                    message, provider=exc.provider, status_code=exc.status_code
                ) from exc

    return FamilySession(tools, progressive=False)


def _utf8_output() -> None:
    """Write what this prints as UTF-8, wherever it goes.

    Windows encodes a piped or redirected stream in the ANSI code page, cp1252,
    which has no "→": `status` raised UnicodeEncodeError on Windows as soon as an
    agent ran it, or its output went to a file, rather than to a console. UTF-8 is
    what Python is moving every stream to (PEP 686). The MCP protocol itself is
    unaffected: the server writes it to ``sys.stdout.buffer``, as UTF-8 already.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() not in (
            "utf-8",
            "utf8",
        ):
            stream.reconfigure(encoding="utf-8")


def _drop_unfilled_placeholders(environ: MutableMapping[str, str]) -> List[str]:
    """Unset each app variable a client passed as an unfilled ``${...}`` placeholder.

    Claude Desktop hands a bundle's optional settings to the server as, literally,
    ``${user_config.github_token}`` when the person leaves them empty. As a value it
    won over the keychain: every app read as connected, and GitHub answered "Bad
    credentials" to a token nobody had set. Runs before any pack is imported,
    since some read their variables at import.
    """
    from charter_packs_mcp.apps import APPS

    names = sorted({f.env for app in APPS.values() for f in app.fields})
    dropped = [n for n in names if re.fullmatch(r"\$\{[^}]*\}", environ.get(n, ""))]
    for name in dropped:
        del environ[name]
    if dropped:
        print(
            f"charter: ignoring {', '.join(dropped)}, left unfilled by the client", file=sys.stderr
        )
    return dropped


def main(argv: Optional[List[str]] = None) -> int:
    """Serve families over MCP (stdio), or connect the apps they use."""
    _utf8_output()
    _drop_unfilled_placeholders(os.environ)
    parser = argparse.ArgumentParser(
        prog="python -m charter_packs_mcp",
        description="Serve Charter families over the Model Context Protocol (stdio), "
        "or connect the apps they use.",
    )
    parser.add_argument(
        "family",
        help="Which family, one of: " + ", ".join(FAMILIES) + ". Comma-separate several "
        "to serve them from one server.",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="serve",
        choices=("serve", "login", "logout", "status"),
        help="serve (the default) runs the server; login connects apps; logout forgets "
        "one; status says where each stands.",
    )
    parser.add_argument("apps", nargs="*", help="For login and logout: which apps (default: all).")
    parser.add_argument("--name", default=None, help="Server name (default: the family names).")
    parser.add_argument(
        "--command",
        default=None,
        help="How users start this server, for the instructions it gives (default: "
        "python -m charter_packs_mcp <family>).",
    )
    args = parser.parse_args(argv)

    try:
        families = resolve([args.family])
    except ValueError as exc:
        parser.error(str(exc))

    from charter_packs_mcp.connections import Connections

    tools = tools_for(families)
    packs: List[str] = []
    for tool in tools:
        if tool.pack and tool.pack not in packs:
            packs.append(tool.pack)
    command = args.command or f"python -m charter_packs_mcp {args.family}"
    connections = Connections(packs)
    connections.load()

    if args.action == "status":
        from charter_packs_mcp.signin import status_text

        print(status_text(connections, command))
        return 0
    if args.action == "logout":
        from charter_packs_mcp.apps import APPS

        for key in args.apps or [a.key for a in connections.apps]:
            if key in APPS:
                connections.forget(APPS[key])
                print(f"{APPS[key].name}: forgotten")
        return 0
    if args.action == "login":
        import asyncio

        from charter_packs_mcp.signin import login

        return asyncio.run(login(connections, args.apps, command=command))

    from charter.adapters.mcp import serve

    from charter_packs_mcp.signin import ConnectTool, SetupPrompt, StatusTool, status_text

    workflows = workflows_for(families)
    connect = ConnectTool(connections, command)
    name = args.name or "-".join(family.key for family in families)
    print(
        f"charter: serving {len(tools)} tools and {len(workflows)} workflows from "
        f"{', '.join(family.key for family in families)} over MCP (stdio)",
        file=sys.stderr,
    )
    serve(
        _session(tools, connections, command),
        name=name,
        prompts=[SetupPrompt(command), *workflows],
        instructions=status_text(connections, command),
        local_tools=[connect, StatusTool(connections, command, connect)],
    )
    return 0
