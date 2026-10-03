# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Install a family the way someone without git does, then talk to it over MCP.

    python scripts/no_git_check.py <wheel URL> <bundle directory>

Both ways a client starts the server are checked: the command `uv tool install`
puts on the PATH (Claude Code, Codex, VS Code, Cursor), and the `uv run` the
`.mcpb` manifest gives Claude Desktop. Each must answer `initialize`, list its
tools and prompts, and run `connection_status`.

Every command runs with uv alone on its PATH, and the check fails if git can
still be found there: Windows and a Mac without the developer tools have none,
and an install that needed it failed with "Git executable not found". CI runs
this on Windows, macOS and Linux against wheels served from the runner (see
.github/workflows/ci.yml).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def git_free_env(tmp: Path) -> Dict[str, str]:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is not installed")
    bindir = tmp / "path"
    bindir.mkdir()
    shutil.copy2(uv, bindir / Path(uv).name)
    dirs = [str(bindir)]
    if os.name == "nt":  # the system's own DLLs and tools; git is never here
        dirs.append(os.path.join(os.environ["SYSTEMROOT"], "System32"))
    path = os.pathsep.join(dirs)
    if shutil.which("git", path=path):
        raise SystemExit(f"git is still reachable on {path}")
    inherited = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # this script's own
    return {
        **inherited,
        "PATH": path,
        "UV_NO_CACHE": "1",
        "UV_TOOL_DIR": str(tmp / "tools"),
        "UV_TOOL_BIN_DIR": str(tmp / "bin"),
        "CHARTER_CREDENTIALS_FILE": str(tmp / "credentials.json"),
    }


async def talk(command: str, args: List[str], env: Dict[str, str]) -> str:
    params = StdioServerParameters(command=command, args=args, env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            prompts = [p.name for p in (await session.list_prompts()).prompts]
            result = await session.call_tool("connection_status", {})
    text = "".join(getattr(c, "text", "") for c in result.content)
    if not tools or "setup" not in prompts or "Not connected yet" not in text:
        raise SystemExit(f"unexpected answer: {len(tools)} tools, prompts {prompts}, {text!r}")
    return f"{len(tools)} tools, {len(prompts)} prompts; connection_status: {text.splitlines()[0]}"


def main() -> None:
    url, bundle = sys.argv[1], Path(sys.argv[2]).resolve()
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        env = git_free_env(tmp)
        uv = str(tmp / "path" / Path(shutil.which("uv") or "uv").name)
        print(f"PATH: {env['PATH']} (no git)")

        subprocess.run([uv, "tool", "install", url], env=env, check=True)
        exe = next((tmp / "bin").iterdir())
        print(
            f"installed, as Claude Code or Cursor starts it: {asyncio.run(talk(str(exe), [], env))}"
        )

        # What manifest.json's mcp_config has Claude Desktop run, in the unpacked bundle.
        args = ["run", "--directory", str(bundle), "src/server.py"]
        print(f"the .mcpb, as Claude Desktop starts it: {asyncio.run(talk(uv, args, env))}")


if __name__ == "__main__":
    main()
