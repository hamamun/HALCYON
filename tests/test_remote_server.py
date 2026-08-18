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
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html


def test_pwa_manifest_and_icons_are_served(server):
    base = f"http://127.0.0.1:{server.port}"
    with urllib.request.urlopen(f"{base}/manifest.webmanifest", timeout=5) as resp:
        assert resp.headers.get_content_type() == "application/manifest+json"
        manifest = json.loads(resp.read().decode("utf-8"))

    assert manifest["name"] == "Halcyon Remote"
    assert manifest["short_name"] == "Halcyon"
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} >= {"192x192", "512x512"}
    assert any("maskable" in icon.get("purpose", "") for icon in manifest["icons"])

    with urllib.request.urlopen(f"{base}/static/icons/halcyon-192.png", timeout=5) as resp:
        assert resp.headers.get_content_type() == "image/png"
        assert resp.read(8) == b"\x89PNG\r\n\x1a\n"


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
