"""Windows WebView2 implementation for Qt widgets.

This module provides WebView2 browser integration that can be embedded
inside a Qt widget by parenting WebView2 to the widget's HWND.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from PySide6.QtCore import QObject

from modes.web.webview_integration import WebViewBase

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# Try to import WebView2
WEBVIEW2_AVAILABLE = False
_CoreWebView2Environment = None
_CoreWebView2Controller = None

if IS_WINDOWS:
    try:
        from webview2.microsoft.web.webview2.core import (  # type: ignore[import-not-found]
            CoreWebView2Controller,
            CoreWebView2Environment,
        )

        _CoreWebView2Environment = CoreWebView2Environment
        _CoreWebView2Controller = CoreWebView2Controller
        WEBVIEW2_AVAILABLE = True
    except ImportError as e:
        log.info("webview2-Microsoft.Web.WebView2.Core not available: %s", e)
    except Exception as e:
        log.warning("Failed to import WebView2: %s", e)


class WebView(WebViewBase):
    """WebView2 wrapper for Qt widgets.
    
    This class creates a WebView2 control and parents it to a Qt widget's
    native window handle (HWND), allowing it to be embedded in a Qt UI.
    
    Usage:
        # Create a container widget in QML or Python
        widget = QWindow.fromWinId(hwnd)  # For QML
        # Or use a QWidget and get its winId()
        
        webview = WebView(widget=my_widget)
        webview.navigate("https://example.com")
        webview.go_back()
    """

    def __init__(
        self,
        widget: "QWidget | None" = None,
        initial_url: str = "about:blank",
        on_title_changed: Callable[[str], None] | None = None,
        on_url_changed: Callable[[str], None] | None = None,
        on_loading_changed: Callable[[bool], None] | None = None,
        on_navigation_completed: Callable[[bool], None] | None = None,
    ) -> None:
        self._widget = widget
        self._on_title_changed = on_title_changed
        self._on_url_changed = on_url_changed
        self._on_loading_changed = on_loading_changed
        self._on_navigation_completed = on_navigation_completed
        self._initial_url = initial_url
        
        self._controller: "CoreWebView2Controller | None" = None
        self._webview: "CoreWebView2Environment | None" = None
        self._initialized = False
        
        # Get HWND from widget if provided
        self._hwnd = None
        if widget is not None:
            try:
                # Qt widget's native window handle
                self._hwnd = int(widget.winId())
            except Exception as e:
                log.warning("Failed to get widget HWND: %s", e)

        if not IS_WINDOWS:
            log.error("WebView2 is only available on Windows")
            return

        if not WEBVIEW2_AVAILABLE:
            log.error("WebView2 package not available")
            return

        # Initialize WebView2
        self._schedule_init()

    def _schedule_init(self) -> None:
        """Schedule initialization from Qt event loop."""
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._async_init)
        except Exception:
            # Fallback to immediate init
            self._async_init()

    def _async_init(self) -> None:
        """Initialize WebView2 asynchronously."""
        if not WEBVIEW2_AVAILABLE or not self._hwnd:
            return

        try:
            import asyncio
            
            # Try to get running loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._init_async())
                    return
            except RuntimeError:
                pass
            
            # Run async init
            asyncio.run(self._init_async())
            
        except Exception as e:
            log.error("WebView2 async init failed: %s", e)
            # Fallback to sync init
            self._init_sync()

    async def _init_async(self) -> None:
        """Async initialization of WebView2."""
        try:
            # Create user data directory
            data_dir = Path.home() / ".halcyon" / "webview2"
            data_dir.mkdir(parents=True, exist_ok=True)
            
            # Create WebView2 environment
            env = await CoreWebView2Environment.create_async(str(data_dir))
            self._webview = env
            
            # Create controller with our HWND
            controller = await env.create_core_webview2_controller_async(self._hwnd)
            self._controller = controller
            
            # Configure the controller
            self._setup_controller()
            
            self._initialized = True
            log.info("WebView2 initialized successfully on HWND: %s", self._hwnd)
            
            # Navigate to initial URL
            if self._initial_url and self._initial_url != "about:blank":
                self.navigate(self._initial_url)
            else:
                # Navigate to blank with our background color
                self.navigate_to_blank()
                
        except FileNotFoundError:
            log.error("WebView2 Runtime not found. Please install Microsoft Edge WebView2 Runtime.")
        except Exception as e:
            log.error("WebView2 initialization failed: %s", e)

    def _init_sync(self) -> None:
        """Synchronous initialization fallback."""
        if not WEBVIEW2_AVAILABLE or not self._hwnd:
            return

        try:
            import asyncio
            
            # Create new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._init_async())
            finally:
                loop.close()
        except Exception as e:
            log.error("WebView2 sync init failed: %s", e)

    def _setup_controller(self) -> None:
        """Set up WebView2 controller properties and event handlers."""
        if not self._controller:
            return

        try:
            # Set default background color (matches app theme)
            self._controller.default_background_color = 0x0E1118  # Theme.base color
            
            # Set size to match parent
            if self._widget:
                size = self._widget.size()
                self._controller.bounds = (0, 0, size.width(), size.height())
            
            # Get CoreWebView for event handling
            webview = self._controller.core_web_view
            if webview:
                # Set up navigation event handlers
                self._setup_event_handlers(webview)
                
        except Exception as e:
            log.warning("Failed to setup controller: %s", e)

    def _setup_event_handlers(self, webview) -> None:
        """Set up WebView2 event handlers."""
        try:
            # Navigation events
            webview.navigation_started = self._on_navigation_started
            webview.navigation_completed = self._on_navigation_completed
            webview.source_changed = self._on_source_changed
            
            # Other events
            webview.document_title_changed = self._on_document_title_changed
            
            log.debug("WebView2 event handlers configured")
        except Exception as e:
            log.warning("Failed to setup event handlers: %s", e)

    def _on_navigation_started(self, sender, args) -> None:
        """Handle navigation started."""
        log.debug("Navigation started")
        if self._on_loading_changed:
            self._on_loading_changed(True)

    def _on_navigation_completed(self, sender, args) -> None:
        """Handle navigation completed."""
        log.debug("Navigation completed")
        if self._on_loading_changed:
            self._on_loading_changed(False)
        if self._on_navigation_completed:
            self._on_navigation_completed(args.is_success)

    def _on_source_changed(self, sender, args) -> None:
        """Handle URL/source changed."""
        try:
            url = sender.source
            log.debug("Source changed: %s", url)
            if self._on_url_changed:
                self._on_url_changed(url)
        except Exception as e:
            log.warning("Failed to get source: %s", e)

    def _on_document_title_changed(self, sender, args) -> None:
        """Handle document title changed."""
        try:
            title = sender.document_title
            log.debug("Title changed: %s", title)
            if self._on_title_changed:
                self._on_title_changed(title)
        except Exception as e:
            log.warning("Failed to get title: %s", e)

    def navigate(self, url: str) -> None:
        """Navigate to URL."""
        if not url:
            return

        if not self._initialized:
            log.debug("Navigate queued: %s", url)
            self._initial_url = url
            return

        try:
            if url == "about:blank":
                self.navigate_to_blank()
            else:
                webview = self._controller.core_web_view
                if webview:
                    webview.navigate(url)
            log.debug("Navigating to: %s", url)
        except Exception as e:
            log.error("Navigation failed for %s: %s", url, e)

    def navigate_to_blank(self) -> None:
        """Navigate to blank page with app theme background."""
        if not self._initialized:
            return
        try:
            html = "<html><body style='background-color:#0E1118;margin:0;'></body></html>"
            webview = self._controller.core_web_view
            if webview:
                webview.navigate_to_string(html)
        except Exception as e:
            log.warning("Navigate to blank failed: %s", e)

    def go_back(self) -> None:
        """Go to previous page in history."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                if webview and webview.can_go_back:
                    webview.go_back()
            except Exception as e:
                log.warning("Go back failed: %s", e)

    def go_forward(self) -> None:
        """Go to next page in history."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                if webview and webview.can_go_forward:
                    webview.go_forward()
            except Exception as e:
                log.warning("Go forward failed: %s", e)

    def reload(self) -> None:
        """Reload current page."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                if webview:
                    webview.reload()
            except Exception as e:
                log.warning("Reload failed: %s", e)

    def stop(self) -> None:
        """Stop current loading."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                if webview:
                    webview.stop()
            except Exception:
                pass

    @property
    def can_go_back(self) -> bool:
        """Check if back navigation is available."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                return webview.can_go_back if webview else False
            except Exception:
                pass
        return False

    @property
    def can_go_forward(self) -> bool:
        """Check if forward navigation is available."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                return webview.can_go_forward if webview else False
            except Exception:
                pass
        return False

    @property
    def current_url(self) -> str:
        """Get current URL."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                return webview.source if webview else ""
            except Exception:
                pass
        return ""

    @property
    def current_title(self) -> str:
        """Get current page title."""
        if self._controller:
            try:
                webview = self._controller.core_web_view
                return webview.document_title if webview else ""
            except Exception:
                pass
        return ""

    def update_bounds(self, x: int, y: int, width: int, height: int) -> None:
        """Update WebView2 bounds."""
        if self._controller:
            try:
                self._controller.bounds = (x, y, width, height)
            except Exception as e:
                log.warning("Failed to update bounds: %s", e)

    def close(self) -> None:
        """Close and cleanup the web view."""
        self._initialized = False
        if self._controller:
            try:
                self._controller.close()
            except Exception:
                pass
        self._controller = None
        self._webview = None
        log.debug("WebView2 closed")
