"""Unix socket daemon client — sends JSON-RPC requests to the daemon."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path


class DaemonClient:
    """Client for communicating with the site2cli daemon over Unix socket."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    async def send(self, method: str, params: dict, req_id: int = 1) -> dict:
        """Send a JSON-RPC request to the daemon.

        Returns:
            The result dict from the daemon response.

        Raises:
            ConnectionError: If the daemon is not running.
            RuntimeError: If the daemon returns an error.
        """
        if not self._socket_path.exists():
            raise ConnectionError(
                f"Daemon socket not found at {self._socket_path}. "
                "Start the daemon with: site2cli daemon start"
            )

        reader, writer = await asyncio.open_unix_connection(str(self._socket_path))

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        }

        try:
            writer.write(json.dumps(request).encode())
            await writer.drain()

            data = await reader.read(65536)
            response = json.loads(data.decode())

            if "error" in response:
                raise RuntimeError(response["error"].get("message", "Unknown error"))

            return response.get("result", {})
        finally:
            writer.close()
            await writer.wait_closed()

    async def list_sessions(self) -> list[str]:
        """List active sessions on the daemon."""
        result = await self.send("list_sessions", {})
        return result.get("sessions", [])

    async def create_session(
        self,
        name: str = "default",
        profile: str | None = None,
        domain: str | None = None,
    ) -> dict:
        """Create a new browser session on the daemon."""
        params = {"name": name}
        if profile:
            params["profile"] = profile
        if domain:
            params["domain"] = domain
        return await self.send("create_session", params)

    async def close_session(self, name: str = "default") -> dict:
        """Close a session on the daemon."""
        return await self.send("close_session", {"name": name})

    async def execute(
        self,
        domain: str,
        action: str,
        params: dict | None = None,
        session: str = "default",
    ) -> dict:
        """Execute an action via the daemon."""
        return await self.send("execute", {
            "session": session,
            "domain": domain,
            "action": action,
            "params": params or {},
        })

    async def shutdown(self) -> dict:
        """Shut down the daemon."""
        return await self.send("shutdown", {})
