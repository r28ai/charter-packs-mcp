# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
The copy of a family's bundle that Smithery takes.

    python scripts/smithery_bundle.py <family.mcpb> <family.smithery.mcpb>

Two things differ from the bundle on the GitHub release, both because Smithery reads
what the MCPB format does not say:

- **The runtime.** Smithery's CLI reads it from ``server.type`` and knows python, node
  and binary, not the ``uv`` Claude Desktop is proven to start these bundles with. Its
  client runs ``mcp_config`` (``uv run``) whatever the label, so the copy says python.
- **An input schema on each tool.** Smithery's registry refuses a tool without one, and
  the MCPB manifest schema refuses a tool with one, so it goes into the packed archive
  after ``mcpb pack`` has validated the manifest without it. Each is the top level of
  the tool's own schema: parameter names, types and descriptions, what a listing shows.
  The full schemas run to 190 KB for one Linear tool.
"""

from __future__ import annotations

import json
import sys
import zipfile
from typing import Any, Dict, Optional

from charter.session import ToolSession

from charter_packs_mcp import FAMILIES

# The two tools every family server adds, as the server declares them.
LOCAL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "connection_status": {"type": "object", "properties": {}},
    "connect": {
        "type": "object",
        "properties": {"app": {"type": "string", "description": "The app to connect, by its key."}},
        "required": ["app"],
    },
}


def _type(prop: Dict[str, Any]) -> str:
    if isinstance(prop.get("type"), str):
        return prop["type"]
    for alt in prop.get("anyOf", []):  # Optional[X] is anyOf [X, null]
        if alt.get("type") not in (None, "null"):
            return alt["type"]
    return "object"  # a $ref, or a union of models


def _enum(prop: Dict[str, Any]) -> Optional[list]:
    values = prop.get("enum") or next(
        (a["enum"] for a in prop.get("anyOf", []) if "enum" in a), None
    )
    return values if values and len(values) <= 20 else None


def top_level(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """A tool's input schema, one level deep."""
    properties: Dict[str, Any] = {}
    for name, prop in parameters.get("properties", {}).items():
        entry: Dict[str, Any] = {"type": _type(prop)}
        if prop.get("description"):
            entry["description"] = prop["description"]
        enum = _enum(prop)
        if enum:
            entry["enum"] = enum
        properties[name] = entry
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if parameters.get("required"):
        schema["required"] = parameters["required"]
    return schema


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    tools = {}
    for family in FAMILIES.values():
        tools.update(ToolSession(family.tools(), progressive=False).visible())
    with zipfile.ZipFile(src) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        manifest["server"]["type"] = "python"
        for entry in manifest.get("tools", []):
            name = entry["name"]
            schema = LOCAL_SCHEMAS.get(name)
            entry["inputSchema"] = schema or top_level(tools[name].to_json_schema()["parameters"])
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for item in bundle.infolist():
                if item.filename == "manifest.json":
                    data = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
                else:
                    data = bundle.read(item.filename)
                out.writestr(item, data)
    print(f"{dst}: runtime python, {len(manifest.get('tools', []))} tools with input schemas")


if __name__ == "__main__":
    main()
