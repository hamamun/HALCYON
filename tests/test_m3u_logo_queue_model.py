"""The logo queue's algorithm, exercised where QML cannot be run.

What this is
------------
``M3UPanel.qml`` throttles channel-logo downloads with a small queue: at most
six requests in flight, rows outside the open group ask for nothing, and a
finished request hands its slot on without dropping the picture it fetched.

That queue is a dozen lines of JavaScript inside a ``.qml`` file, and running
QML needs a GPU-capable Qt Quick environment that CI does not have. So this
file is a **faithful transliteration** of those functions, driven through the
scenarios that actually happen in the panel: a playlist opening, a group being
switched, rows being scrolled away mid-request, and a panel being torn down.

What it does and does not prove
-------------------------------
It proves the *algorithm* holds its invariants — the cap is never exceeded,
slots are never leaked or double-counted, and the queue self-cleans. It cannot
prove the QML *wiring* (that ``wanted`` is bound to the right thing, or that
``Image.onStatusChanged`` calls ``done``); that part is held by review and
``qmllint``.

**If you change the queue in M3UPanel.qml, change it here too.** The two are
kept deliberately line-for-line similar so a divergence is easy to spot.
"""

from __future__ import annotations

import pytest


class Slot:
    """One delegate's logo cell: the three properties the queue touches."""

    def __init__(self, wanted: str = "") -> None:
        self.wanted = wanted
        self.granted = ""
        self.holds_slot = False
        #: Every value this cell handed to its Image, in order. A request is
        #: started by a non-empty entry and aborted by the empty one after it.
        self.history: list[str] = []

    def _set_granted(self, value: str) -> None:
        if value != self.granted:
            self.granted = value
            self.history.append(value)

    @property
    def requests_started(self) -> int:
        return len([h for h in self.history if h])


class LogoQueue:
    """Transliteration of the ``logoQueue`` QtObject in M3UPanel.qml."""

    max_active = 6

    def __init__(self) -> None:
        self.active_count = 0
        self.pending: list[Slot] = []

    def restart(self, slot: Slot | None) -> None:
        if slot is None:
            return
        if len(slot.wanted) == 0:
            self.withdraw(slot)
            return
        if slot.granted == slot.wanted:
            return
        if slot in self.pending:
            return
        self.withdraw(slot)
        if self.active_count < self.max_active:
            self.grant(slot)
        else:
            self.pending.append(slot)

    def grant(self, slot: Slot | None) -> None:
        if slot is None or slot.holds_slot:
            return
        self.active_count += 1
        slot.holds_slot = True
        slot._set_granted(slot.wanted)

    def done(self, slot: Slot | None) -> None:
        if slot is None or not slot.holds_slot:
            return
        slot.holds_slot = False
        self.active_count = max(0, self.active_count - 1)
        self.pump()

    def withdraw(self, slot: Slot | None) -> None:
        if slot is None:
            return
        if slot in self.pending:
            self.pending.remove(slot)
        slot._set_granted("")
        self.done(slot)

    def pump(self) -> None:
        while self.active_count < self.max_active and self.pending:
            nxt = self.pending.pop(0)
            if nxt is not None and len(nxt.wanted) > 0:
                self.grant(nxt)

    # -- the panel side, for readability in the tests ----------------------
    def finish(self, slot: Slot) -> None:
        """What ``Image.onStatusChanged`` does on Ready or Error.

        Both outcomes free the slot. On Error the panel additionally reports
        the URL to the mode (``ctx.noteLogoFailed``), which is covered by
        ``test_m3u_logo_cache.py``.
        """
        self.done(slot)


@pytest.fixture()
def queue() -> LogoQueue:
    return LogoQueue()


def _open_group(queue: LogoQueue, count: int, prefix: str = "u") -> list[Slot]:
    """A group expanding: `count` rows appear, each wanting a logo."""
    slots = [Slot(f"https://cdn/{prefix}{i}.png") for i in range(count)]
    for slot in slots:
        queue.restart(slot)      # onWantedChanged
        queue.restart(slot)      # Component.onCompleted — both really fire
    return slots


# ------------------------------------------------------------------- cap --
def test_a_thousand_rows_never_exceed_six_requests_at_once(queue) -> None:
    """The whole point: this is what "excessive load detected" was."""
    slots = _open_group(queue, 1000)

    assert queue.active_count == 6
    assert sum(1 for s in slots if s.requests_started) == 6
    assert len(queue.pending) == 994


def test_finishing_one_request_starts_exactly_one_more(queue) -> None:
    slots = _open_group(queue, 20)
    first = next(s for s in slots if s.holds_slot)

    queue.finish(first)

    assert queue.active_count == 6, "the slot was handed on, not lost"
    assert sum(1 for s in slots if s.requests_started) == 7


def test_every_row_is_eventually_served(queue) -> None:
    slots = _open_group(queue, 50)

    # Drain: finish whatever is in flight until nothing is left.
    guard = 0
    while queue.active_count and guard < 1000:
        guard += 1
        queue.finish(next(s for s in slots if s.holds_slot))

    assert all(s.requests_started == 1 for s in slots), "no row was starved"
    assert queue.pending == []
    assert queue.active_count == 0, "no slot leaked"


# ------------------------------------------------------------- no churn --
def test_a_row_is_not_restarted_by_its_own_second_signal(queue) -> None:
    """onWantedChanged and Component.onCompleted both fire while a row builds.

    The first version of this queue withdrew unconditionally, so the second
    call aborted the request the first had just started — precisely the churn
    the queue exists to prevent.
    """
    slot = Slot("https://cdn/a.png")

    queue.restart(slot)
    queue.restart(slot)
    queue.restart(slot)

    assert slot.requests_started == 1
    assert slot.history == ["https://cdn/a.png"]
    assert queue.active_count == 1


def test_a_finished_picture_is_kept_when_its_slot_is_handed_on(queue) -> None:
    slot = Slot("https://cdn/a.png")
    queue.restart(slot)
    queue.finish(slot)

    assert slot.granted == "https://cdn/a.png", (
        "clearing the source on completion would unload the picture and make "
        "the row re-fetch it"
    )
    assert not slot.holds_slot
    assert queue.active_count == 0


# --------------------------------------------------- collapse and switch --
def test_collapsing_a_group_cancels_its_requests_and_frees_the_slots(queue) -> None:
    slots = _open_group(queue, 10)
    assert queue.active_count == 6

    for slot in slots:               # the group collapses: nothing is wanted
        slot.wanted = ""
        queue.restart(slot)

    assert queue.active_count == 0
    assert queue.pending == []
    assert all(s.granted == "" for s in slots)


def test_switching_groups_serves_the_new_one(queue) -> None:
    old = _open_group(queue, 10, prefix="old")
    for slot in old:
        slot.wanted = ""
        queue.restart(slot)

    new = _open_group(queue, 10, prefix="new")

    assert queue.active_count == 6
    # The old group's requests were started and then aborted; none is still
    # holding a slot, and none is still pointing its Image at a URL.
    assert all(s.granted == "" and not s.holds_slot for s in old)
    assert all(s.history[-1] == "" for s in old if s.history)
    assert sum(1 for s in new if s.requests_started) == 6


def test_a_row_that_changes_its_mind_mid_flight(queue) -> None:
    slot = Slot("https://cdn/a.png")
    queue.restart(slot)
    slot.wanted = "https://cdn/b.png"
    queue.restart(slot)

    assert slot.granted == "https://cdn/b.png"
    assert slot.history == ["https://cdn/a.png", "", "https://cdn/b.png"]
    assert queue.active_count == 1, "one row, one slot"


# ------------------------------------------------------------ destruction --
def test_scrolling_a_queued_row_away_removes_it_from_the_queue(queue) -> None:
    slots = _open_group(queue, 20)
    queued = queue.pending[3]

    queue.withdraw(queued)          # Component.onDestruction

    assert queued not in queue.pending
    assert queue.active_count == 6, "destroying a *queued* row frees no slot"


def test_scrolling_an_active_row_away_frees_its_slot(queue) -> None:
    slots = _open_group(queue, 20)
    active = next(s for s in slots if s.holds_slot)

    queue.withdraw(active)          # Component.onDestruction mid-request

    assert queue.active_count == 6, "the freed slot went straight to the queue"
    assert sum(1 for s in slots if s.requests_started) == 7


def test_tearing_the_whole_panel_down_leaks_nothing(queue) -> None:
    slots = _open_group(queue, 100)

    for slot in slots:              # every delegate destroyed, in order
        queue.withdraw(slot)

    assert queue.active_count == 0
    assert queue.pending == []


def test_a_destroyed_queue_is_survivable(queue) -> None:
    """`Component.onDestruction: if (logoQueue) ...` — the null case."""
    queue.restart(None)
    queue.withdraw(None)
    queue.done(None)
    queue.grant(None)

    assert queue.active_count == 0
