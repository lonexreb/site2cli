"""Unix socket daemon server — keeps browser alive across CLI invocations."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from site2cli.browser.session import SessionManager

logger = logging.getLogger("site2cli.daemon")


class DaemonServer:
    """JSON-RPC server over Unix socket for persistent browser sessions."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path
        self._session_mgr = SessionManager()
        self._running = True

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    async def run(self) -> None:
        """Start the daemon server."""
        # Clean up stale socket
        if self._socket_path.exists():
            self._socket_path.unlink()

        server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        logger.info("Daemon listening on %s", self._socket_path)

        async with server:
            while self._running:
                await asyncio.sleep(0.5)

        # Cleanup
        await self._session_mgr.close_all()
        if self._socket_path.exists():
            self._socket_path.unlink()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single client connection."""
        try:
            data = await reader.read(65536)
            if not data:
                return

            request = json.loads(data.decode())
            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id", 0)

            result = await self._dispatch(method, params)

            response = {"jsonrpc": "2.0", "result": result, "id": req_id}
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as e:
            error_resp = {
                "jsonrpc": "2.0",
                "error": {"code": -1, "message": str(e)},
                "id": req_id if "req_id" in locals() else 0,
            }
            writer.write(json.dumps(error_resp).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _dispatch(self, method: str, params: dict) -> dict:
        """Dispatch a JSON-RPC method."""
        if method == "list_sessions":
            return {"sessions": self._session_mgr.list()}

        elif method == "create_session":
            name = params.get("name", "default")
            from site2cli.browser.context import create_browser_context

            ctx_mgr = create_browser_context(
                profile=params.get("profile"),
                session_manager=self._session_mgr,
                session_name=name,
                inject_cookies_for=params.get("domain"),
            )
            browser, context, page = await ctx_mgr.__aenter__()
            return {"session": name, "status": "created"}

        elif method == "close_session":
            name = params.get("name", "default")
            await self._session_mgr.close(name)
            return {"session": name, "status": "closed"}

        elif method == "execute":
            name = params.get("session", "default")
            domain = params.get("domain", "")
            action = params.get("action", "")
            action_params = params.get("params", {})

            from site2cli.config import get_config
            from site2cli.registry import SiteRegistry
            from site2cli.router import Router

            config = get_config()
            registry = SiteRegistry(config.db_path)
            router = Router(registry)
            result = await router.execute(domain, action, action_params)
            return result

        elif method == "discover":
            url = params.get("url", "")
            if not url:
                return {"error": "url required"}
            # Forward to the capture pipeline
            from urllib.parse import urlparse

            from site2cli.discovery.capture import TrafficCapture

            parsed = urlparse(url)
            domain = parsed.hostname or url
            capture = TrafficCapture(target_domain=domain)
            exchanges = await capture.capture_page_traffic(
                url, duration_seconds=params.get("duration", 15)
            )
            return {
                "domain": domain,
                "exchanges": len(exchanges),
            }

        elif method == "shutdown":
            self._running = False
            return {"status": "shutting_down"}

        else:
            return {"error": f"Unknown method: {method}"}
