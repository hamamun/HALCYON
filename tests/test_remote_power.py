"""Power actions — §R.2 ⚡ Power. Executor is injectable; never run for real."""

from __future__ import annotations

from remote import power


def _record():
    calls = []

    def executor(argv):
        calls.append(list(argv))
        return 0

    return calls, executor


def test_sleep_issues_command():
    calls, executor = _record()
    assert power.sleep_pc(executor=executor) is True
    assert calls, "sleep must invoke an OS command"
    assert any("suspend" in " ".join(c).lower() or "powrprof" in c[0].lower() for c in calls)


def test_shutdown_issues_command():
    calls, executor = _record()
    assert power.shutdown_pc(executor=executor) is True
    assert calls, "shutdown must invoke an OS command"
    assert any("shutdown" in " ".join(c).lower() or "poweroff" in " ".join(c).lower() for c in calls)


def test_failure_returns_false():
    calls, executor = _record()

    def failing(_argv):
        return 1

    assert power.sleep_pc(executor=failing) is False
