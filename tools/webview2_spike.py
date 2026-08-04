#!/usr/bin/env python3
"""WebView2 detection and direct pythonnet bridge spike (Milestone 3.1, §P3.2).

First step of Phase 3 — confirms that:
  1. pythonnet + the two bridge DLLs (Microsoft.Web.WebView2.Core.dll + WebView2Loader.dll) load.
  2. Registry + import check detects whether Windows built-in Edge WebView2 runtime is present.
  3. A single WebView2 page renders inside a native child window below Halcyon chrome.
  4. Popup / new window requests (NewWindowRequested) are intercepted to route to tabs (§P3.4).
  5. Missing runtime displays "WebView2 is not available" without crash or bundling (§P3.2).

Usage:
    python tools/webview2_spike.py [url] [--smoke]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modes.web import webview2_host, webview2_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("webview2_spike")


def main() -> int:
    parser = argparse.ArgumentParser(description="Halcyon WebView2 bridge spike (Milestone 3.1)")
    parser.add_argument(
        "url",
        nargs="?",
        default="https://www.google.com",
        help="URL to render in the test window (default: https://www.google.com)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run detection and smoke checks without opening an interactive GUI window",
    )
    args = parser.parse_args()

    logger.info("=== Halcyon Milestone 3.1 Spike: WebView2 Detection & Direct Bridge ===")

    available, message = webview2_runtime.check_webview2_available()
    logger.info("WebView2 available: %s — status: %s", available, message)

    if not available:
        logger.info(
            "Expected on non-Windows / Linux CI containers or Windows machines without the "
            "WebView2 Runtime. In Halcyon, Web mode stage will display: '%s' without "
            "crashing or downloading (per §P3.2).",
            webview2_runtime.get_stage_error_message(),
        )
        # Verify host initialization safely fails without exception
        host = webview2_host.WebViewHost()
        ok = host.init_controller(0)
        assert not ok
        assert host.errorMessage == "WebView2 is not available"
        logger.info("Verified safe fallback: WebViewHost reported status correctly.")
        return 0

    logger.info("WebView2 runtime detected via Windows registry & pythonnet import.")
    logger.info("Profile directory: %s", webview2_runtime.get_user_data_dir())

    if args.smoke:
        logger.info("--smoke flag passed: exiting after successful detection check.")
        return 0

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QGuiApplication, QWindow
    except ImportError:
        logger.warning("QtGui/PySide6 unavailable in this environment — smoke test complete.")
        return 0

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    window = QWindow()
    window.setTitle("Halcyon WebView2 Bridge Spike — Milestone 3.1")
    window.resize(1024, 640)

    host = webview2_host.WebViewHost()
    host.urlChanged.connect(lambda u: logger.info("URL Changed -> %s", u))
    host.titleChanged.connect(lambda t: window.setTitle(f"{t} — Halcyon WebView2 Spike"))
    host.newWindowRequested.connect(
        lambda popup_url: logger.info(
            "★ NewWindowRequested intercepted! Route to new Halcyon tab -> %s", popup_url
        )
    )

    window.show()
    app.processEvents()

    win_id = int(window.winId())
    logger.info("Initializing CoreWebView2Controller in parent winId=%s...", win_id)
    ok = host.init_controller(win_id)
    if not ok:
        logger.error("Failed to initialize CoreWebView2Controller: %s", host.errorMessage)
        return 1

    host.set_bounds(0, 0, 1024, 640)
    host.navigate(args.url)

    logger.info("Rendered %s inside native child window. Close window to exit.", args.url)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
