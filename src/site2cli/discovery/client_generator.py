"""Generate Python API clients from OpenAPI specs."""

from __future__ import annotations

import re
from pathlib import Path


def _sanitize_name(name: str) -> str:
    """Convert a string to a valid Python identifier."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name and name[0].isdigit():
        name = f"_{name}"
    return name.lower()


def _operation_id_to_method(op_id: str) -> str:
    """Convert an operationId to a Python method name."""
    return _sanitize_name(op_id)


def _schema_to_type_hint(schema: dict) -> str:
    """Convert JSON Schema to Python type hint."""
    type_map = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
        "null": "None",
    }
    t = schema.get("type", "any")
    if t == "array":
        items = schema.get("items", {})
        item_type = _schema_to_type_hint(items)
        return f"list[{item_type}]"
    return type_map.get(t, "Any")


def generate_client_code(spec: dict, class_name: str | None = None) -> str:
    """Generate a Python client class from an OpenAPI spec.

    Returns the Python source code as a string.
    """
    info = spec.get("info", {})
    title = info.get("title", "API")
    if not class_name:
        class_name = _sanitize_name(title.replace("API", "").strip()).title().replace("_", "")
        class_name = f"{class_name}Client" if class_name else "APIClient"

    servers = spec.get("servers", [])
    base_url = servers[0]["url"] if servers else "http://localhost"

    methods = []
    for path, path_item in spec.get("paths", {}).items():
        for http_method, operation in path_item.items():
            if http_method in ("parameters", "summary", "description"):
                continue
            op_id = operation.get("operationId", f"{http_method}_{path}")
            method_name = _operation_id_to_method(op_id)
            summary = operation.get("summary", "")

            # Build parameters
            params = []
            path_params = []
            query_params = []
            for param in operation.get("parameters", []):
                p_name = _sanitize_name(param["name"])
                p_type = _schema_to_type_hint(param.get("schema", {"type": "string"}))
                required = param.get("required", False)
                if required:
                    params.append(f"{p_name}: {p_type}")
                else:
                    params.append(f"{p_name}: {p_type} | None = None")
                if param["in"] == "path":
                    path_params.append(p_name)
                elif param["in"] == "query":
                    query_params.append(p_name)

            # Body parameters
            body_param = None
            req_body = operation.get("requestBody", {})
            if req_body:
                content = req_body.get("content", {})
                for ct, ct_info in content.items():
                    schema = ct_info.get("schema", {})
                    if schema.get("type") == "object" and "properties" in schema:
                        for prop_name, prop_schema in schema["properties"].items():
                            p_name = _sanitize_name(prop_name)
                            p_type = _schema_to_type_hint(prop_schema)
                            required_props = schema.get("required", [])
                            if prop_name in required_props:
                                params.append(f"{p_name}: {p_type}")
                            else:
                                params.append(f"{p_name}: {p_type} | None = None")
                        body_param = "body_props"
                    else:
                        params.append("body: dict | None = None")
                        body_param = "body"
                    break

            # Build method body
            param_str = ", ".join(["self"] + params)

            # Build URL
            url_expr = f'f"{path}"' if path_params else f'"{path}"'

            # Build query params dict
            query_dict_lines = ""
            if query_params:
                items = ", ".join(f'"{p}": {p}' for p in query_params)
                query_dict_lines = f"""
        params = {{{items}}}
        params = {{k: v for k, v in params.items() if v is not None}}"""

            # Build body dict
            body_lines = ""
            if body_param == "body_props":
                schema = list(content.values())[0].get("schema", {})
                prop_names = [_sanitize_name(p) for p in schema.get("properties", {}).keys()]
                items = ", ".join(f'"{p}": {p}' for p in prop_names)
                body_lines = f"""
        json_body = {{{items}}}
        json_body = {{k: v for k, v in json_body.items() if v is not None}}"""

            # Build request call
            request_args = [f'"{http_method.upper()}"', f"self._base_url + {url_expr}"]
            if query_params:
                request_args.append("params=params")
            if body_param == "body_props":
                request_args.append("json=json_body")
            elif body_param == "body":
                request_args.append("json=body")

            method_code = f'''    def {method_name}({param_str}) -> dict:
        """{summary}"""
        {query_dict_lines.strip()}
        {body_lines.strip()}
        response = self._client.request({", ".join(request_args)})
        response.raise_for_status()
        return response.json()
'''.rstrip()

            methods.append(method_code)

    methods_str = "\n\n".join(methods)

    code = f'''"""Auto-generated API client for {title}."""

from __future__ import annotations

import httpx


class {class_name}:
    """{title} client.

    Auto-generated by site2cli from OpenAPI spec.
    """

    def __init__(
        self,
        base_url: str = "{base_url}",
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            headers=headers or {{}},
            cookies=cookies or {{}},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "{class_name}":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

{methods_str}
'''
    return code


def save_client(code: str, output_path: Path) -> Path:
    """Save generated client code to a file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(code)
    return output_path
