# core/screenshot.py
import sys
import mss
import mss.tools
import numpy as np
import time
import logging

logger = logging.getLogger(__name__)

# Initialize variables to None globally so they can be safely checked later
windll = None
win32gui = None
wintypes = None
Structure = None
byref = None

# Platform specific initialization
if sys.platform == "win32":
    try:
        import win32gui
        # We still need ctypes for the DWM API calls (DwmGetWindowAttribute)
        from ctypes import windll, wintypes, Structure, byref
        
        # --- FIX: Removed manual DPI awareness setting here ---
        # We rely on Qt (set up in app.py or by default) to handle DPI awareness correctly.
        # Manually setting it here (e.g., windll.shcore.SetProcessDpiAwareness(2)) 
        # used to conflict with Qt's initialization and cause "Access Denied" errors.

    except ImportError:
        logger.warning("pywin32 or ctypes imports failed. Active window capture will be less accurate on Windows.")
        # Ensure they remain None if import fails
        win32gui = None
        windll = None
    except Exception as e:
        logger.warning(f"Unexpected error during Windows API initialization: {e}")
        win32gui = None
        windll = None

def capture_region(monitor_dict: dict) -> np.ndarray | None:
    """Captures a specific region and returns it as a BGRA NumPy array."""
    try:
        with mss.mss() as sct:
            sct_img = sct.grab(monitor_dict)
            # Efficient conversion to NumPy array (BGRA format)
            img = np.array(sct_img)
            return img
    except Exception as e:
        logger.error(f"Error during region capture: {e}")
        return None

def capture_active_window() -> np.ndarray | None:
    """Attempts to capture the currently active (foreground) window."""
    # Small delay to ensure the correct window is focused if triggered by hotkey
    time.sleep(0.05) 
    
    # Check if necessary components are available before calling the Win32 specific function
    # The check for sys.platform ensures short-circuiting on non-Windows platforms.
    if sys.platform == "win32" and win32gui and windll:
        return _capture_active_window_win32()
    else:
        # Fallback for Linux/macOS or if pywin32/ctypes is missing
        logger.info("Active window capture not fully supported on this platform or initialization failed. Capturing primary monitor instead.")
        try:
            with mss.mss() as sct:
                # sct.monitors[0] is the all-monitors bounding box, [1] is the primary monitor
                if len(sct.monitors) > 1:
                    monitor = sct.monitors[1] 
                else:
                    # Fallback if only the bounding box is available
                    monitor = sct.monitors[0]
                return capture_region(monitor)
        except Exception as e:
            logger.error(f"Error during fallback capture: {e}")
            return None

def _capture_active_window_win32() -> np.ndarray | None:
    """Windows specific implementation using DWM for accurate bounds."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None

        # Use DWM API to get the actual window bounds (excluding shadows)
        # This requires the process to be DPI aware, which Qt handles for us.
        try:
            # Ensure required ctypes components (wintypes, Structure, byref) are loaded
            if not (wintypes and Structure and byref):
                raise ImportError("ctypes components (wintypes/Structure/byref) failed to load.")

            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            rect = wintypes.RECT()
            
            # Ensure dwmapi is loaded and the function exists before calling it
            if hasattr(windll, 'dwmapi') and hasattr(windll.dwmapi, 'DwmGetWindowAttribute'):
                # DwmGetWindowAttribute requires byref for the RECT structure. Returns 0 on success.
                if windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS), byref(rect), wintypes.DWORD(Structure.sizeof(rect))) == 0:
                    x, y, x2, y2 = rect.left, rect.top, rect.right, rect.bottom
                else:
                    raise OSError("DwmGetWindowAttribute call failed.")
            else:
                 raise AttributeError("DWM API (dwmapi.dll or DwmGetWindowAttribute) not accessible.")
                 
        except (AttributeError, OSError, ImportError) as e:
            # Fallback if DWM API is not available or failed
            logger.info(f"DWM API failed ({e}), falling back to GetWindowRect (might include shadows).")
            # GetWindowRect should also return physical coordinates if the app is DPI aware.
            x, y, x2, y2 = win32gui.GetWindowRect(hwnd)

        width = x2 - x
        height = y2 - y

        if width <= 0 or height <= 0:
            return None

        monitor = {"top": y, "left": x, "width": width, "height": height}
        return capture_region(monitor)

    except Exception as e:
        logger.error(f"Error during Win32 active window capture: {e}")
        return None