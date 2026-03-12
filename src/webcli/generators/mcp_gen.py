"""MCP server generation from OpenAPI specs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from webcli.models import MCPToolSchema, SiteEntry, Tier


def _spec_to_mcp_tools(site: SiteEntry, spec: dict) -> list[MCPToolSchema]:
    """Convert OpenAPI spec operations to MCP tool schemas."""
    tools = []
    domain_prefix = re.sub(r"[^a-z0-9]", "_", site.domain.split(".")[0])

    for path, path_item in spec.get("paths", {}).items():
        for http_method, operation in path_item.items():
            if http_method in ("parameters", "summary", "description"):
                continue

            op_id = operation.get("operationId", f"{http_method}_{path}")
            tool_name = f"{domain_prefix}_{op_id}"
            description = operation.get("summary", op_id)

            # Build input schema from parameters + request body
            properties = {}
            required = []

            for param in operation.get("parameters", []):
                p_name = param["name"]
                p_schema = param.get("schema", {"type": "string"})
                properties[p_name] = {
                    "type": p_schema.get("type", "string"),
                    "description": param.get("description", ""),
                }
                if param.get("required"):
                    required.append(p_name)

            req_body = operation.get("requestBody", {})
            if req_body:
                content = req_body.get("content", {})
                for ct_info in content.values():
                    schema = ct_info.get("schema", {})
                    if schema.get("type") == "object" and "properties" in schema:
                        for prop_name, prop_schema in schema["properties"].items():
                            properties[prop_name] = {
                                "type": prop_schema.get("type", "string"),
                                "description": prop_schema.get("description", ""),
                            }
                            if prop_name in schema.get("required", []):
                                required.append(prop_name)
                    break

            input_schema = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

            # Determine tier from site actions
            tier = Tier.API
            for action in site.actions:
                if action.name == op_id:
                    tier = action.tier
                    break

            tools.append(
                MCPToolSchema(
                    name=tool_name,
                    description=description,
                    input_schema=input_schema,
                    site_domain=site.domain,
                    action_name=op_id,
                    tier=tier,
                )
            )

    return tools


def generate_mcp_server_code(site: SiteEntry, spec: dict) -> str:
    """Generate Python code for an MCP server from an OpenAPI spec.

    Returns the Python source code as a string.
    """
    tools = _spec_to_mcp_tools(site, spec)

    tool_registrations = []
    tool_handlers = []

    for tool in tools:
        input_schema_json = json.dumps(tool.input_schema, indent=8)

        tool_registrations.append(f"""    types.Tool(
        name="{tool.name}",
        description="{tool.description}",
        inputSchema={input_schema_json},
    )""")

        # Build the handler
        handler = f'''    if name == "{tool.name}":
        return await _execute_api_call(
            site_domain="{tool.site_domain}",
            method="{_find_method(spec, tool.action_name)}",
            path="{_find_path(spec, tool.action_name)}",
            arguments=arguments,
        )'''
        tool_handlers.append(handler)

    registrations_str = ",\n".join(tool_registrations)
    handlers_str = "\n".join(tool_handlers)

    code = f'''"""Auto-generated MCP server for {site.domain}."""

from __future__ import annotations

import json
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types


server = Server("{site.domain}-webcli")

BASE_URL = "{site.base_url}"


async def _execute_api_call(
    site_domain: str,
    method: str,
    path: str,
    arguments: dict,
) -> list[types.TextContent]:
    """Execute an API call and return the result as MCP content."""
    url = BASE_URL.rstrip("/") + path

    # Separate path params from query/body params
    query_params = {{}}
    body_params = {{}}
    for key, value in arguments.items():
        if f"{{{{{key}}}}}" in path:
            url = url.replace(f"{{{{{key}}}}}", str(value))
        elif method in ("POST", "PUT", "PATCH"):
            body_params[key] = value
        else:
            query_params[key] = value

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            url,
            params=query_params or None,
            json=body_params or None,
        )

    try:
        result = json.dumps(response.json(), indent=2)
    except Exception:
        result = response.text

    return [types.TextContent(type="text", text=result)]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
{registrations_str}
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
{handlers_str}
    raise ValueError(f"Unknown tool: {{name}}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
'''
    return code


def _find_method(spec: dict, op_id: str) -> str:
    """Find the HTTP method for an operation ID in the spec."""
    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if operation.get("operationId") == op_id:
                return method.upper()
    return "GET"


def _find_path(spec: dict, op_id: str) -> str:
    """Find the path for an operation ID in the spec."""
    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if operation.get("operationId") == op_id:
                return path
    return "/"


def save_mcp_server(code: str, output_path: Path) -> Path:
    """Save generated MCP server code to a file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(code)
    return output_path
