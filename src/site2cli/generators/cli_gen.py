"""Dynamic CLI command generation from OpenAPI specs."""

from __future__ import annotations

import json

import typer

from site2cli.models import SiteEntry


def _type_str_to_python(type_str: str) -> type:
    """Map JSON Schema types to Python types for Typer."""
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
    }.get(type_str, str)


def generate_site_commands(site: SiteEntry, spec: dict) -> typer.Typer:
    """Generate a Typer sub-app for a discovered site.

    Returns a Typer app with commands for each endpoint.
    """
    site_app = typer.Typer(
        name=site.domain.replace(".", "-"),
        help=site.description or f"Commands for {site.domain}",
    )

    for path, path_item in spec.get("paths", {}).items():
        for http_method, operation in path_item.items():
            if http_method in ("parameters", "summary", "description"):
                continue

            op_id = operation.get("operationId", f"{http_method}_{path}")
            summary = operation.get("summary", op_id)
            command_name = op_id.replace("_", "-")

            # Build the command function dynamically
            _register_command(
                site_app,
                command_name=command_name,
                summary=summary,
                http_method=http_method.upper(),
                path=path,
                operation=operation,
                site=site,
            )

    return site_app


def _register_command(
    app: typer.Typer,
    command_name: str,
    summary: str,
    http_method: str,
    path: str,
    operation: dict,
    site: SiteEntry,
) -> None:
    """Register a single CLI command on the Typer app."""

    # Collect parameter info
    params_info = []
    for param in operation.get("parameters", []):
        params_info.append({
            "name": param["name"],
            "type": param.get("schema", {}).get("type", "string"),
            "required": param.get("required", False),
            "description": param.get("description", ""),
            "location": param.get("in", "query"),
        })

    # Body parameters
    req_body = operation.get("requestBody", {})
    body_schema = None
    if req_body:
        content = req_body.get("content", {})
        for ct_info in content.values():
            body_schema = ct_info.get("schema", {})
            if body_schema.get("type") == "object" and "properties" in body_schema:
                for prop_name, prop_schema in body_schema["properties"].items():
                    required_props = body_schema.get("required", [])
                    params_info.append({
                        "name": prop_name,
                        "type": prop_schema.get("type", "string"),
                        "required": prop_name in required_props,
                        "description": prop_schema.get("description", ""),
                        "location": "body",
                    })
            break

    # Create a closure-based command
    def make_command(p_info: list, h_method: str, p_path: str, s: SiteEntry):
        def command(
            ctx: typer.Context,
            json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
        ) -> None:
            """Execute the API call."""
            import httpx

            from site2cli.auth.manager import AuthManager

            # Collect parameter values from context
            # In a real implementation, these would be Typer arguments
            # For now, we use extra args from the context
            query_params = {}
            path_params = {}
            body_data = {}

            # Parse extra args as --key=value pairs
            extra = ctx.args or []
            parsed_extra = {}
            i = 0
            while i < len(extra):
                arg = extra[i]
                if arg.startswith("--"):
                    key = arg[2:].replace("-", "_")
                    if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
                        parsed_extra[key] = extra[i + 1]
                        i += 2
                    else:
                        parsed_extra[key] = "true"
                        i += 1
                else:
                    i += 1

            for p in p_info:
                val = parsed_extra.get(p["name"])
                if val is None and p["required"]:
                    typer.echo(f"Missing required parameter: --{p['name']}", err=True)
                    raise typer.Exit(1)
                if val is not None:
                    if p["location"] == "path":
                        path_params[p["name"]] = val
                    elif p["location"] == "body":
                        body_data[p["name"]] = val
                    else:
                        query_params[p["name"]] = val

            # Build URL
            url = s.base_url.rstrip("/") + p_path
            for k, v in path_params.items():
                url = url.replace(f"{{{k}}}", v)

            # Auth
            auth_mgr = AuthManager()
            headers = auth_mgr.get_auth_headers(s.domain, s.auth_type)
            cookies = auth_mgr.get_auth_cookies(s.domain)

            with httpx.Client(headers=headers, cookies=cookies, timeout=30) as client:
                response = client.request(
                    h_method,
                    url,
                    params=query_params or None,
                    json=body_data or None,
                )

            if json_output:
                try:
                    typer.echo(json.dumps(response.json(), indent=2))
                except Exception:
                    typer.echo(response.text)
            else:
                try:
                    data = response.json()
                    _pretty_print(data)
                except Exception:
                    typer.echo(response.text)

        command.__doc__ = summary
        return command

    cmd_fn = make_command(params_info, http_method, path, site)
    app.command(
        name=command_name,
        help=summary,
        context_settings={"allow_extra_args": True, "allow_interspersed_args": False},
    )(cmd_fn)


def _pretty_print(data: object, indent: int = 0) -> None:
    """Pretty-print JSON data in a human-readable format."""
    from rich.console import Console
    from rich.json import JSON

    console = Console()
    console.print(JSON(json.dumps(data, default=str)))
