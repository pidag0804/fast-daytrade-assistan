# app.py
import sys
import os
import logging
import asyncio
import platform
# Import QStyleFactory and QMessageBox
from PySide6.QtWidgets import QApplication, QStyleFactory, QMessageBox
from PySide6.QtCore import Qt
import qasync

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger("AppStartup")

# --- Global Exception Handler ---
# This helps catch errors that might otherwise cause a silent crash or blank window.
def handle_exception(exc_type, exc_value, exc_traceback):
    """Handles uncaught exceptions globally, including those from Qt event handlers."""
    if issubclass(exc_type, KeyboardInterrupt):
        # Allow default handling for Ctrl+C
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logger.critical("Unhandled exception occurred:", exc_info=(exc_type, exc_value, exc_traceback))
    
    # Display an error message box for critical errors
    # We need to ensure a QApplication instance exists before showing a QMessageBox
    if QApplication.instance():
        QMessageBox.critical(None, "發生未預期的錯誤",
                             f"應用程式遇到了一個未處理的錯誤並將關閉。\n\n錯誤詳情: {exc_value}")

# Install the global exception handler
sys.excepthook = handle_exception


# Import MainWindow and Config after setting up environment
try:
    from ui.main_window import MainWindow
    from core.config import SettingsManager
except ImportError as e:
    logger.error(f"無法匯入核心模組。請確認專案結構正確且依賴套件已安裝。Error: {e}")
    # Initialize a minimal QApplication just to show the error message if imports fail early
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "匯入錯誤", f"無法匯入核心模組:\n{e}\n\n請確認已安裝所有依賴套件 (pip install -r requirements.txt)。")
    sys.exit(1)

async def main():
    # Ensure High DPI support (Modern Qt 6 approach)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    def factory():
        app = QApplication(sys.argv)
        
        # Set organization and application name (used by QSettings in core/config.py)
        app.setOrganizationName("FastDaytradeTools")
        app.setApplicationName(SettingsManager.SERVICE_NAME)

        # Set a modern style
        # Use QStyleFactory.keys() to check available styles (Fixes previous TypeError)
        if "Fusion" in QStyleFactory.keys():
            app.setStyle("Fusion")
        else:
            logger.info("Fusion style not available, using default platform style.")
            
        return app

    # Check if an application instance already exists
    if not QApplication.instance():
        app = factory()
    else:
        app = QApplication.instance()
    
    # Initialize qasync event loop
    try:
        loop = qasync.QEventLoop(app)
        asyncio.set_event_loop(loop)
    except Exception as e:
        logger.error(f"Failed to initialize asyncio event loop: {e}")
        sys.exit(1)

    # Initialize and show the main window
    # Errors during MainWindow init are caught by the global handler if raised
    main_window = MainWindow()
    main_window.show()


    # Start the event loop
    with loop:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Application interrupted during event loop.")
        finally:
            # Ensure clean shutdown
            loop.close()
            logger.info("Event loop closed.")

if __name__ == "__main__":
    # Handle running from source or bundled application (e.g., PyInstaller)
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        try:
             # Change directory if necessary for finding assets in bundled mode
             os.chdir(sys._MEIPASS)
        except Exception as e:
             logger.warning(f"Could not change directory to _MEIPASS in bundled mode: {e}")

    if platform.system() == "Darwin":
        logger.info("\n--- macOS 注意事項 ---\n請確保已授予「輔助使用」與「螢幕錄製」權限以啟用全域熱鍵與截圖功能。\n")

    try:
        # Use asyncio.run() to start the main async function
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user (Ctrl+C).")
    except SystemExit as e:
        # Handle sys.exit() calls gracefully
        if e.code != 0:
            logger.error(f"Application exited with error code: {e.code}")
    except Exception as e:
        # This catches exceptions that occur outside the QApplication event loop scope during startup
        logger.critical(f"An unhandled exception occurred during asyncio.run: {e}", exc_info=True)