# ui/main_window.py
import sys
import os
import logging
import asyncio
import numpy as np
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QListView, QTextEdit, QPushButton, QToolBar, QStatusBar,
    QApplication, QLabel, QMenu, QMessageBox, QScrollArea
)
from PySide6.QtCore import Qt, QThreadPool, Slot, QSize, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QImage

from core.config import settings_manager
from core.hotkeys import HotkeyManager
from core.screenshot import capture_active_window, capture_region
from core.imaging import ImageSaveWorker

# Import the centralized AI manager
from core.ai_client.manager import ai_manager 
from core.models import AnalysisResult

# Import THUMBNAIL_SIZE for consistent UI sizing
from ui.queue_model import UploadQueueModel, THUMBNAIL_SIZE
from ui.settings_dialog import SettingsDialog
from ui.widgets import SnippingTool, AnalysisCard
from ui.editor.editor_window import ImageEditorWindow

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Set basic window properties first
        self.setWindowTitle("股票當沖詢問工具 (Fast Daytrade Assistant)")
        self.setGeometry(100, 100, 1300, 850)

        # Use a try-except block during initialization to catch errors causing blank windows
        try:
            # Initialize QThreadPool for background image processing
            self.threadpool = QThreadPool()
            logger.info(f"Initialized ThreadPool with {self.threadpool.maxThreadCount()} threads.")

            # Initialize core components
            self.hotkey_manager = HotkeyManager(self)
            self.queue_model = UploadQueueModel(self)
            self.snipping_tool = SnippingTool()
            self.editor_window = None
            self.original_window_state = None # For tracking state during screenshots

            # Setup the UI structure (Crucial for visibility)
            self.setup_ui()
            self.setup_toolbar()
            self.connect_signals()
            self.load_styles()

            # Initial load of settings display
            self.on_settings_changed()

        except Exception as e:
            # If initialization fails, log it. The global handler in app.py will show the error.
            logger.critical(f"Failed to initialize MainWindow: {e}", exc_info=True)
            # Re-raise the exception to stop the application
            raise

    # --- UI Setup Methods (Must be complete) ---

    def setup_ui(self):
        # This is the core layout setup.
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # These methods add widgets to the splitter
        self.setup_queue_panel(splitter)
        self.setup_chat_panel(splitter)

        splitter.setSizes([350, 950])

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.update_status("就緒")

    def setup_queue_panel(self, parent_splitter):
        queue_panel = QWidget()
        layout = QVBoxLayout(queue_panel)
        layout.addWidget(QLabel("待上傳區 (可拖拉排序、多選)"))

        self.queue_view = QListView()
        self.queue_view.setModel(self.queue_model)
        # Use IconMode for better thumbnail display
        self.queue_view.setViewMode(QListView.ViewMode.IconMode)
        # Set icon size based on the thumbnail size defined in queue_model
        self.queue_view.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.queue_view.setGridSize(QSize(THUMBNAIL_SIZE + 20, THUMBNAIL_SIZE + 30))
        self.queue_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.queue_view.setSpacing(5)

        # Enable Drag/Drop and Selection
        self.queue_view.setDragEnabled(True)
        self.queue_view.setAcceptDrops(True)
        self.queue_view.setDropIndicatorShown(True)
        self.queue_view.setDragDropMode(QListView.DragDropMode.InternalMove)
        self.queue_view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)

        # Context Menu
        self.queue_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_view.customContextMenuRequested.connect(self.show_queue_context_menu)

        layout.addWidget(self.queue_view)
        parent_splitter.addWidget(queue_panel)

    def setup_chat_panel(self, parent_splitter):
        chat_panel = QWidget()
        layout = QVBoxLayout(chat_panel)

        # Results Display Area (Scrollable Container for Cards)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_area.setWidget(self.results_container)
        layout.addWidget(scroll_area, stretch=1)

        # Input Area
        self.user_input = QTextEdit()
        self.user_input.setPlaceholderText("輸入補充說明（例如：目前持倉成本、特殊消息等）...")
        self.user_input.setMaximumHeight(80)
        layout.addWidget(self.user_input)

        self.send_button = QPushButton("送出分析請求")
        self.send_button.clicked.connect(self.send_analysis_request)
        layout.addWidget(self.send_button)

        parent_splitter.addWidget(chat_panel)

    def setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        self.action_f2 = QAction("截當前視窗", self)
        self.action_f2.triggered.connect(lambda: self.trigger_screenshot('window'))
        toolbar.addAction(self.action_f2)

        self.action_f3 = QAction("截並編輯", self)
        self.action_f3.triggered.connect(lambda: self.trigger_screenshot('edit'))
        toolbar.addAction(self.action_f3)

        self.action_f4 = QAction("框選截圖", self)
        self.action_f4.triggered.connect(lambda: self.trigger_screenshot('region'))
        toolbar.addAction(self.action_f4)

        toolbar.addSeparator()

        action_clear = QAction("清空待上傳", self)
        action_clear.triggered.connect(self.queue_model.clear_queue)
        toolbar.addAction(action_clear)

        action_settings = QAction("設定", self)
        action_settings.triggered.connect(self.open_settings)
        toolbar.addAction(action_settings)

    def connect_signals(self):
        # Hotkeys
        self.hotkey_manager.trigger_f2.connect(lambda: self.trigger_screenshot('window'))
        self.hotkey_manager.trigger_f3.connect(lambda: self.trigger_screenshot('edit'))
        self.hotkey_manager.trigger_f4.connect(lambda: self.trigger_screenshot('region'))

        # Snipping Tool
        self.snipping_tool.snipping_finished.connect(self.handle_region_capture)

        # Settings changes
        settings_manager.settings_changed.connect(self.on_settings_changed)

    # --- Screenshot Logic ---

    @Slot(str)
    def trigger_screenshot(self, mode):
        """Handles screenshot requests from hotkeys or toolbar."""
        # Strategy: Minimize window briefly for reliability (Windows specific)
        # This helps ensure we capture the intended foreground window, not our own app.
        if sys.platform == "win32":
            self.update_status(f"準備截圖 ({mode})...")
            
            # Store current state and minimize
            self.original_window_state = self.windowState()
            self.setWindowState(Qt.WindowState.WindowMinimized)
            QApplication.processEvents() # Process the minimize event
            
            # Wait for OS focus shift/minimization animation
            delay = 300 # milliseconds
        else:
             # macOS/Linux: Minimization might be slower or unnecessary, use shorter delay
             self.original_window_state = None
             delay = 100

        if mode == 'region':
                # Start the snipping tool after the delay
                QTimer.singleShot(delay, self.snipping_tool.start)
                # Window state will be restored in handle_region_capture
        else:
                # Execute capture after the delay
                QTimer.singleShot(delay, lambda: self.execute_capture(mode))

    def restore_window_state(self):
        """Restores the window state if it was minimized for screenshot."""
        if self.original_window_state is not None:
            self.setWindowState(self.original_window_state)
            self.activateWindow()
            self.original_window_state = None
        elif self.isMinimized():
            # Fallback if state tracking wasn't used (e.g., non-Windows platforms)
            self.showNormal()
            self.activateWindow()

    def execute_capture(self, mode):
        # This runs after the delay (if any)
        image_data = capture_active_window()
        
        # Restore window visibility
        self.restore_window_state()

        if image_data is not None:
            if mode == 'edit':
                self.open_editor(image_data)
            else:
                self.process_and_save(image_data)
        else:
            self.update_status("錯誤：無法截取當前視窗。請檢查權限或日誌。", is_error=True)

    @Slot(dict)
    def handle_region_capture(self, monitor_dict):
        # This is triggered when the snipping tool finishes
        # Restore window visibility immediately
        self.restore_window_state()
            
        # Small delay (50ms) to ensure the overlay is fully closed before capture
        QTimer.singleShot(50, lambda: self.finish_region_capture(monitor_dict))

    def finish_region_capture(self, monitor_dict):
        image_data = capture_region(monitor_dict)
        if image_data is not None:
            self.process_and_save(image_data)
        else:
            self.update_status("錯誤：無法截取指定範圍。請檢查權限或日誌。", is_error=True)

    # --- Image Processing (QThreadPool) ---

    def process_and_save(self, image_input: np.ndarray | QImage):
        """Starts the background worker for image processing."""
        self.update_status("正在背景處理並儲存影像...")
        # image_input can be NumPy array (from screenshot) or QImage (from editor)
        worker = ImageSaveWorker(image_input)
        worker.signals.finished.connect(self.on_image_saved)
        worker.signals.error.connect(self.on_image_error)
        # Start the worker in the background thread pool
        self.threadpool.start(worker)

    @Slot(str)
    def on_image_saved(self, path):
        self.queue_model.add_item(path)
        self.update_status(f"已加入待上傳區: {os.path.basename(path)}")

    @Slot(str)
    def on_image_error(self, error_message):
        self.update_status(f"影像儲存失敗: {error_message}", is_error=True)

    # --- Image Editor ---
    
    def open_editor(self, image_data: np.ndarray):
        # Ensure any previous editor instance is closed
        if self.editor_window and self.editor_window.isVisible():
            if not self.editor_window.close():
                # If user cancels closing (e.g., unsaved changes), stop opening a new one
                return

        # Create and show the new editor window
        self.editor_window = ImageEditorWindow(image_data, self)
        self.editor_window.image_saved.connect(self.on_editor_saved)
        self.editor_window.show()

    @Slot(QImage)
    def on_editor_saved(self, edited_qimage: QImage):
        # Process the QImage returned from the editor (save it)
        self.process_and_save(edited_qimage)

    # --- AI Analysis (Asyncio) ---

    def send_analysis_request(self):
        # Re-check API key before sending
        if not self.update_send_button_state():
            QMessageBox.warning(self, "API Key 未設定", self.send_button.toolTip())
            return

        selected_indexes = self.queue_view.selectionModel().selectedIndexes()
        
        # If nothing is selected, show warning
        if not selected_indexes:
            if self.queue_model.rowCount() == 0:
                self.update_status("請先截圖再進行分析。", is_error=True)
            else:
                QMessageBox.information(self, "提示", "請在左側待上傳區選擇要分析的圖片（可多選）。")
            return

        # Get paths in the correct visual order (handled by the model)
        image_paths = self.queue_model.get_paths_by_indexes(selected_indexes)
        user_text = self.user_input.toPlainText().strip()

        # Start the async task using the qasync event loop integration
        # We pass a copy (list(...)) to ensure indexes remain valid during async operation
        asyncio.create_task(self.run_analysis(image_paths, user_text, list(selected_indexes)))

    async def run_analysis(self, image_paths: list[str], user_text: str, uploaded_indexes: list):
        self.set_loading_state(True)
        # Use the ai_manager to determine the active provider for status update
        provider = ai_manager.active_provider
        self.update_status(f"開始分析請求 (使用 {provider})...")
        try:
            # Await the async analysis using the ai_manager
            result = await ai_manager.analyze(image_paths, user_text)
            self.on_analysis_finished(result, uploaded_indexes)
        except Exception as e:
            self.on_analysis_error(str(e))
        finally:
            self.set_loading_state(False)

    def on_analysis_finished(self, result: AnalysisResult, uploaded_indexes: list):
        self.update_status(f"分析完成。耗時: {result.response_time:.2f}s")
        
        # Display result by creating a card widget
        card = AnalysisCard(result)
        # Insert the new card at the top of the results layout
        self.results_layout.insertWidget(0, card)

        # Auto clear queue if configured in settings
        if settings_manager.get("General/AutoClearQueue"):
            # Clear the items that were successfully uploaded
            self.queue_model.remove_items(uploaded_indexes)
            self.user_input.clear() # Clear the input text box

    def on_analysis_error(self, error_message: str):
        self.update_status(f"分析失敗: {error_message}", is_error=True)
        QMessageBox.critical(self, "分析錯誤", f"請求 AI 分析時發生錯誤：\n\n{error_message}")

    # --- Utilities ---

    def update_status(self, message, is_error=False):
        # Show message in status bar for 5 seconds
        self.statusBar.showMessage(message, 5000)
        if is_error:
            logger.error(message)
        else:
            logger.info(message)

    def set_loading_state(self, is_loading):
        if is_loading:
            self.send_button.setEnabled(False)
            self.send_button.setText("分析中...")
        else:
            # When finished loading, double check API key validity before re-enabling
            self.update_send_button_state()
            self.send_button.setText("送出分析請求")

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()
        # SettingsManager emits settings_changed signal automatically upon saving

    def on_settings_changed(self):
        """Callback when settings are updated."""
        self.update_hotkey_display()
        # Only update button state if not currently loading
        if self.send_button.text() != "分析中...":
            self.update_send_button_state()
        # HotkeyManager and AIManager listen to this signal and reload automatically

    def update_send_button_state(self) -> bool:
        """Updates the send button based on the active provider's API key. Returns True if ready."""
        # Check the API key for the CURRENTLY ACTIVE provider
        active_provider = settings_manager.get("AI/Provider")
        
        is_ready = False
        try:
            api_key = settings_manager.get_api_key(active_provider)
            if not api_key:
                self.send_button.setEnabled(False)
                self.send_button.setToolTip(f"請先至「設定」配置 {active_provider} API Key")
            else:
                is_ready = True
                # Only enable if not currently loading
                if self.send_button.text() != "分析中...":
                    self.send_button.setEnabled(True)
                self.send_button.setToolTip("")
        except ValueError:
             # Handle case where provider name might be invalid
             self.send_button.setEnabled(False)
             self.send_button.setToolTip(f"無效的 AI 供應商: {active_provider}")
        
        return is_ready


    def update_hotkey_display(self):
        """Updates the toolbar button text with current hotkeys."""
        hk = settings_manager.get_hotkeys()

        self.action_f2.setText(f"截當前視窗 ({hk['F2'] or 'N/A'})")
        self.action_f3.setText(f"截並編輯 ({hk['F3'] or 'N/A'})")
        self.action_f4.setText(f"框選截圖 ({hk['F4'] or 'N/A'})")

        # Also set app-level shortcuts as fallback if global hotkeys fail
        try:
            self.action_f2.setShortcut(QKeySequence(hk['F2']))
            self.action_f3.setShortcut(QKeySequence(hk['F3']))
            self.action_f4.setShortcut(QKeySequence(hk['F4']))
        except Exception as e:
            logger.warning(f"Failed to set fallback application shortcuts: {e}")

    def show_queue_context_menu(self, position):
        indexes = self.queue_view.selectedIndexes()
        menu = QMenu()

        if indexes:
            action_delete = QAction("刪除選取項目", self)
            # Pass a copy of the list to ensure indexes remain valid if model changes
            action_delete.triggered.connect(lambda: self.queue_model.remove_items(list(indexes)))
            menu.addAction(action_delete)

            # Actions for single selection
            if len(indexes) == 1:
                path_role = Qt.ItemDataRole.UserRole + 1 # Corresponds to PathRole in UploadQueueModel
                path = self.queue_model.data(indexes[0], path_role)
                
                if path and os.path.exists(path):
                    action_open = QAction("開啟檔案", self)
                    action_open.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
                    menu.addAction(action_open)
                    
                    action_open_folder = QAction("開啟資料夾位置", self)
                    # Open the directory containing the file
                    action_open_folder.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))))
                    menu.addAction(action_open_folder)

        # Execute the menu at the global position mapped from the viewport
        if menu.actions():
            menu.exec(self.queue_view.viewport().mapToGlobal(position))

    def load_styles(self):
        try:
            # Determine the base directory for finding assets
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                # Bundled application (e.g., PyInstaller)
                base_dir = sys._MEIPASS
                style_path = os.path.join(base_dir, 'assets', 'styles.qss')
            else:
                # Running from source (assuming ui/ is sibling to assets/)
                script_dir = os.path.dirname(os.path.abspath(__file__))
                style_path = os.path.normpath(os.path.join(script_dir, '..', 'assets', 'styles.qss'))
            
            if os.path.exists(style_path):
                with open(style_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
            else:
                 logger.warning(f"styles.qss not found at {style_path}. Using default style.")
        except Exception as e:
            logger.warning(f"Error loading styles.qss: {e}")

    def closeEvent(self, event):
        # Ensure graceful shutdown
        logger.info("Shutting down application...")
        
        # Ensure the editor window is closed properly
        if self.editor_window and self.editor_window.isVisible():
            if not self.editor_window.close():
                # If the user cancels closing the editor, cancel closing the main app
                event.ignore()
                return

        self.hotkey_manager.stop()
        # Wait briefly (1 second) for running background tasks (like image saving) to finish
        if not self.threadpool.waitForDone(1000):
            logger.warning("Background tasks did not finish in time during shutdown.")
        event.accept()