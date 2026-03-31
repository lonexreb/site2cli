"""Unified MCP server — serves ALL discovered sites as MCP tools via the tier router."""

from __future__ import annotations

import json
import re
from typing import Any

from site2cli.generators.mcp_gen import _spec_to_mcp_tools
from site2cli.models import MCPToolSchema, SiteEntry
from site2cli.registry import SiteRegistry


def spec_to_tool_schemas(site: SiteEntry, spec: dict) -> list[MCPToolSchema]:
    """Public wrapper around the tool-schema extraction logic."""
    return _spec_to_mcp_tools(site, spec)


def _build_tool_registry(
    registry: SiteRegistry,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Build the tool list and lookup map from all registered sites.

    Returns:
        (tools_list, tool_map) where tool_map maps tool_name -> {domain, action}.
    """
    sites = registry.list_sites()
    tools: list[dict[str, Any]] = []
    tool_map: dict[str, dict[str, str]] = {}

    for site in sites:
        domain_prefix = re.sub(r"[^a-z0-9]", "_", site.domain.split(".")[0])
        for action in site.actions:
            tool_name = f"{domain_prefix}_{action.name}"
            # Build a basic input schema from the endpoint if available
            properties: dict[str, Any] = {}
            required: list[str] = []
            if action.endpoint:
                for param in action.endpoint.parameters:
                    properties[param.name] = {
                        "type": param.param_type,
                        "description": param.description,
                    }
                    if param.required:
                        required.append(param.name)

            tools.append({
                "name": tool_name,
                "description": action.description or action.name,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })
            tool_map[tool_name] = {
                "domain": site.domain,
                "action": action.name,
            }

    return tools, tool_map


async def run_unified_mcp_server(registry: SiteRegistry) -> None:
    """Run the unified MCP server on stdio.

    All discovered sites are exposed as MCP tools. Tool execution
    goes through the Router, which automatically uses the best tier.
    """
    from mcp import types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    from site2cli.router import Router

    server = Server("site2cli-unified")
    router = Router(registry)

    tools_list, tool_map = _build_tool_registry(registry)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in tools_list
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent]:
        if name not in tool_map:
            raise ValueError(f"Unknown tool: {name}")

        info = tool_map[name]
        result = await router.execute(info["domain"], info["action"], arguments)

        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str),
            )
        ]

    async with stdio_server() as (read_stream, write_stream):
        init_opts = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_opts)
