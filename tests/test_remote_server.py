"""Remote server skeleton — §R.4, Step 1.

Deliberately independent of Qt and of the player: the server must be testable
headless, and these tests exist to prove the lifecycle contract — starts,
answers, stops — without touching any player code path.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from remote.server import RemoteServer, available, lan_ip


@pytest.fixture()
def server():
    srv = RemoteServer(port=0)  # OS-assigned port, collision-proof for CI
    assert srv.start(), "server should start (aiohttp is installed in the venv)"
    yield srv
    srv.stop()


def test_aiohttp_available():
    assert available() is True


def test_health_endpoint(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/health", timeout=5) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
    assert body["status"] == "ok"
    assert body["app"] == "halcyon"
    assert isinstance(body["pid"], int)


def test_index_page_served(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
        html = resp.read().decode("utf-8")
    assert "Halcyon" in html


def test_ephemeral_port_is_real(server):
    assert 0 < server.port < 65536


def test_base_url_contains_port(server):
    assert f":{server.port}" in server.base_url


def test_stop_is_idempotent(server):
    server.stop()
    server.stop()  # must be a no-op, not a raise


def test_start_is_idempotent(server):
    assert server.start() is True
    assert server.start() is True


def test_lan_ip_shape():
    ip = lan_ip()
    assert isinstance(ip, str)
    if ip:  # offline boxes may yield "" — but never garbage
        assert len(ip.split(".")) == 4
