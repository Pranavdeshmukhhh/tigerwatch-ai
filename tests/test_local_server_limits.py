"""Actual socket-cap regression; no provider access or production credentials."""
import socket
import threading
from types import SimpleNamespace

import pytest

from tigerwatch.dashboard import BoundedDashboardServer, handler_for


def test_extra_connections_are_closed_without_starting_more_handlers():
    release, ready = threading.Event(), threading.Event()
    lock, active = threading.Lock(), []
    class Held(handler_for(SimpleNamespace(), "fixture-local-limit-key")):
        def handle(self):
            with lock:
                active.append(self)
                if len(active) == 2:
                    ready.set()
            release.wait(5)
    try:
        server = BoundedDashboardServer(("127.0.0.1", 0), Held, max_connections=2)
    except PermissionError:
        pytest.skip("Local socket binding unavailable in this execution environment")
    sockets = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for _ in range(2):
            sockets.append(socket.create_connection(server.server_address, timeout=2))
        assert ready.wait(2)
        extra = socket.create_connection(server.server_address, timeout=2)
        sockets.append(extra)
        try:
            assert extra.recv(1) == b""
        except ConnectionResetError:
            pass
        assert len(active) == 2
    finally:
        release.set()
        for client in sockets:
            client.close()
        server.shutdown()
        server.server_close()
