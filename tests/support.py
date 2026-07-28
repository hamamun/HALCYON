"""Shared test scaffolding.

``AppController`` is expensive to build for real — it wants an engine, a
library, metadata, lyrics and an equalizer — so several test modules construct
one by hand with fakes. They each did that inline, which meant every new piece
of controller state broke *all* of them at once, in a way that looks like a
product bug and is not.

One builder, here. Adding state to the controller is now a one-line edit.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.app import AppController


def build_controller(engine, *, playlist=None, settings=None, **services):
    """A real ``AppController`` wired to fakes.

    ``QObject.__init__`` must run — skipping it via ``__new__`` alone leaves the
    signals unusable ("Signal source has been deleted"). So the base class is
    initialised and only the collaborators are stubbed.

    Keeps the field list in step with ``AppController.__init__`` by hand,
    deliberately: mirroring it automatically would make a test pass against
    state the real constructor never sets.
    """
    controller = AppController.__new__(AppController)
    AppController.__bases__[0].__init__(controller)  # QObject.__init__

    controller._engine = engine
    controller._settings = settings
    controller._library = services.get("library")
    # These three are only ever called, never asserted on, in the tests that use
    # this builder — so a MagicMock is the right default. Passing None instead
    # made any test that reached _on_media_changed fail on an AttributeError
    # that says nothing about the behaviour under test.
    controller._metadata = services.get("metadata", MagicMock())
    controller._lyrics = services.get("lyrics", MagicMock())
    controller._equalizer = services.get("equalizer", MagicMock())

    controller._active_mode = "local"
    controller._contexts = {"local": playlist} if playlist is not None else {}

    controller._subtitle_delay = 0
    controller._audio_tracks = []
    controller._subtitle_tracks = []
    controller._current_audio = -1
    controller._current_subtitle = -1
    controller._resume_path = ""
    controller._resume_ms = 0
    controller._audio_restored = False
    controller._subtitle_restored = False
    return controller


def null_library():
    """A Library stand-in that remembers nothing and is happy to be asked."""
    library = MagicMock()
    library.remembered_audio_track.return_value = ""
    library.remembered_subtitle_track.return_value = ""
    library.resume_position.return_value = 0
    return library
