import sys
import logging
from pynput import keyboard
from PySide6.QtCore import QObject, Signal, QThread, Slot, QMetaObject, Qt
from core.config import settings_manager

logger = logging.getLogger(__name__)

def convert_qt_to_pynput(qt_key_str: str) -> str:
    """Converts QKeySequence string format (e.g., Ctrl+F2) to pynput format (<ctrl>+<f2>)."""
    if not qt_key_str: return ""

    parts = qt_key_str.split('+')
    pynput_parts = []
    for part in parts:
        part = part.strip().lower()
        if part in ["ctrl", "shift", "alt", "meta", "cmd", "win"]:
            # Handle platform specific mapping
            if sys.platform == "darwin":
                 if part == "ctrl": pynput_parts.append("<cmd>") # Qt Ctrl usually means Cmd on Mac
                 elif part == "meta": pynput_parts.append("<ctrl>") # Qt Meta usually means Ctrl on Mac
                 else: pynput_parts.append(f"<{part}>")
            else:
                 if part == "meta": pynput_parts.append("<win>")
                 else: pynput_parts.append(f"<{part}>")
        elif len(part) > 1:
             # Function keys (F1, F2) or others (Home, End)
             pynput_parts.append(f"<{part}>")
        else:
            # Single characters
            pynput_parts.append(part)
    
    return '+'.join(pynput_parts)


class HotkeyListener(QObject):
    """Listens for global hotkeys using pynput in a dedicated QThread."""
    hotkey_triggered = Signal(str) # Action name (F2, F3, F4)

    def __init__(self):
        super().__init__()
        self.listener = None
        self.hotkey_map = {}

    @Slot()
    def start_listening(self):
        """Starts or restarts the listener. Must be called in the worker thread."""
        if self.listener:
            self.listener.stop()
        
        self.load_hotkeys()

        if not self.hotkey_map:
            logger.info("No hotkeys configured. Listener not starting.")
            return

        try:
            self.listener = keyboard.GlobalHotKeys(self.hotkey_map)
            self.listener.start()
            logger.info(f"Hotkey listener started. Listening for: {list(self.hotkey_map.keys())}")
        except Exception as e:
            logger.error(f"Failed to start global hotkey listener: {e}")
            self.show_permission_warning(e)

    def load_hotkeys(self):
        hotkeys = settings_manager.get_hotkeys()
        self.hotkey_map = {}
        for action, key_str in hotkeys.items():
            if not key_str: continue
            try:
                pynput_key = convert_qt_to_pynput(key_str)
                if pynput_key:
                    self.hotkey_map[pynput_key] = lambda action=action: self.hotkey_triggered.emit(action)
            except Exception as e:
                logger.warning(f"Invalid hotkey format for {action} ({key_str}): {e}")

    @Slot()
    def stop_listening(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
            logger.info("Hotkey listener stopped.")

    def show_permission_warning(self, error):
        # This function runs in the worker thread, so cannot show QMessageBox directly.
        # It should ideally emit a signal back to the main thread.
        if sys.platform == "darwin":
            logger.error("macOS 權限錯誤：請確保已在「系統設定 > 安全性與隱私權 > 輔助使用」中授權此應用程式或終端機。")
        elif sys.platform == "win32":
            logger.warning("Windows UAC 注意：如果目標程式以管理員身分運行，本工具也需要以管理員身分運行才能捕捉熱鍵。")

class HotkeyManager(QObject):
    """Manages the HotkeyListener lifecycle and thread communication."""
    
    trigger_f2 = Signal()
    trigger_f3 = Signal()
    trigger_f4 = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = QThread()
        self.listener = HotkeyListener()
        
        # Move the listener to the dedicated thread
        self.listener.moveToThread(self.thread)
        
        # Connect signals
        self.thread.started.connect(self.listener.start_listening)
        self.listener.hotkey_triggered.connect(self.handle_trigger)
        settings_manager.settings_changed.connect(self.reload_hotkeys)
        
        self.thread.start()

    def handle_trigger(self, action: str):
        # Relay the signal from the listener thread to the main thread
        if action == "F2":
            self.trigger_f2.emit()
        elif action == "F3":
            self.trigger_f3.emit()
        elif action == "F4":
            self.trigger_f4.emit()

    def reload_hotkeys(self):
        """Safely reloads hotkeys by invoking the method in the listener's thread."""
        if self.thread.isRunning():
            # Use invokeMethod to ensure start_listening runs in the correct thread context
            QMetaObject.invokeMethod(self.listener, "start_listening", Qt.ConnectionType.QueuedConnection)

    def stop(self):
        if self.thread.isRunning():
            QMetaObject.invokeMethod(self.listener, "stop_listening", Qt.ConnectionType.QueuedConnection)
            self.thread.quit()
            self.thread.wait()