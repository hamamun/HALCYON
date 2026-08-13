"""The title-bar video-route badge — §V.7.

The badge answers one question at a glance: *is the video I am watching right
now going through Turbo or through Soft?* Everything here defends the property
that makes that answer worth trusting — **the badge reports the achieved route,
never the request**. A Turbo selection that fell back to Soft reads "S".

Three layers:

* the policy functions in ``core.video_mode`` (no Qt, no display);
* the controller properties QML binds to;
* the live title bar, because "there is a badge" is exactly the kind of claim
  a text search passes while the control is invisible or empty.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import video_mode as policy

ROOT = Path(__file__).resolve().parent.parent
TITLEBAR_QML = ROOT / "ui" / "shell" / "TitleBar.qml"
BADGE_QML = ROOT / "ui" / "components" / "VideoModeBadge.qml"


# ---------------------------------------------------------------------------
# The four tokens (§V.7)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("selected", "effective", "expected"),
    [
        ("auto", "turbo", "AT"),
        ("auto", "soft", "AS"),
        ("turbo", "turbo", "T"),
        ("soft", "soft", "S"),
    ],
)
def test_the_badge_has_exactly_four_tokens(selected, effective, expected):
    assert policy.badge(selected, effective) == expected


def test_a_turbo_selection_that_fell_back_reads_soft():
    """The whole point of the badge (§V.7).

    The user asked for Turbo; the media is audio-only, or the system cannot do
    it, or the attempt failed and the engine continued on Soft (§V.4). The
    badge must say "S". Claiming "T" while the CPU decodes would misreport the
    one fact the badge exists to report.
    """
    assert policy.badge("turbo", "soft") == "S"


def test_auto_that_landed_on_soft_still_discloses_auto():
    """"AS" rather than "S": Auto made this choice, not the user."""
    assert policy.badge("auto", "soft") == "AS"


def test_a_mode_that_cannot_use_turbo_drops_the_auto_prefix():
    """M3U shows a plain disabled "Soft" in Settings (§V.2), so a bare "S".

    An "A" there would advertise a decision Auto was never allowed to make.
    """
    assert policy.badge("auto", "soft", turbo_allowed=False) == "S"
    assert policy.badge("turbo", "soft", turbo_allowed=False) == "S"


def test_an_unknown_route_is_reported_as_soft():
    """Unknown means "not demonstrably Turbo", and Soft is the safe claim."""
    assert policy.badge("auto", "") == "AS"
    assert policy.badge("auto", None) == "AS"
    assert policy.badge("auto", "nonsense") == "AS"


# ---------------------------------------------------------------------------
# The tooltip carries the reason (§V.7)
# ---------------------------------------------------------------------------
def test_every_soft_tooltip_says_why_it_is_soft():
    """"Soft" alone invites "but I chose Turbo?". Each answer names its cause."""
    cases = [
        (dict(selected="turbo", effective="soft", has_video=False), "audio only"),
        (dict(selected="turbo", effective="soft", turbo_available=False),
         "not available on this system"),
        (dict(selected="turbo", effective="soft", pending=True),
         "applies when the next video starts"),
        (dict(selected="turbo", effective="soft"), "could not start"),
        (dict(selected="auto", effective="soft"), "not demanding"),
        (dict(selected="soft", effective="soft"), "selected in Settings"),
        (dict(selected="auto", effective="soft", turbo_allowed=False),
         "always uses Soft"),
        (dict(selected="turbo", effective="soft", mini_mode=True),
         "Mini Mode always uses Soft"),
    ]
    for kwargs, expected in cases:
        selected = kwargs.pop("selected")
        effective = kwargs.pop("effective")
        text = policy.describe(selected, effective, **kwargs)
        assert expected in text, f"{kwargs} -> {text!r}"
        assert text.startswith(("Soft", "Auto")), text


def test_the_audio_only_reason_outranks_a_failed_turbo_attempt():
    """Precedence, not preference: audio-only is why Turbo never ran at all."""
    text = policy.describe(
        "turbo", "soft", has_video=False, turbo_available=False
    )
    assert "audio only" in text
    assert "not available" not in text


def test_mini_mode_outranks_every_other_soft_reason():
    text = policy.describe("turbo", "soft", mini_mode=True, has_video=False)
    assert "Mini Mode" in text


def test_turbo_tooltips_name_the_hardware_path():
    assert "hardware" in policy.describe("turbo", "turbo")
    auto = policy.describe("auto", "turbo")
    assert auto.startswith("Auto") and "hardware" in auto


def test_a_running_turbo_route_is_never_explained_away():
    """Turbo is actually running, so no failure reason may leak into the text."""
    text = policy.describe(
        "auto", "turbo", has_video=False, turbo_available=False, mini_mode=True
    )
    assert "Turbo" in text
    for excuse in ("could not", "not available", "audio only", "Mini Mode"):
        assert excuse not in text


# ---------------------------------------------------------------------------
# The controller properties QML binds to
# ---------------------------------------------------------------------------
def _controller(qt_application, mode="local", selected="auto", route="soft"):
    """A controller assembled the way the other controller tests do it."""
    from PySide6.QtCore import QObject

    from core.app import AppController

    controller = AppController.__new__(AppController)
    QObject.__init__(controller)

    class _Engine:
        videoRoute = route
        turbo_ok = True

        def turbo_available(self):
            return self.turbo_ok

    controller._engine = _Engine()
    controller._active_mode = mode
    controller._video_mode = selected
    controller._mini_mode = False
    controller._video_mode_has_video = True
    return controller


def test_the_controller_badge_reports_the_engines_actual_route(qt_application):
    controller = _controller(qt_application, selected="turbo", route="soft")
    assert controller.videoModeBadge == "S", (
        "the engine is on Soft; the badge must not echo the Turbo selection"
    )

    controller._engine.videoRoute = "turbo"
    assert controller.videoModeBadge == "T"


def test_the_controller_badge_drops_the_prefix_in_m3u(qt_application):
    controller = _controller(qt_application, mode="m3u", selected="auto")
    assert controller.videoModeBadge == "S"


def test_the_controller_tooltip_reports_an_unsupported_system(qt_application):
    controller = _controller(qt_application, selected="turbo", route="soft")
    controller._engine.turbo_ok = False
    assert "not available on this system" in controller.videoModeTooltip


def test_a_broken_turbo_probe_never_breaks_the_tooltip(qt_application):
    """The badge is chrome; an engine that raises must not blank the title bar."""
    controller = _controller(qt_application, selected="turbo", route="soft")

    def _boom():
        raise RuntimeError("engine is mid-teardown")

    controller._engine.turbo_available = _boom
    assert controller.videoModeTooltip  # a sentence, not an exception


def test_the_badge_refreshes_when_the_route_settles(qt_application):
    """A late fallback must reach the title bar (§V.4).

    Without an emit after the route is applied the badge would keep showing
    the previous media's answer, which is precisely the lie this feature is
    supposed to prevent.
    """
    import core.app as app_module

    source = Path(app_module.__file__).read_text(encoding="utf-8")
    marker = "def _apply_video_mode_deferred"
    body = source[source.index(marker):]
    body = body[: body.index("\n    def ", 1)]
    assert "videoModeChanged.emit()" in body


# ---------------------------------------------------------------------------
# The live title bar
# ---------------------------------------------------------------------------
from tests.conftest import GUI_AVAILABLE  # noqa: E402

gui_only = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

#: QML trees built in a helper must outlive the helper's stack frame.
_KEEP_ALIVE: list = []


def _title_bar(mode, *, has_media, badge="AT", tooltip="Auto -> Turbo"):
    """The real TitleBar.qml, driven by property doubles."""
    from PySide6.QtCore import Property, QObject, QUrl
    from PySide6.QtQml import QQmlApplicationEngine

    class _App(QObject):
        @Property(str, constant=True)
        def videoModeBadge(self):
            return badge

        @Property(str, constant=True)
        def videoModeTooltip(self):
            return tooltip

    class _Player(QObject):
        @Property(float, constant=True)
        def duration(self):
            return 120.0 if has_media else 0.0

        @Property(str, constant=True)
        def currentMedia(self):
            return "/tmp/clip.mkv" if has_media else ""

    from core.app import ModeList

    qml_engine = QQmlApplicationEngine()
    qml_engine.addImportPath(str(ROOT))
    app_stub, player_stub, modes = _App(), _Player(), ModeList()
    ctx = qml_engine.rootContext()
    ctx.setContextProperty("App", app_stub)
    ctx.setContextProperty("Player", player_stub)
    ctx.setContextProperty("Metadata", None)
    ctx.setContextProperty("Modes", modes)

    qml_engine.loadData(
        f"""
        import QtQuick
        import Halcyon.Shell
        Window {{
            width: 900; height: 60
            TitleBar {{
                objectName: "titleBar"
                anchors.fill: parent
                activeMode: "{mode}"
            }}
        }}
        """.encode(),
        QUrl.fromLocalFile(str(ROOT / "inline.qml")),
    )
    roots = qml_engine.rootObjects()
    assert roots, "TitleBar.qml failed to load"
    window = roots[0]
    bar = window.findChild(QObject, "titleBar")
    # The engine and the stubs own the QML tree; without a reference on the
    # caller's side Python collects them and the bar is deleted underneath us.
    _KEEP_ALIVE.append((qml_engine, window, app_stub, player_stub, modes))
    return bar


def _badge_item(bar):
    from PySide6.QtCore import QObject

    for child in bar.findChildren(QObject):
        meta = child.metaObject()
        names = {
            meta.property(i).name() for i in range(meta.propertyCount())
        }
        if {"turbo", "tooltip"} <= names and child.property("text") is not None:
            return child
    return None


@gui_only
@pytest.mark.parametrize("mode", ["local", "m3u"])
def test_the_badge_shows_in_local_and_m3u_while_media_plays(gui_app, mode):
    bar = _title_bar(mode, has_media=True)
    assert bar.property("videoBadgeVisible") is True
    badge = _badge_item(bar)
    assert badge is not None, "the badge is missing from the title bar"
    assert badge.property("visible") is True
    assert badge.property("text") == "AT"


@gui_only
def test_the_badge_stays_out_of_web_mode(gui_app):
    """Web has no video route of its own, so the badge would be noise (§V.1)."""
    bar = _title_bar("web", has_media=True)
    assert bar.property("videoBadgeVisible") is False
    badge = _badge_item(bar)
    assert badge is None or badge.property("visible") is False


@gui_only
def test_the_badge_stays_hidden_until_there_is_media(gui_app):
    bar = _title_bar("local", has_media=False)
    assert bar.property("videoBadgeVisible") is False
    badge = _badge_item(bar)
    assert badge is None or badge.property("visible") is False


@gui_only
def test_an_empty_badge_collapses_instead_of_showing_an_empty_pill(gui_app):
    bar = _title_bar("local", has_media=True, badge="")
    badge = _badge_item(bar)
    assert badge is not None
    assert badge.property("visible") is False


@gui_only
def test_the_badge_tints_for_turbo_and_stays_quiet_for_soft(gui_app):
    """Soft is the ordinary, correct state — it must not read as a warning."""
    turbo = _badge_item(_title_bar("local", has_media=True, badge="AT"))
    soft = _badge_item(_title_bar("local", has_media=True, badge="AS"))
    assert turbo.property("turbo") is True
    assert soft.property("turbo") is False
    assert turbo.property("text") != soft.property("text")


@gui_only
def test_the_badge_carries_the_controllers_tooltip(gui_app):
    bar = _title_bar("local", has_media=True, tooltip="Auto \u2192 Soft; not demanding")
    badge = _badge_item(bar)
    assert "not demanding" in badge.property("tooltip")


# ---------------------------------------------------------------------------
# What the badge must not become
# ---------------------------------------------------------------------------
def test_the_badge_is_a_read_out_not_a_button():
    """It reports; it does not act (§V.7).

    Settings owns the setting. A clickable badge would be a second, hidden
    entry point to it, and a status glyph that moves the UI when brushed is a
    hazard next to the window buttons.
    """
    source = BADGE_QML.read_text(encoding="utf-8")
    for forbidden in ("onClicked", "MouseArea", "TapHandler", "showSettings"):
        assert forbidden not in source, (
            f"{forbidden} makes the badge interactive; it is a read-out"
        )


def test_the_badge_never_recomputes_the_route_in_qml():
    """One decision site (§V.1): core/video_mode.py, via the controller.

    QML deciding "turbo if X" locally is how the badge and the engine drift
    apart.
    """
    source = TITLEBAR_QML.read_text(encoding="utf-8")
    assert "videoModeBadge" in source
    assert "effectiveVideoMode" not in source, (
        "the title bar must render the controller's badge string, not derive "
        "its own from the route"
    )
