"""Remote API integration — server ↔ bridge ↔ endpoints (§R.4).

Uses the same fake controller/engine as the bridge tests plus a real
RemoteServer on an ephemeral port, exercising the routes a phone hits.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from PySide6.QtCore import QCoreApplication, QObject

from remote.bridge import RemoteBridge
from remote.server import RemoteServer


class FakeEngine(QObject):
    def __init__(self):
        super().__init__()
        self._playing = False
        self._volume = 80
        self._time = 0

    def isPlaying(self): return self._playing
    def time(self): return self._time
    def duration(self): return 120000
    def position(self): return 0.0
    def volume(self): return self._volume
    def muted(self): return False
    def rate(self): return 1.0
    def seek(self, ms): self._time = ms


class FakeController(QObject):
    def __init__(self):
        super().__init__()
        self.mode = "local"
        self.calls = []

    def activeMode(self): return self.mode
    def setActiveMode(self, m): self.mode = m
    def playPause(self): self.calls.append("playPause")
    def play(self): self.calls.append("play")
    def pause(self): self.calls.append("pause")
    def stop(self): self.calls.append("stop")
    def next(self): self.calls.append("next")
    def previous(self): self.calls.append("previous")
    def currentPlaybackLabel(self): return ""
    @property
    def currentFileStem(self): return ""
    def audioTracks(self): return []
    def subtitleTracks(self): return []
    def currentAudioId(self): return -1
    def currentSubtitleId(self): return -1
    def subtitleDelayMs(self): return 0


def _get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read()


def _post(url, body, timeout=10):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


@pytest.fixture()
def server(tmp_path):
    bridge = RemoteBridge(controller=FakeController(), engine=FakeEngine(), settings=None)
    srv = RemoteServer(bridge=bridge, port=0)
    assert srv.start()
    # Give the bridge a full snapshot to serve.
    bridge.publish_now()
    try:
        yield srv, bridge, tmp_path
    finally:
        srv.stop()
        bridge._timer.stop()


def test_health(server):
    srv, _, _ = server
    status, body = _get(f"http://127.0.0.1:{srv.port}/health")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["status"] == "ok" and data["app"] == "halcyon"


def test_index_serves_phone_ui(server):
    srv, _, _ = server
    status, body = _get(f"http://127.0.0.1:{srv.port}/")
    assert status == 200
    html = body.decode("utf-8")
    assert "HALCYON" in html and "app.js" in html


def test_status_snapshot(server):
    srv, bridge, _ = server
    status, body = _get(f"http://127.0.0.1:{srv.port}/api/status")
    assert status == 200
    snap = json.loads(body.decode("utf-8"))
    assert snap["app"] == "halcyon"
    assert snap["connected"] is True
    assert snap["mode"] == "local"


def test_cmd_endpoint_queues_command(server):
    srv, bridge, _ = server
    status, data = _post(f"http://127.0.0.1:{srv.port}/api/cmd", {"action": "playPause", "payload": {}})
    assert status == 200 and data["ok"] is True
    # Drain the Qt event queue so the queued signal fires.
    app = QCoreApplication.instance()
    end = time.time() + 0.5
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    assert bridge._controller.calls == ["playPause"]


def test_cmd_rejects_missing_action(server):
    srv, _, _ = server
    try:
        _post(f"http://127.0.0.1:{srv.port}/api/cmd", {"payload": {}})
        assert False, "expected 400"
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def test_drives_endpoint(server):
    srv, _, _ = server
    status, body = _get(f"http://127.0.0.1:{srv.port}/api/drives")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert isinstance(data["drives"], list) and data["drives"]


def test_browse_endpoint(server, tmp_path):
    srv, _, _ = server
    (tmp_path / "clip.mp4").write_bytes(b"x")
    url = f"http://127.0.0.1:{srv.port}/api/browse?path={urllib.parse.quote(str(tmp_path).replace(chr(92), '/'))}"
    status, body = _get(url)
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    names = [f["name"] for f in data["files"]]
    assert "clip.mp4" in names


def test_browse_bad_path(server):
    srv, _, _ = server
    url = f"http://127.0.0.1:{srv.port}/api/browse?path=/does/not/exist/xyz"
    try:
        _get(url)
        assert False, "expected 400"
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def test_qr_endpoint(server):
    srv, _, _ = server
    try:
        status, body = _get(f"http://127.0.0.1:{srv.port}/qr.png")
        if status == 200:
            assert body[:8] == b"\x89PNG\r\n\x1a\n"
        else:
            assert status == 503  # qrcode not installed — still a clean answer
    except urllib.error.HTTPError as exc:
        assert exc.code == 503


def test_sse_pushes_snapshot(server):
    srv, bridge, _ = server
    bridge.publish_now()  # bump the version so the stream has data
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/api/events", timeout=10) as resp:
        first = resp.readline()
        assert first.startswith(b"data: ")
        payload = json.loads(first[6:].decode("utf-8"))
        assert payload["app"] == "halcyon"
