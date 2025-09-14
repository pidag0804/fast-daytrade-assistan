# app.py
import sys
import os
import logging
import asyncio
import platform
import traceback  # 匯入 traceback 模組
from PySide6.QtWidgets import QApplication, QStyleFactory, QMessageBox
from PySide6.QtCore import Qt
import qasync

# --- 設定日誌記錄到檔案 ---
log_file_path = "app_crash.log"
# 每次啟動時清除舊的日誌檔案
if os.path.exists(log_file_path):
    os.remove(log_file_path)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'), # 寫入檔案
        logging.StreamHandler(sys.stdout)                  # 同時在終端機顯示
    ]
)
logger = logging.getLogger("AppStartup")

# --- 全域例外處理器 (增強版) ---
def handle_exception(exc_type, exc_value, exc_traceback):
    """全域處理未捕獲的例外，將其寫入日誌檔案。"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # 格式化完整的錯誤回溯訊息
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logger.critical(f"Unhandled exception occurred:\n{error_msg}")
    
    # 確保 QApplication 實例存在，才顯示訊息框
    if QApplication.instance():
        QMessageBox.critical(None, "發生未預期的錯誤",
                             f"應用程式遇到了一個無法處理的錯誤並將關閉。\n\n"
                             f"錯誤詳情已寫入日誌檔案: {os.path.abspath(log_file_path)}")
    
    sys.exit(1)

# 安裝全域例外處理器
sys.excepthook = handle_exception


# Import MainWindow and Config after setting up environment
try:
    from ui.main_window import MainWindow
    from core.config import SettingsManager
except ImportError as e:
    logger.error(f"無法匯入核心模組。請確認專案結構正確且依賴套件已安裝。Error: {e}")
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "匯入錯誤", f"無法匯入核心模組:\n{e}\n\n請確認已安裝所有依賴套件 (pip install -r requirements.txt)。")
    sys.exit(1)

async def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    def factory():
        app = QApplication(sys.argv)
        app.setOrganizationName("FastDaytradeTools")
        app.setApplicationName(SettingsManager.SERVICE_NAME)
        if "Fusion" in QStyleFactory.keys():
            app.setStyle("Fusion")
        else:
            logger.info("Fusion style not available, using default platform style.")
        return app

    if not QApplication.instance():
        app = factory()
    else:
        app = QApplication.instance()
    
    try:
        loop = qasync.QEventLoop(app)
        asyncio.set_event_loop(loop)
    except Exception as e:
        logger.error(f"Failed to initialize asyncio event loop: {e}")
        sys.exit(1)

    main_window = MainWindow()
    main_window.show()

    with loop:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Application interrupted during event loop.")
        finally:
            loop.close()
            logger.info("Event loop closed.")

if __name__ == "__main__":
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        try:
             os.chdir(sys._MEIPASS)
        except Exception as e:
             logger.warning(f"Could not change directory to _MEIPASS in bundled mode: {e}")

    if platform.system() == "Darwin":
        logger.info("\n--- macOS 注意事項 ---\n請確保已授予「輔助使用」與「螢幕錄製」權限以啟用全域熱鍵與截圖功能。\n")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user (Ctrl+C).")
    except SystemExit as e:
        if e.code != 0:
            logger.error(f"Application exited with error code: {e.code}")
    except Exception as e:
        logger.critical(f"An unhandled exception occurred during asyncio.run: {e}", exc_info=True)