"""Single-instance IPC for shell/context-menu launches.

Windows Explorer starts a new process for every file association or context-menu
verb.  Halcyon should not open a second player window for ``Add to Queue``;
instead the second process sends the launch request to the already-running
instance and exits.  Qt's local sockets give us this without adding a pywin32
runtime dependency.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import QObject, QByteArray, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from core.launch import LaunchRequest

log = logging.getLogger(__name__)

SERVER_NAME = "Halcyon.Player.SingleInstance.v1"
IPC_TIMEOUT_MS = 1200
MAX_PAYLOAD_BYTES = 512 * 1024


def send_to_running_instance(
    request: LaunchRequest,
    *,
    server_name: str = SERVER_NAME,
    timeout_ms: int = IPC_TIMEOUT_MS,
) -> bool:
    """Send ``request`` to an already-running Halcyon instance if one exists.

    Returns ``True`` only after the payload was written.  A failure simply means
    this process should continue as the primary app instance.
    """
    socket = QLocalSocket()
    try:
        socket.connectToServer(server_name)
        if not socket.waitForConnected(timeout_ms):
            return False
        payload = json.dumps(request.to_payload(), ensure_ascii=False).encode("utf-8") + b"\n"
        socket.write(payload)
        if not socket.waitForBytesWritten(timeout_ms):
            return False
        socket.flush()
        socket.disconnectFromServer()
        return True
    except Exception:  # noqa: BLE001 - IPC failure must never block launch
        log.debug("could not forward launch request to running instance", exc_info=True)
        return False
    finally:
        try:
            socket.close()
        except Exception:
            pass


class SingleInstanceServer(QObject):
    """A tiny JSON-over-QLocalServer receiver owned by the primary instance."""

    requestReceived = Signal(object)

    def __init__(self, *, server_name: str = SERVER_NAME, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server_name = server_name
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._drain_pending)

    def listen(self) -> bool:
        if self._server.listen(self._server_name):
            log.debug("single-instance server listening as %s", self._server_name)
            return True

        # A crash can leave a stale local-socket name behind.  Remove it once;
        # if listening still fails, the app remains usable, just without IPC.
        log.debug("single-instance listen failed, removing stale server name")
        QLocalServer.removeServer(self._server_name)
        if self._server.listen(self._server_name):
            log.debug("single-instance server listening after stale cleanup")
            return True

        log.warning("single-instance IPC disabled: %s", self._server.errorString())
        return False

    def close(self) -> None:
        try:
            self._server.close()
            QLocalServer.removeServer(self._server_name)
        except Exception:
            pass

    def _drain_pending(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.readyRead.connect(lambda sock=socket: self._read_socket(sock))
            socket.disconnected.connect(socket.deleteLater)
            self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        if socket.bytesAvailable() <= 0 and socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            return
        data = bytes(socket.readAll())
        if not data:
            return
        if len(data) > MAX_PAYLOAD_BYTES:
            log.warning("single-instance payload too large; ignored")
            socket.disconnectFromServer()
            return
        try:
            payload: Any = json.loads(data.decode("utf-8").strip())
        except Exception:
            log.warning("single-instance payload was not valid JSON")
            socket.disconnectFromServer()
            return
        self.requestReceived.emit(payload)
        socket.disconnectFromServer()
