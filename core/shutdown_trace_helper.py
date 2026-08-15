#!/usr/bin/env python3
"""Standalone out-of-process watcher for a hung Halcyon shutdown.

Run as::

    python core/shutdown_trace_helper.py <pid> <dump_path> <grace>

This script is spawned by :class:`core.shutdown_trace.ShutdownTracer` at the
top of ``aboutToQuit``. It is deliberately standalone: it imports nothing from
Halcyon, touches no Qt, and must keep running after its parent's main thread
has wedged.

**Why it exists.** Halcyon's main thread blocks inside a native Qt call during
QML teardown *while holding the GIL*. An in-process tracer thread can never be
scheduled, so it can never report. Only a separate process — which the GIL does
not constrain — can observe the hang. This script does that with ctypes over
``kernel32`` and ``dbghelp``:

1. Open the parent process and ``WaitForSingleObject`` on its handle for
   ``grace`` seconds. If it signals, the parent exited cleanly: exit silently
   with no output. This is the normal path on every healthy shutdown.
2. Otherwise the parent is hung. Snapshot its loaded modules via Toolhelp so
   addresses can be attributed to a DLL.
3. Suspend every thread in the parent, read each one's ``CONTEXT`` control
   registers (``Rip`` on x64, ``Eip`` on x86), and resolve that instruction
   pointer to ``module+offset``.
4. Write a human-readable ``shutdown-trace.txt`` and a full
   ``shutdown-trace.dmp`` minidump (loadable in WinDbg/Visual Studio for real
   symbolised stacks).
5. Resume every thread in a ``finally`` block — unconditionally. Leaving a
   process suspended would turn a diagnostic into a much worse bug.

Windows-only. On any other platform it exits quietly.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# Platform gate. Do this before importing ctypes.wintypes, which does not exist
# off Windows.
# --------------------------------------------------------------------------
if sys.platform != "win32":  # pragma: no cover - Windows-only diagnostic
    sys.exit(0)

import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

# --------------------------------------------------------------------------
# Win32 constants
# --------------------------------------------------------------------------
PROCESS_ALL_ACCESS = 0x001F0FFF
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
SYNCHRONIZE = 0x00100000

THREAD_GET_CONTEXT = 0x0008
THREAD_SUSPEND_RESUME = 0x0002
THREAD_QUERY_INFORMATION = 0x0040

TH32CS_SNAPTHREAD = 0x00000004
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

MAX_MODULE_NAME32 = 255
MAX_PATH = 260

# CONTEXT flags. The *_CONTROL subset is all we need (instruction pointer,
# stack pointer, frame pointer) and is the cheapest to retrieve.
CONTEXT_AMD64 = 0x00100000
CONTEXT_AMD64_CONTROL = CONTEXT_AMD64 | 0x00000001
CONTEXT_i386 = 0x00010000
CONTEXT_I386_CONTROL = CONTEXT_i386 | 0x00000001

IS_X64 = ctypes.sizeof(ctypes.c_void_p) == 8

#: MiniDumpWithFullMemory | MiniDumpWithHandleData | MiniDumpWithThreadInfo
#: A full-memory dump is large but is the only kind that reliably reconstructs
#: native stacks through Qt's teardown.
MINIDUMP_TYPE = 0x00000002 | 0x00000004 | 0x00001000

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# --------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------
class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * (MAX_MODULE_NAME32 + 1)),
        ("szExePath", ctypes.c_char * MAX_PATH),
    ]


class M128A(ctypes.Structure):
    _fields_ = [("Low", ctypes.c_ulonglong), ("High", ctypes.c_longlong)]


class CONTEXT_AMD64_T(ctypes.Structure):
    """x64 CONTEXT. Must be 16-byte aligned and laid out exactly."""

    _pack_ = 16
    _fields_ = [
        ("P1Home", ctypes.c_ulonglong),
        ("P2Home", ctypes.c_ulonglong),
        ("P3Home", ctypes.c_ulonglong),
        ("P4Home", ctypes.c_ulonglong),
        ("P5Home", ctypes.c_ulonglong),
        ("P6Home", ctypes.c_ulonglong),
        ("ContextFlags", wintypes.DWORD),
        ("MxCsr", wintypes.DWORD),
        ("SegCs", wintypes.WORD),
        ("SegDs", wintypes.WORD),
        ("SegEs", wintypes.WORD),
        ("SegFs", wintypes.WORD),
        ("SegGs", wintypes.WORD),
        ("SegSs", wintypes.WORD),
        ("EFlags", wintypes.DWORD),
        ("Dr0", ctypes.c_ulonglong),
        ("Dr1", ctypes.c_ulonglong),
        ("Dr2", ctypes.c_ulonglong),
        ("Dr3", ctypes.c_ulonglong),
        ("Dr6", ctypes.c_ulonglong),
        ("Dr7", ctypes.c_ulonglong),
        ("Rax", ctypes.c_ulonglong),
        ("Rcx", ctypes.c_ulonglong),
        ("Rdx", ctypes.c_ulonglong),
        ("Rbx", ctypes.c_ulonglong),
        ("Rsp", ctypes.c_ulonglong),
        ("Rbp", ctypes.c_ulonglong),
        ("Rsi", ctypes.c_ulonglong),
        ("Rdi", ctypes.c_ulonglong),
        ("R8", ctypes.c_ulonglong),
        ("R9", ctypes.c_ulonglong),
        ("R10", ctypes.c_ulonglong),
        ("R11", ctypes.c_ulonglong),
        ("R12", ctypes.c_ulonglong),
        ("R13", ctypes.c_ulonglong),
        ("R14", ctypes.c_ulonglong),
        ("R15", ctypes.c_ulonglong),
        ("Rip", ctypes.c_ulonglong),
        ("FltSave", ctypes.c_byte * 512),
        ("VectorRegister", M128A * 26),
        ("VectorControl", ctypes.c_ulonglong),
        ("DebugControl", ctypes.c_ulonglong),
        ("LastBranchToRip", ctypes.c_ulonglong),
        ("LastBranchFromRip", ctypes.c_ulonglong),
        ("LastExceptionToRip", ctypes.c_ulonglong),
        ("LastExceptionFromRip", ctypes.c_ulonglong),
    ]


class FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [
        ("ControlWord", wintypes.DWORD),
        ("StatusWord", wintypes.DWORD),
        ("TagWord", wintypes.DWORD),
        ("ErrorOffset", wintypes.DWORD),
        ("ErrorSelector", wintypes.DWORD),
        ("DataOffset", wintypes.DWORD),
        ("DataSelector", wintypes.DWORD),
        ("RegisterArea", ctypes.c_byte * 80),
        ("Cr0NpxState", wintypes.DWORD),
    ]


class CONTEXT_X86_T(ctypes.Structure):
    """x86 CONTEXT."""

    _fields_ = [
        ("ContextFlags", wintypes.DWORD),
        ("Dr0", wintypes.DWORD),
        ("Dr1", wintypes.DWORD),
        ("Dr2", wintypes.DWORD),
        ("Dr3", wintypes.DWORD),
        ("Dr6", wintypes.DWORD),
        ("Dr7", wintypes.DWORD),
        ("FloatSave", FLOATING_SAVE_AREA),
        ("SegGs", wintypes.DWORD),
        ("SegFs", wintypes.DWORD),
        ("SegEs", wintypes.DWORD),
        ("SegDs", wintypes.DWORD),
        ("Edi", wintypes.DWORD),
        ("Esi", wintypes.DWORD),
        ("Ebx", wintypes.DWORD),
        ("Edx", wintypes.DWORD),
        ("Ecx", wintypes.DWORD),
        ("Eax", wintypes.DWORD),
        ("Ebp", wintypes.DWORD),
        ("Eip", wintypes.DWORD),
        ("SegCs", wintypes.DWORD),
        ("EFlags", wintypes.DWORD),
        ("Esp", wintypes.DWORD),
        ("SegSs", wintypes.DWORD),
        ("ExtendedRegisters", ctypes.c_byte * 512),
    ]


class MINIDUMP_EXCEPTION_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ThreadId", wintypes.DWORD),
        ("ExceptionPointers", ctypes.c_void_p),
        ("ClientPointers", wintypes.BOOL),
    ]


# --------------------------------------------------------------------------
# Module map
# --------------------------------------------------------------------------
def enumerate_modules(pid: int) -> list[tuple[int, int, str, str]]:
    """Return ``(base, size, name, path)`` for every module loaded in *pid*."""
    modules: list[tuple[int, int, str, str]] = []
    snap = kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid
    )
    if snap == INVALID_HANDLE_VALUE:
        return modules
    try:
        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)
        ok = kernel32.Module32First(snap, ctypes.byref(entry))
        while ok:
            base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
            modules.append(
                (
                    base,
                    int(entry.modBaseSize),
                    entry.szModule.decode("mbcs", "replace"),
                    entry.szExePath.decode("mbcs", "replace"),
                )
            )
            ok = kernel32.Module32Next(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    modules.sort(key=lambda m: m[0])
    return modules


def resolve(addr: int, modules: list[tuple[int, int, str, str]]) -> str:
    """Map an absolute address to ``module.dll+0xoffset``."""
    for base, size, name, _path in modules:
        if base <= addr < base + size:
            return f"{name}+0x{addr - base:x}"
    return "<unknown module>"


def enumerate_threads(pid: int) -> list[int]:
    """Return every thread id belonging to *pid*, in creation order."""
    tids: list[int] = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        return tids
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        ok = kernel32.Thread32First(snap, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                tids.append(int(entry.th32ThreadID))
            ok = kernel32.Thread32Next(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return tids


def thread_instruction_pointer(handle: int) -> tuple[int, int, int] | None:
    """Return ``(ip, sp, bp)`` for a *suspended* thread, or ``None``."""
    if IS_X64:
        # The x64 CONTEXT must be 16-byte aligned; over-allocate and align.
        raw = (ctypes.c_byte * (ctypes.sizeof(CONTEXT_AMD64_T) + 16))()
        addr = ctypes.addressof(raw)
        aligned = (addr + 15) & ~15
        ctx = CONTEXT_AMD64_T.from_address(aligned)
        ctx.ContextFlags = CONTEXT_AMD64_CONTROL
        if not kernel32.GetThreadContext(wintypes.HANDLE(handle), ctypes.byref(ctx)):
            return None
        return int(ctx.Rip), int(ctx.Rsp), int(ctx.Rbp)

    ctx32 = CONTEXT_X86_T()
    ctx32.ContextFlags = CONTEXT_I386_CONTROL
    if not kernel32.GetThreadContext(wintypes.HANDLE(handle), ctypes.byref(ctx32)):
        return None
    return int(ctx32.Eip), int(ctx32.Esp), int(ctx32.Ebp)


def write_minidump(process: int, pid: int, path: Path) -> str:
    """Write a full minidump of *process* to *path*. Returns a status string."""
    try:
        dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)
    except OSError:
        return "dbghelp.dll unavailable — no minidump written"

    handle = kernel32.CreateFileW(
        str(path),
        0x40000000,  # GENERIC_WRITE
        0,
        None,
        2,  # CREATE_ALWAYS
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return f"could not create {path} (error {ctypes.get_last_error()})"

    try:
        dbghelp.MiniDumpWriteDump.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        dbghelp.MiniDumpWriteDump.restype = wintypes.BOOL
        ok = dbghelp.MiniDumpWriteDump(
            wintypes.HANDLE(process),
            wintypes.DWORD(pid),
            wintypes.HANDLE(handle),
            wintypes.DWORD(MINIDUMP_TYPE),
            None,
            None,
            None,
        )
        if not ok:
            return f"MiniDumpWriteDump failed (error {ctypes.get_last_error()})"
        return f"minidump written to {path}"
    finally:
        kernel32.CloseHandle(handle)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(
            "usage: shutdown_trace_helper.py <pid> <dump_path> <grace>",
            file=sys.stderr,
        )
        return 2

    pid = int(argv[1])
    dump_path = Path(argv[2])
    grace = float(argv[3])

    txt_path = dump_path.with_suffix(".txt")
    dmp_path = dump_path.with_suffix(".dmp")

    process = kernel32.OpenProcess(
        PROCESS_ALL_ACCESS, False, pid
    ) or kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | SYNCHRONIZE, False, pid
    )
    if not process:
        # Parent already gone, or we lack rights. Either way: nothing to report.
        return 0

    try:
        # ------------------------------------------------------------------
        # Step 1: wait out the grace period on the parent's handle. A healthy
        # shutdown signals the handle and we exit having written nothing.
        # ------------------------------------------------------------------
        rc = kernel32.WaitForSingleObject(
            wintypes.HANDLE(process), wintypes.DWORD(int(grace * 1000))
        )
        if rc == WAIT_OBJECT_0:
            return 0
        if rc != WAIT_TIMEOUT:
            return 0

        # ------------------------------------------------------------------
        # Step 2: still alive. Snapshot modules, then freeze and inspect.
        # ------------------------------------------------------------------
        modules = enumerate_modules(pid)
        tids = enumerate_threads(pid)

        lines: list[str] = []
        lines.append("=" * 78)
        lines.append("HALCYON SHUTDOWN HANG TRACE")
        lines.append("=" * 78)
        lines.append(f"captured   : {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"target pid : {pid}")
        lines.append(f"grace      : {grace:.1f}s elapsed after aboutToQuit")
        lines.append(f"arch       : {'x64' if IS_X64 else 'x86'}")
        lines.append(f"threads    : {len(tids)}")
        lines.append(f"modules    : {len(modules)}")
        lines.append("")
        lines.append(
            "The process was still alive after the grace period, so the shutdown"
        )
        lines.append(
            "is hung. Each thread below is reported by its instruction pointer,"
        )
        lines.append(
            "resolved to the DLL that owns it. The thread sitting in Qt6Qml /"
        )
        lines.append(
            "Qt6Quick / Qt6Core (rather than in ntdll's wait routines) is the one"
        )
        lines.append("holding the GIL and blocking the exit.")
        lines.append("")

        suspended: list[int] = []
        try:
            # --------------------------------------------------------------
            # Step 3: suspend every thread, then read its context. Suspending
            # first means all the reported IPs are from one coherent instant.
            # --------------------------------------------------------------
            handles: list[tuple[int, int]] = []
            for tid in tids:
                h = kernel32.OpenThread(
                    THREAD_GET_CONTEXT | THREAD_SUSPEND_RESUME | THREAD_QUERY_INFORMATION,
                    False,
                    tid,
                )
                if not h:
                    continue
                if kernel32.SuspendThread(wintypes.HANDLE(h)) == 0xFFFFFFFF:
                    kernel32.CloseHandle(h)
                    continue
                suspended.append(h)
                handles.append((tid, h))

            for index, (tid, h) in enumerate(handles):
                regs = thread_instruction_pointer(h)
                label = "main/GUI thread (suspect)" if index == 0 else f"thread {index}"
                lines.append("-" * 78)
                if regs is None:
                    lines.append(f"[{label}] tid={tid}  <context unavailable>")
                    continue
                ip, sp, bp = regs
                lines.append(f"[{label}] tid={tid}")
                lines.append(f"    ip = 0x{ip:016x}  {resolve(ip, modules)}")
                lines.append(f"    sp = 0x{sp:016x}")
                lines.append(f"    bp = 0x{bp:016x}")

            # --------------------------------------------------------------
            # Step 4: minidump, for real symbolised stacks in WinDbg.
            # --------------------------------------------------------------
            lines.append("")
            lines.append("=" * 78)
            lines.append(write_minidump(process, pid, dmp_path))
            lines.append("=" * 78)
            lines.append("")
            lines.append("Loaded modules:")
            for base, size, name, path in modules:
                lines.append(f"    0x{base:016x} +0x{size:08x}  {name:<28} {path}")

        finally:
            # --------------------------------------------------------------
            # Step 5: ALWAYS resume. A suspended process is a far worse bug
            # than the one we came to diagnose.
            # --------------------------------------------------------------
            for h in suspended:
                try:
                    kernel32.ResumeThread(wintypes.HANDLE(h))
                finally:
                    kernel32.CloseHandle(h)

        try:
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            import tempfile

            fallback = Path(tempfile.gettempdir()) / txt_path.name
            fallback.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return 0
    finally:
        kernel32.CloseHandle(process)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
