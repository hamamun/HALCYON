"""``VideoSurface`` — frames from the ring into the Qt scene graph (§0.3).

The whole point: video becomes a **normal QML Item**. Once it is a scene-graph
node, glass panels, blur, rounded corners, the OSD and animated overlays all
composite over it correctly and permanently — the class of bug where a native
video window punches a hole through your UI simply cannot occur.

Two pixel paths
---------------
``i420``  The Y plane and the interleaved-by-stacking U/V planes are uploaded as
          single-channel (``QImage.Format_Grayscale8``) textures, and a QML
          ``ShaderEffect`` does the BT.709 matrix multiply. 1.5 bytes/px.
``rv32``  One packed RGB texture, no shader. 4 bytes/px. Fallback for hardware
          or drivers that dislike the shader path (§9, "Shader fails on old
          iGPU"). **Important:** libVLC's RV32 is host-byte-order RGB — on
          little-endian Windows/x86 the bytes are R, G, B, X, *not* BGRA. The
          QImage must therefore be :pyattr:`~QImage.Format.Format_RGBX8888`;
          creating it as ``Format_RGB32`` (which reads B, G, R) is what swaps
          red and blue on every frame. See :meth:`VideoSurface._update_packed`.

**Implementation note — why plane *items* rather than a QSGMaterial.**
The plan (§0.4) describes a custom ``QSGMaterialShader`` binding three samplers.
PySide6 does not expose ``QSGMaterialShader::updateSampledImage``, so a custom
multi-sampler material cannot be built from Python. The equivalent, using only
exposed API, is what this module does instead:

* three ``PlaneSurface`` items, each a texture **provider**, one per plane;
* a QML ``ShaderEffect`` samples them as ``y``, ``u``, ``v`` properties.

Same number of uploads (three small ones instead of one large — 1.5 bytes/px
total either way), same shader maths, same zero CPU conversion. The difference is
invisible at runtime and keeps us on supported API.

Threading
---------
``on_frame`` is invoked from VLC's decoder thread and does exactly one thing:
``QMetaObject.invokeMethod(..., QueuedConnection)`` to request an update on the
GUI thread. All texture work happens inside ``updatePaintNode`` on the render
thread, which is the only place it is legal.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Property, QObject, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import (
    QQuickItem,
    QQuickWindow,
    QSGSimpleTextureNode,
    QSGTexture,
    QSGTextureProvider,
)

from engine.video_out import Chroma, FrameFormat, VideoOutput

log = logging.getLogger(__name__)

QML_IMPORT_NAME = "Halcyon.Engine"
QML_IMPORT_MAJOR_VERSION = 1


class _PlaneTextureProvider(QSGTextureProvider):
    """Hands one plane's texture to whatever QML samples it."""

    def __init__(self) -> None:
        super().__init__()
        self._texture: QSGTexture | None = None

    def texture(self) -> QSGTexture | None:  # noqa: D102 - Qt override
        return self._texture

    def set_texture(self, texture: QSGTexture | None) -> None:
        self._texture = texture
        self.textureChanged.emit()


@QmlElement
class PlaneSurface(QQuickItem):
    """A single video plane, exposed to QML as a texture provider.

    Invisible by itself — a ``ShaderEffect`` samples it. Three of these plus the
    YUV shader make a picture; one of these alone (in RV32 mode) is the picture.
    """

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        self._provider: _PlaneTextureProvider | None = None
        self._texture: QSGTexture | None = None
        self._image: QImage | None = None
        self._pending: QImage | None = None
        self._dirty = False

    # -- texture provider plumbing ------------------------------------------
    def isTextureProvider(self) -> bool:  # noqa: N802 - Qt override
        return True

    def textureProvider(self) -> QSGTextureProvider:  # noqa: N802 - Qt override
        if self._provider is None:
            self._provider = _PlaneTextureProvider()
        return self._provider

    # -- content ------------------------------------------------------------
    def set_image(self, image: QImage | None) -> None:
        """Stage a new QImage *view* for the next commit.

        Called from :meth:`VideoSurface.updatePaintNode`, i.e. during the
        render-thread sync phase while the GUI thread is blocked. Scheduling
        an update from inside ``updatePaintNode`` is explicitly allowed by Qt,
        which is why this is safe here and was *not* safe from the decoder
        thread.
        """
        self._pending = image
        self._dirty = True
        self.update()

    def commit_texture(self, window) -> None:
        """Build the QSGTexture from the staged image and publish it.

        Runs on the **render thread**, while the owning :class:`VideoSurface`
        holds the ring pin — so the one DMA upload reads stable pixels and no
        reader/writer race is possible.

        The plane item itself is invisible (only the QML ``ShaderEffect``
        samples it), so its own ``updatePaintNode`` is never invoked by Qt.
        Committing here, from the surface's ``updatePaintNode``, is therefore
        the *only* path by which a plane ever receives a texture. Leaving it
        to ``updatePaintNode`` left three texture providers holding ``None``,
        which is exactly why the I420 path rendered black whenever the shader
        was present.
        """
        image = self._pending
        if image is None or image.isNull():
            texture = None
        else:
            # One DMA upload. NoOwnership: the pixels belong to the ring, and
            # the ring outlives this texture.
            texture = window.createTextureFromImage(
                image, QQuickWindow.CreateTextureOption.TextureIsOpaque
            )
            self._image = image  # keep the view alive while Qt reads it
        self._texture = texture
        self._dirty = False
        # Ensure the provider exists so the ShaderEffect always has a texture to
        # sample, even on the first frame before it has queried us. Safe on the
        # render thread (we are inside the surface's updatePaintNode).
        self.textureProvider().set_texture(texture)

    def updatePaintNode(self, node, _data):  # noqa: N802 - Qt override
        window = self.window()
        if window is None:
            return None

        if self._dirty:
            self.commit_texture(window)

        # Planes are invisible in normal operation, so this is only reached if
        # a plane is made visible for debugging; it then draws its own texture
        # as a flat rectangle.
        if self._texture is None:
            return None

        tex_node = node if isinstance(node, QSGSimpleTextureNode) else QSGSimpleTextureNode()
        tex_node.setTexture(self._texture)
        tex_node.setOwnsTexture(False)
        tex_node.setFiltering(QSGTexture.Filtering.Linear)
        tex_node.setRect(QRectF(0, 0, max(self.width(), 1), max(self.height(), 1)))
        return tex_node

    def releaseResources(self) -> None:  # noqa: N802 - Qt override
        self._texture = None
        self._image = None
        if self._provider is not None:
            try:
                self._provider.set_texture(None)
            except RuntimeError:
                pass


@QmlElement
class VideoSurface(QQuickItem):
    """The video item. Put it in a QML scene; draw anything you like on top.

    QML surface:

        VideoSurface {
            anchors.fill: parent
            source: player.videoOutput          // set from Python or a context prop
            fillMode: VideoSurface.PreserveAspectFit
        }

    Exposes ``contentRect`` (the letterboxed picture rectangle in item
    coordinates) so overlays — subtitle safe area, OSD, PiP crop — can align to
    the picture rather than the item.
    """

    frameFormatChanged = Signal()
    hasVideoChanged = Signal()
    contentRectChanged = Signal()
    fillModeChanged = Signal()
    frameRendered = Signal()

    #: Internal, decoder-thread -> GUI-thread hops. Emitting a Qt signal is
    #: thread-safe; the queued connections below marshal the delivery.
    frameArrived = Signal()
    formatArrived = Signal()
    videoStopped = Signal()

    class FillMode:
        Stretch = 0
        PreserveAspectFit = 1
        PreserveAspectCrop = 2

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        self._vout: VideoOutput | None = None
        self._fmt: FrameFormat | None = None
        self._fill_mode = self.FillMode.PreserveAspectFit
        self._has_video = False
        self._content_rect = QRectF()
        self._last_serial = -1

        # RV32 path: this item draws the picture itself.
        self._texture: QSGTexture | None = None
        self._image: QImage | None = None
        self._image_buf: object | None = None  # keep the ring view alive for upload

        # I420 path: three child plane items, sampled by a ShaderEffect in QML.
        self._plane_y: PlaneSurface | None = None
        self._plane_u: PlaneSurface | None = None
        self._plane_v: PlaneSurface | None = None
        self._plane_bufs: tuple = ()  # one ctypes view per plane, kept until upload lands

        self.widthChanged.connect(self._recompute_content_rect)
        self.heightChanged.connect(self._recompute_content_rect)

        # Queued on purpose: the emitting thread is VLC's, the receiving slot
        # must run on the GUI thread. Without the explicit type Qt would use
        # AutoConnection, which is queued here anyway — being explicit
        # documents the intent and survives a future re-parenting.
        self.frameArrived.connect(
            self._on_frame_gui, Qt.ConnectionType.QueuedConnection
        )
        self.formatArrived.connect(
            self._on_format_gui, Qt.ConnectionType.QueuedConnection
        )
        self.videoStopped.connect(
            self._on_video_stopped_gui, Qt.ConnectionType.QueuedConnection
        )

    # ------------------------------------------------------------ binding ---
    def bind(self, vout: VideoOutput) -> None:
        """Attach to a video output. Safe to call once; PiP calls it on its own
        surface against the *same* VideoOutput (§P2.5)."""
        if self._vout is vout:
            return
        if self._vout is not None:
            self._vout.remove_reader()
        self._vout = vout
        vout.add_reader()
        vout.frame_ready = self._on_frame_threadsafe
        vout.format_changed = self._on_format_threadsafe
        vout.video_stopped = self._on_video_stopped_threadsafe
        self._ensure_planes()

    def unbind(self) -> None:
        if self._vout is not None:
            self._vout.remove_reader()
            self._vout = None
        self._set_has_video(False)

    @Slot(QObject)
    def setSource(self, source: QObject) -> None:  # noqa: N802 - QML-facing
        """QML-friendly binding: pass anything exposing ``.video_output``."""
        vout = getattr(source, "video_output", None)
        if isinstance(vout, VideoOutput):
            self.bind(vout)

    # ------------------------------------------------ thread entry points ---
    # These two run on VLC's **decoder thread**. Neither may touch Qt state.
    #
    # ``QQuickItem.update()`` is *not* thread-safe, contrary to what the old
    # code assumed. Calling it from the decoder thread made Qt log
    #
    #     Updates can only be scheduled from GUI thread or from
    #     QQuickItem::updatePaintNode()
    #
    # and then drop the request — so no repaint was ever scheduled and the
    # stage stayed black even though frames were decoding correctly. The fix
    # is the hop the module docstring always described: emit a signal that is
    # delivered to the GUI thread, and call update() there.
    def _on_frame_threadsafe(self) -> None:
        self.frameArrived.emit()

    def _on_format_threadsafe(self, fmt: FrameFormat) -> None:
        self._fmt = fmt
        self.formatArrived.emit()

    @Slot()
    def _on_frame_gui(self) -> None:
        """GUI thread. Safe to schedule a repaint from here."""
        self.update()

    def _on_video_stopped_threadsafe(self) -> None:
        self.videoStopped.emit()

    @Slot()
    def _on_format_gui(self) -> None:
        self._recompute_content_rect()
        self.frameFormatChanged.emit()
        self.update()

    @Slot()
    def _on_video_stopped_gui(self) -> None:
        """The stream has no more video. Drop back to the idle state.

        Without this ``hasVideo`` latched true for the rest of the session, so
        after one video the audio-only Now Playing card never appeared again.
        """
        self._fmt = None
        self._last_serial = -1
        self._texture = None
        self._image = None
        self._image_buf = None
        self._plane_bufs = ()
        self._set_has_video(False)
        self.frameFormatChanged.emit()
        self.update()

    # ------------------------------------------------------------ layout ---
    def _recompute_content_rect(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        fmt = self._fmt
        if fmt is None or self._fill_mode == self.FillMode.Stretch:
            rect = QRectF(0, 0, w, h)
        else:
            item_aspect = w / h
            video_aspect = fmt.aspect
            crop = self._fill_mode == self.FillMode.PreserveAspectCrop
            wider = video_aspect > item_aspect
            if wider != crop:
                # letterbox: full width, bars top and bottom
                ch = w / video_aspect
                rect = QRectF(0, (h - ch) / 2.0, w, ch)
            else:
                # pillarbox: full height, bars left and right
                cw = h * video_aspect
                rect = QRectF((w - cw) / 2.0, 0, cw, h)
        if rect != self._content_rect:
            self._content_rect = rect
            self._layout_planes()
            self.contentRectChanged.emit()

    def _ensure_planes(self) -> None:
        if self._plane_y is not None:
            return
        self._plane_y = PlaneSurface(self)
        self._plane_u = PlaneSurface(self)
        self._plane_v = PlaneSurface(self)
        for p in (self._plane_y, self._plane_u, self._plane_v):
            p.setVisible(False)  # sampled as textures, never drawn directly
        self._layout_planes()

    def _layout_planes(self) -> None:
        for p in (self._plane_y, self._plane_u, self._plane_v):
            if p is not None:
                p.setWidth(max(self.width(), 1))
                p.setHeight(max(self.height(), 1))

    def _set_has_video(self, value: bool) -> None:
        if self._has_video != value:
            self._has_video = value
            self.hasVideoChanged.emit()

    # ------------------------------------------------------------- paint ---
    def updatePaintNode(self, node, _data):  # noqa: N802 - Qt override
        vout = self._vout
        window = self.window()
        if vout is None or window is None:
            return node

        claim = vout.ring.acquire_read()
        if claim is None:
            return node
        try:
            serial, address, fmt = claim
            if serial == self._last_serial:
                return node
            self._last_serial = serial
            if self._fmt is None or self._fmt != fmt:
                self._fmt = fmt
                self._recompute_content_rect()

            if fmt.is_planar:
                node = self._update_planar(window, address, fmt, node)
            else:
                node = self._update_packed(window, address, fmt, node)
        finally:
            vout.ring.release_read()

        self._set_has_video(True)
        self.frameRendered.emit()
        return node

    def _plane_view(self, address: int, offset: int, pitch: int, lines: int,
                    width: int, height: int) -> tuple[QImage, object]:
        """A QImage that *views* ring memory — no copy, no ownership.

        ``pitch`` is honoured as bytesPerLine so padded strides do not shear the
        picture; the visible ``width``/``height`` crop off the alignment padding.

        Returns ``(image, buffer)``; the caller must keep ``buffer`` reachable
        for as long as Qt might still read from the image (until the texture
        upload completes). The pixels themselves live in the ring and are never
        freed here.
        """
        import ctypes

        size = pitch * lines
        buf = (ctypes.c_ubyte * size).from_address(address + offset)
        image = QImage(
            memoryview(buf), width, height, pitch, QImage.Format.Format_Grayscale8
        )
        return image, buf

    def _update_planar(self, window, address: int, fmt: FrameFormat, node):
        self._ensure_planes()
        cw, ch = (fmt.width + 1) // 2, (fmt.height + 1) // 2
        y_img, y_buf = self._plane_view(
            address, 0, fmt.y_pitch, fmt.y_lines, fmt.width, fmt.height
        )
        u_img, u_buf = self._plane_view(
            address, fmt.y_size, fmt.uv_pitch, fmt.uv_lines, cw, ch
        )
        v_img, v_buf = self._plane_view(
            address, fmt.y_size + fmt.uv_size, fmt.uv_pitch, fmt.uv_lines, cw, ch
        )
        # Commit every plane *here*, while the ring pin held by updatePaintNode
        # keeps the slot stable. The plane items are invisible, so deferring
        # their texture build to their own updatePaintNode (as the old code did)
        # never ran — the providers never received a texture and the ShaderEffect
        # sampled nothing, i.e. black video on the I420 path.
        self._plane_y.set_image(y_img)
        self._plane_u.set_image(u_img)
        self._plane_v.set_image(v_img)
        for plane in (self._plane_y, self._plane_u, self._plane_v):
            plane.commit_texture(window)
        # Hold the ctypes wrappers until the next frame. The textures are already
        # uploaded, but this is cheap insurance against any RHI that defers its
        # GPU read past this sync phase.
        self._plane_bufs = (y_buf, u_buf, v_buf)
        return node

    def _update_packed(self, window, address: int, fmt: FrameFormat, node):
        import ctypes

        size = fmt.y_pitch * fmt.y_lines
        buf = (ctypes.c_ubyte * size).from_address(address)
        # libVLC's RV32 is packed RGB in host byte order. On little-endian x86
        # the bytes therefore land as R, G, B, X — NOT B, G, R, A. The old code
        # created this QImage as Format_RGB32, which Qt reads as B, G, R, and so
        # every frame rendered with red and blue swapped. Format_RGBX8888 is a
        # fixed byte order of R, G, B, X regardless of CPU endianness, which is
        # exactly what VLC writes. Do not "simplify" this back to RGB32.
        image = QImage(
            memoryview(buf),
            fmt.width,
            fmt.height,
            fmt.y_pitch,
            QImage.Format.Format_RGBX8888,
        )
        self._texture = window.createTextureFromImage(
            image, QQuickWindow.CreateTextureOption.TextureIsOpaque
        )
        self._image = image
        self._image_buf = buf  # keep the ring view alive until the upload lands
        tex_node = node if isinstance(node, QSGSimpleTextureNode) else QSGSimpleTextureNode()
        tex_node.setTexture(self._texture)
        tex_node.setOwnsTexture(False)
        tex_node.setFiltering(QSGTexture.Filtering.Linear)
        tex_node.setRect(self._content_rect)
        return tex_node

    def releaseResources(self) -> None:  # noqa: N802 - Qt override
        self._texture = None
        self._image = None
        self._image_buf = None
        self._plane_bufs = ()

    # ---------------------------------------------------------- properties ---
    @Property(bool, notify=hasVideoChanged)
    def hasVideo(self) -> bool:  # noqa: N802 - QML-facing
        return self._has_video

    @Property(QRectF, notify=contentRectChanged)
    def contentRect(self) -> QRectF:  # noqa: N802 - QML-facing
        """The picture rectangle inside this item — overlays anchor to this."""
        return self._content_rect

    @Property(QSize, notify=frameFormatChanged)
    def frameSize(self) -> QSize:  # noqa: N802 - QML-facing
        return QSize(self._fmt.width, self._fmt.height) if self._fmt else QSize()

    @Property(bool, notify=frameFormatChanged)
    def isPlanar(self) -> bool:  # noqa: N802 - QML-facing
        """True when the YUV shader path is in use, False for the RV32 fallback."""
        return bool(self._fmt and self._fmt.is_planar)

    @Property(QQuickItem, notify=frameFormatChanged)
    def planeY(self) -> QQuickItem | None:  # noqa: N802 - QML-facing
        self._ensure_planes()
        return self._plane_y

    @Property(QQuickItem, notify=frameFormatChanged)
    def planeU(self) -> QQuickItem | None:  # noqa: N802 - QML-facing
        self._ensure_planes()
        return self._plane_u

    @Property(QQuickItem, notify=frameFormatChanged)
    def planeV(self) -> QQuickItem | None:  # noqa: N802 - QML-facing
        self._ensure_planes()
        return self._plane_v

    def _get_fill_mode(self) -> int:
        return self._fill_mode

    def _set_fill_mode(self, mode: int) -> None:
        if mode != self._fill_mode:
            self._fill_mode = mode
            self._recompute_content_rect()
            self.fillModeChanged.emit()

    fillMode = Property(int, _get_fill_mode, _set_fill_mode, notify=fillModeChanged)
