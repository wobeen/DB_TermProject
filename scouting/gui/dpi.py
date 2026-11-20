"""Windows DPI setup, called before Tk creates a native window."""

from __future__ import annotations

import sys


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def configure_tk_scaling(root) -> None:
    """Map Tk points to the monitor's actual pixels without double scaling."""
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", dpi / 72.0)
        return dpi
    except Exception:
        return 96.0
