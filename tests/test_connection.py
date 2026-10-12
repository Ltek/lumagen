# pyright: reportPrivateUsage=false
"""Connection-lifecycle tests against a fake TCP-to-serial adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

import pytest

from custom_components.lumagen.client import (
    LumagenClient,
    LumagenConnectionError,
    WatchdogMode,
)


class FakeAdapter:
    """Minimal stand-in for an iTach IP2SL wired to a Lumagen.

    mode:
      "echo"   — echoes every byte and answers queries (Echo-RS232 = On)
      "noecho" — answers queries without echo (Echo-RS232 = Off)
      "wedged" — accepts TCP, reads, never sends anything
    """

    def __init__(self, mode: str = "echo") -> None:
        self.mode = mode
        self.received: list[bytes] = []
        self.connections = 0
        self.closed = 0
        self.writers: list[asyncio.StreamWriter] = []
        self._server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for w in self.writers:
            with suppress(Exception):
                w.transport.abort()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        self.writers.append(writer)
        buf = b""
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                self.received.append(data)
                if self.mode == "wedged":
                    continue
                out = data if self.mode == "echo" else b""
                buf += data
                for query, reply in (
                    (b"ZQS00", b"!S00,Ok\r\n"),
                    (b"ZQS02", b"!S02,1\r\n"),
                ):
                    while query in buf:
                        buf = buf.replace(query, b"", 1)
                        out += reply
                buf = buf[-8:]
                if out:
                    writer.write(out)
                    await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self.closed += 1

    def sent_text(self) -> str:
        return b"".join(self.received).decode("ascii", "ignore")


@asynccontextmanager
async def adapter(mode: str = "echo") -> AsyncIterator[FakeAdapter]:
    fake = FakeAdapter(mode)
    await fake.start()
    try:
        yield fake
    finally:
        await fake.stop()


def _client(
    port: int,
    *,
    watchdog: WatchdogMode = "auto",
    keepalive_interval: float = 30.0,
) -> LumagenClient:
    return LumagenClient(
        "127.0.0.1",
        port,
        watchdog=watchdog,
        watchdog_timeout=0.3,
        keepalive_interval=keepalive_interval,
        verify_timeout=0.3,
        connect_timeout=1.0,
    )


async def _until(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


class TestVerifiedConnect:
    @pytest.mark.anyio
    async def test_healthy_echo(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect() is True
                assert client.state.connected
                assert client.health.echo_detected is True
                assert client.health.watchdog_mode == "echo"
                assert "ZQS00" in fake.sent_text()
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_echo_off_uses_query_watchdog(self):
        async with adapter("noecho") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect() is True
                assert client.health.echo_detected is False
                assert client.health.watchdog_mode == "query"
                await client.send_remote_command("menu")
                assert await _until(lambda: "MZQS00" in fake.sent_text())
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_wedged_adapter_is_never_connected(self):
        """An adapter that accepts TCP but passes no data is not 'connected'."""
        async with adapter("wedged") as fake:
            changes: list[bool] = []
            client = _client(fake.port)
            ok = await client.connect(on_connection_changed=changes.append)
            assert ok is False
            assert not client.state.connected
            assert changes == [False]
            assert client.health.consecutive_failures == 1
            assert "no response" in (client.health.last_disconnect_reason or "")
            # socket was aborted, freeing the adapter's slot
            assert await _until(lambda: fake.closed == 1)
            await client.disconnect()

    @pytest.mark.anyio
    async def test_refused_connection(self):
        async with adapter() as fake:
            port = fake.port
        client = _client(port)
        assert await client.connect() is False
        assert "connect failed" in (client.health.last_disconnect_reason or "")


class TestStaleConnection:
    @pytest.mark.anyio
    async def test_stale_read_loop_cannot_tear_down_new_connection(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect()
                old_gen = client._gen
                # force a reconnect to a new generation
                assert await client._open_connection()
                assert client._gen == old_gen + 1
                disconnects = client.health.disconnects

                # A stale reader from the old connection hits EOF late.
                stale = asyncio.StreamReader()
                stale.feed_data(b"garbage")
                stale.feed_eof()
                await client._read_loop(stale, old_gen)

                assert client.state.connected
                assert client.health.disconnects == disconnects
                assert client._reconnect_task is None
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_reconnect_after_peer_drop(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect()
                fake.writers[-1].transport.abort()  # adapter drops us
                assert await _until(lambda: not client.state.connected)
                assert await _until(lambda: client.state.connected, timeout=4.0)
                assert client.health.reconnects == 1
                assert client.health.disconnects == 1
                assert fake.connections == 2
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_backoff_keeps_growing_while_wedged(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect()
                fake.mode = "wedged"
                fake.writers[-1].transport.abort()
                assert await _until(
                    lambda: client.health.consecutive_failures >= 2, timeout=6.0
                )
                assert not client.state.connected
            finally:
                await client.disconnect()


class TestWatchdog:
    @pytest.mark.anyio
    async def test_silent_link_detected_after_command(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect()
                fake.mode = "wedged"  # link goes quiet but TCP stays up
                await client.send_remote_command("menu")
                assert await _until(lambda: not client.state.connected, timeout=1.5)
                assert "no response" in (client.health.last_disconnect_reason or "")
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_healthy_link_survives_commands(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect()
                for _ in range(3):
                    await client.send_remote_command("menu")
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.5)
                assert client.state.connected
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_power_commands_get_grace_period(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            try:
                assert await client.connect()
                fake.mode = "wedged"  # e.g. Lumagen busy booting
                await client.power_on()
                await client.send_remote_command("menu")
                await asyncio.sleep(0.6)
                assert client.state.connected
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_watchdog_off(self):
        async with adapter("echo") as fake:
            client = _client(fake.port, watchdog="off")
            try:
                assert await client.connect()
                assert client.health.watchdog_mode == "off"
                fake.mode = "wedged"
                await client.send_remote_command("menu")
                await asyncio.sleep(0.6)
                assert client.state.connected
            finally:
                await client.disconnect()

    @pytest.mark.anyio
    async def test_keepalive_detects_idle_dead_link(self):
        async with adapter("echo") as fake:
            client = _client(fake.port, keepalive_interval=0.2, watchdog="off")
            client._probe_timeout = 0.2
            try:
                assert await client.connect()
                fake.mode = "wedged"
                assert await _until(lambda: not client.state.connected, timeout=2.0)
                assert client.health.last_disconnect_reason == "keepalive timeout"
            finally:
                await client.disconnect()


class TestTeardown:
    @pytest.mark.anyio
    async def test_disconnect_leaves_no_tasks(self):
        async with adapter("echo") as fake:
            client = _client(fake.port)
            assert await client.connect()
            await client.send_remote_command("menu")
            await client.disconnect()
            for task in (
                client._read_task,
                client._keepalive_task,
                client._watchdog_task,
                client._reconnect_task,
            ):
                assert task is None or task.done()
            assert not client.state.connected
            assert await _until(lambda: fake.closed == 1)

    @pytest.mark.anyio
    async def test_send_raises_when_disconnected(self):
        client = LumagenClient("127.0.0.1", 1)
        with pytest.raises(LumagenConnectionError):
            await client.send_remote_command("menu")


class TestLineBuffer:
    @pytest.mark.anyio
    async def test_split_chunks_and_echo_prefix(self):
        client = LumagenClient("127.0.0.1", 1)
        client._running = True
        reader = asyncio.StreamReader()
        for chunk in (b"%ZQS0", b"2!S0", b"2,1\r", b"\n!I53,1\r\n"):
            reader.feed_data(chunk)
        reader.feed_eof()
        await client._read_loop(reader, client._gen)
        assert client.state.power is True
        assert client.state.game_mode is True
        assert client.health.last_data_received is not None
        assert [d for _, d, _ in client.traffic] == ["rx", "rx"]
        client._running = False
        if client._power_on_task:
            client._power_on_task.cancel()
