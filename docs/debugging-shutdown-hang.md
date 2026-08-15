# Debugging the Halcyon shutdown hang

Window closes, logs stop at `engine shut down`, the Python process never
exits. This is the runbook for isolating and pinning the exact blocking
frame. See `core/shutdown_trace.py` for the tracer that produces the dumps.

## The three ranked suspects (2026-08-15)

1. **.NET CLR shutdown racing Python finalization.** `clr.dll`,
   `mscorlib.ni.dll`, `clrjit.dll` are loaded because `main.py` calls
   `init_pythonnet_com()` for WebView2. Two runtimes tearing down
   concurrently, neither aware of the other, is a known hang.
2. **`QThreadPool.globalInstance()` in `modes/m3u/playlist.py`.** `~QThreadPool`
   calls `waitForDone()` with no timeout. Fixed: M3U now owns a private pool
   and `M3UContext.shutdown()` drains it (see commit "Use a private
   QThreadPool for M3U playlist loads"). This was a real latent bug
   regardless of whether it is today's cause.
3. **VLC's `libqt_plugin.dll`** (17 MB, `vendor/vlc/plugins/gui/`) is loaded
   even with `--intf=dummy` because VLC dlopens every plugin to build its
   cache. A second Qt's static destructors in the same process as PySide6 is
   a hazard.

## Step 1 — isolate the CLR (one run, no tools)

Run the app with the pythonnet bootstrap skipped:

```bat
set HALCYON_DISABLE_PYTHONNET=1
python main.py --trace-shutdown
```

(or `python main.py --no-pythonnet --trace-shutdown`). Then close it.

- **Exits cleanly** → suspect #1 confirmed; hunt the CLR finalization race.
- **Still hangs** → CLR exonerated; read the dump (Step 3). The M3U pool fix
  (Step 2) is already in, so the remaining candidates are the interpreter
  finalization join and VLC's Qt plugin.

## Step 2 — M3U global pool fix

Done in `modes/m3u/playlist.py` + `tests/test_m3u_shutdown.py` (see the
commit). No action needed; verified by `pytest tests/test_m3u_shutdown.py`.

## Step 3 — read the minidump

The tracer writes `shutdown-trace.txt` (readable now) and
`shutdown-trace.dmp` (in the repo root, next to `main.py`). Open the `.dmp`
in **WinDbg (x64)** — *File → Open Crash Dump*.

Paste this whole block into the command line:

```
.symfix
.reload
!analyze -v
~0k
~*k
!uniqstack -v
!runaway
lmDvmclr
lmDvmmscorlib
lmDvmpython314
lmDvmQt6Core
lmDvmQt6Qml
lmDvmQt6Quick
lmDvmlibqt_plugin
```

What each does, and what to paste back:

| Command | Purpose | Paste back when |
|---|---|---|
| `.symfix` / `.reload` | Fetch Microsoft symbols + reload all modules (Python/VLC/Qt symbols usually need `srv*C:\Symbols*https://msdl.microsoft.com/download/symbols`) | always — say if `.reload` reports errors on python314/qt6/libvlc |
| `!analyze -v` | First guess at the faulting/blocking frame | first ~30 lines |
| `~0k` | Main thread stack with return addresses | full output |
| `~*k` | Every thread's stack | full output — this is the one that names the blocker |
| `!uniqstack -v` | Groups the 12+ threads by where they wait; the *caller* of each wait is the interesting frame | full output |
| `!runaway` | Thread CPU times — proves nothing is spinning | output, just to confirm |
| `lmDvm...` | Confirms which DLLs are loaded and their build ids | output |

### How to read it

Every thread parks in a wait syscall (`ntdll!NtWaitFor...` /
`win32u!NtUserMsgWaitForMultipleObjectsEx`). The **frame directly below the
wait** is the blocker:

- `clr!Thread::Join` / `clr!WaitForFinalizers` / `clr!ThreadpoolMgr::UnfairSemaphore::Wait` / `clr!WaitHandle::WaitOne` → **suspect #1 confirmed**: the CLR is tearing down while Python finalizes.
- `Qt6Core!QThreadPoolThread::run` → `QThread::wait`/`QMutex::lock` from a `waitForDone()` caller → suspect #2-style join (the M3U fix should have removed ours; check the caller frames to see whose pool it is).
- `Qt6Gui`/`Qt6Qml`/`Qt6Quick` static destructors running *inside* a second Qt instance's teardown (check the caller chain for `libqt_plugin.dll`) → suspect #3.
- `python314!PyThread_acquire_lock` / `Py_FinalizeEx` / `Py_EndInterpreter` waiting on a non-daemon thread → interpreter finalization join (what the out-of-process trace could not rule out).

If the `.dmp` is missing (trace showed the hang but no dump — the helper
suspends/resumes threads, so check `shutdown-trace.log`), re-run with
`--trace-shutdown` and wait ~10 s after the hang before killing the process.
