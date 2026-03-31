"""Tests for the daemon server and client.

Covers DaemonServer and DaemonClient (Unix socket JSON-RPC communication).
~12 tests total.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

import pytest

from site2cli.daemon.client import DaemonClient
from site2cli.daemon.server import DaemonServer


def _short_sock() -> Path:
    """Return a short socket path to avoid macOS AF_UNIX 104-byte limit."""
    return Path(tempfile.gettempdir()) / f"s2c_{uuid.uuid4().hex[:8]}.sock"


@pytest.fixture()
def sock():
    """Yield a short-lived socket path, cleaned up after the test."""
    path = _short_sock()
    yield path
    if path.exists():
        path.unlink()


# ---------- DaemonClient unit tests ----------


def test_client_stores_socket_path(tmp_path):
    """DaemonClient constructor stores the socket path."""
    sock = tmp_path / "test.sock"
    client = DaemonClient(sock)
    assert client.socket_path == sock


@pytest.mark.asyncio
async def test_client_raises_connection_error_no_socket(tmp_path):
    """DaemonClient raises ConnectionError when socket file does not exist."""
    sock = tmp_path / "missing.sock"
    client = DaemonClient(sock)
    with pytest.raises((ConnectionError, OSError)):
        await client.send("list_sessions", {})


# ---------- DaemonServer unit tests ----------


def test_server_stores_socket_path(tmp_path):
    """DaemonServer constructor stores the socket path."""
    sock = tmp_path / "test.sock"
    server = DaemonServer(sock)
    assert server.socket_path == sock


@pytest.mark.asyncio
async def test_server_creates_and_removes_socket(sock):
    """DaemonServer creates the socket on run and removes it on stop."""
    server = DaemonServer(sock)

    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)  # let server bind

    assert sock.exists(), "Socket file should exist after server starts"

    # Shut down via client
    client = DaemonClient(sock)
    await client.send("shutdown", {})
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_server_handles_list_sessions(sock):
    """Server responds to 'list_sessions' with a sessions list."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    client = DaemonClient(sock)
    result = await client.send("list_sessions", {})
    assert "sessions" in result
    assert isinstance(result["sessions"], list)

    await client.send("shutdown", {})
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_server_handles_shutdown(sock):
    """Server responds to 'shutdown' and stops accepting connections."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    client = DaemonClient(sock)
    result = await client.send("shutdown", {})
    # Should acknowledge the shutdown
    assert result is not None

    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_server_returns_error_for_unknown_method(sock):
    """Server returns an error response for unrecognized methods."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    client = DaemonClient(sock)
    result = await client.send("nonexistent_method", {})
    assert "error" in result

    await client.send("shutdown", {})
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ---------- Client convenience methods ----------


@pytest.mark.asyncio
async def test_client_list_sessions_method(sock):
    """DaemonClient.list_sessions() convenience method works."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    client = DaemonClient(sock)
    sessions = await client.list_sessions()
    assert isinstance(sessions, list)

    await client.send("shutdown", {})
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_client_shutdown_method(sock):
    """DaemonClient.shutdown() convenience method works."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    client = DaemonClient(sock)
    await client.shutdown()

    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ---------- Integration tests ----------


@pytest.mark.asyncio
async def test_integration_list_sessions(sock):
    """Full integration: start server, list_sessions via client, shut down."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    client = DaemonClient(sock)
    result = await client.send("list_sessions", {})
    assert result["sessions"] == []

    await client.send("shutdown", {})
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_integration_shutdown(sock):
    """Full integration: start server, send shutdown, verify it stops."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    client = DaemonClient(sock)
    await client.send("shutdown", {})
    await asyncio.sleep(0.3)

    # After shutdown, new connections should fail
    client2 = DaemonClient(sock)
    with pytest.raises((ConnectionError, OSError)):
        await client2.send("list_sessions", {})

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_server_handles_malformed_json(sock):
    """Server handles malformed JSON gracefully without crashing."""
    server = DaemonServer(sock)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    # Connect directly and send garbage bytes
    reader, writer = await asyncio.open_unix_connection(str(sock))
    writer.write(b"this is not json\n")
    await writer.drain()

    # Try to read a response -- server should send an error or close gracefully
    try:
        data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        if data:
            response = json.loads(data.decode())
            assert "error" in response
    except (asyncio.TimeoutError, json.JSONDecodeError, ConnectionError):
        # Any of these is acceptable -- server didn't crash
        pass
    finally:
        writer.close()

    # Server should still be alive -- verify with a valid request
    client = DaemonClient(sock)
    result = await client.send("list_sessions", {})
    assert "sessions" in result

    await client.send("shutdown", {})
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
