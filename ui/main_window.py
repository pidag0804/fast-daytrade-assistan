# ui/main_window.py
from __future__ import annotations

import sys
import os
import logging
import asyncio
import re
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, QSize, QItemSelectionModel, QRect, QPoint
from PySide6.QtGui import QKeySequence, QImage, QPixmap, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QListView,
    QTextEdit, QPushButton, QToolBar, QStatusBar, QApplication, QLabel,
    QMenu, QMessageBox, QScrollArea, QLineEdit, QFormLayout
)

from core.config import settings_manager
from core.hotkeys import HotkeyManager
from core.screenshot import capture_active_window, capture_region
from core.imaging import ImageSaveOptions, save_image_async
from core.ai_client.manager import ai_manager
from core.models import AnalysisResult

from ui.queue_model import UploadQueueModel, THUMBNAIL_SIZE
from ui.settings_dialog import SettingsDialog
from ui.widgets import SnippingTool, AnalysisCard

logger = logging.getLogger(__name__)

class _OverlaySnip(QWidget):
    def __init__(self, on_done):
        super().__init__(flags=Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowFullScreen)
        self._on_done = on_done
        from PySide6.QtWidgets import QRubberBand
        self._rubber = QRubberBand(QRubberBand.Rectangle, self)
        self._origin = QPoint()
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, e):
        self._origin = e.pos()
        self._rubber.setGeometry(QRect(self._origin, self._origin))
        self._rubber.show()

    def mouseMoveEvent(self, e):
        self._rubber.setGeometry(QRect(self._origin, e.pos()).normalized())

    def mouseReleaseEvent(self, e):
        rect = QRect(self._origin, e.pos()).normalized()
        self._rubber.hide()
        region = {"left": rect.left(), "top": rect.top(), "width": rect.width(), "height": rect.height()}
        self.close()
        self._on_done(region)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("股票當沖詢問工具 (Fast Daytrade Assistant)")
        self.resize(1300, 880)

        if not logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            logger.addHandler(h)
            logger.setLevel(logging.INFO)
        logger.propagate = False

        self.hotkey_manager = HotkeyManager(self)
        self.queue_model = UploadQueueModel(self)
        self.snipping_tool = SnippingTool()
        self.editor_window = None
        self._saved_state = None

        self._build_ui()
        self._connect()
        self.set_loading_state(False)
        self.on_settings_changed()
        logger.info("就緒")

    # ---------- UI ----------
    def _build_ui(self):
        main = QWidget(); self.setCentralWidget(main)
        layout = QHBoxLayout(main)
        splitter = QSplitter(Qt.Horizontal); layout.addWidget(splitter)

        # 左側：待上傳
        qpanel = QWidget(); ql = QVBoxLayout(qpanel)
        ql.addWidget(QLabel("待上傳區 (可拖曳排序、多選)"))
        self.queue_view = QListView()
        self.queue_view.setModel(self.queue_model)
        self.queue_view.setViewMode(QListView.IconMode)
        self.queue_view.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.queue_view.setGridSize(QSize(THUMBNAIL_SIZE + 20, THUMBNAIL_SIZE + 30))
        self.queue_view.setResizeMode(QListView.Adjust)
        self.queue_view.setSpacing(6)
        self.queue_view.setDragEnabled(True)
        self.queue_view.setAcceptDrops(True)
        self.queue_view.setDropIndicatorShown(True)
        self.queue_view.setDragDropMode(QListView.InternalMove)
        self.queue_view.setSelectionMode(QListView.ExtendedSelection)
        self.queue_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue_view.customContextMenuRequested.connect(self._queue_menu)
        ql.addWidget(self.queue_view)
        splitter.addWidget(qpanel)

        # 右側：結果 + 請求
        rpanel = QWidget(); rl = QVBoxLayout(rpanel)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self.results_container = QWidget(); self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.results_container)
        rl.addWidget(scroll, 1)

        self.user_input = QTextEdit(); self.user_input.setPlaceholderText("補充說明（例如持倉成本、消息）...")
        self.user_input.setMaximumHeight(80)
        rl.addWidget(self.user_input)

        # 股票 meta
        meta_box = QWidget(); meta_form = QFormLayout(meta_box)
        self.ed_symbol = QLineEdit(); self.ed_symbol.setPlaceholderText("例：2330")
        self.ed_name = QLineEdit(); self.ed_name.setPlaceholderText("例：台積電")
        meta_form.addRow("股票代號：", self.ed_symbol)
        meta_form.addRow("股票名稱：", self.ed_name)
        rl.addWidget(meta_box)

        self.send_button = QPushButton("送出分析請求")
        self.send_button.clicked.connect(self.send_analysis_request)
        rl.addWidget(self.send_button)
        splitter.addWidget(rpanel)

        splitter.setSizes([360, 980])

        # 工具列
        tb = QToolBar("Main"); self.addToolBar(tb)
        act_f2 = QAction("截當前視窗", self); act_f2.triggered.connect(lambda: self._trigger_screenshot("window")); tb.addAction(act_f2)
        act_f3 = QAction("截並編輯", self); act_f3.triggered.connect(lambda: self._trigger_screenshot("edit")); tb.addAction(act_f3)
        act_f4 = QAction("框選截圖", self); act_f4.triggered.connect(lambda: self._trigger_screenshot("region")); tb.addAction(act_f4)
        tb.addSeparator()
        act_clear = QAction("清空待上傳", self); act_clear.triggered.connect(self.queue_model.clear_queue); tb.addAction(act_clear)
        act_settings = QAction("設定", self); act_settings.triggered.connect(self.open_settings); tb.addAction(act_settings)

        # 快捷鍵備援
        for key, cb in (("F3", lambda: self._trigger_screenshot("edit")),
                        ("F4", lambda: self._trigger_screenshot("region"))):
            qs = QAction(self); qs.setShortcut(QKeySequence(key)); qs.triggered.connect(cb); self.addAction(qs)

        self.statusBar = QStatusBar(); self.setStatusBar(self.statusBar)

    def _connect(self):
        try:
            self.hotkey_manager.trigger_f2.connect(lambda: self._trigger_screenshot("window"))
            self.hotkey_manager.trigger_f3.connect(lambda: self._trigger_screenshot("edit"))
            self.hotkey_manager.trigger_f4.connect(lambda: self._trigger_screenshot("region"))
            self.hotkey_manager.start(["<f3>", "<f4>"])
        except Exception as e:
            logger.warning("全域熱鍵初始化失敗，將僅使用視窗內快捷鍵：%s", e)

        try:
            self.snipping_tool.snipping_finished.connect(self._handle_region_capture)
        except Exception:
            pass

        settings_manager.settings_changed.connect(self.on_settings_changed)

    # ---------- 截圖 ----------
    def _trigger_screenshot(self, mode: str):
        if sys.platform == "win32":
            self._saved_state = self.windowState()
            self.setWindowState(Qt.WindowMinimized)
            QApplication.processEvents()
            delay = 300
        else:
            self._saved_state = None
            delay = 120

        if mode == "region":
            QTimer.singleShot(delay, self._start_snipping_tool)
        else:
            QTimer.singleShot(delay, lambda: self._do_capture(mode))

    def _restore_window(self):
        if self._saved_state is not None:
            self.setWindowState(self._saved_state)
            self.activateWindow()
            self._saved_state = None
        elif self.isMinimized():
            self.showNormal(); self.activateWindow()

    def _start_snipping_tool(self):
        st = self.snipping_tool
        for name in ("start", "begin", "activate", "show"):
            if hasattr(st, name) and callable(getattr(st, name)):
                getattr(st, name)()
                return
        def _done(region_dict):
            self._finish_region_capture(region_dict)
        ov = _OverlaySnip(_done)
        ov.show()

    def _do_capture(self, mode: str):
        try:
            img = capture_active_window()
            self._restore_window()
            if img is None or (isinstance(img, QPixmap) and img.isNull()):
                raise RuntimeError("無法截取當前視窗。")
            if mode == "edit":
                self._open_editor(img)
            else:
                self._process_and_save(img)
        except Exception as e:
            logger.exception("截圖失敗：%s", e)
            QMessageBox.critical(self, "截圖失敗", str(e))

    def _handle_region_capture(self, monitor_dict: dict):
        self._restore_window()
        QTimer.singleShot(50, lambda: self._finish_region_capture(monitor_dict))

    def _finish_region_capture(self, monitor_dict: dict):
        img = capture_region(monitor_dict)
        if img is None or (isinstance(img, QPixmap) and img.isNull()):
            self._status("錯誤：無法截取指定範圍。", True)
            return
        self._process_and_save(img)

    # ---------- 儲存與加入佇列 ----------
    def _nd_to_qimage(self, arr: np.ndarray) -> QImage:
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        h, w = arr.shape[:2]
        if arr.ndim == 3 and arr.shape[2] == 3:
            return QImage(arr.data, w, h, 3*w, QImage.Format_RGB888).copy()
        if arr.ndim == 3 and arr.shape[2] == 4:
            return QImage(arr.data, w, h, 4*w, QImage.Format_RGBA8888).copy()
        raise ValueError(f"Unsupported ndarray shape: {arr.shape}")

    def _process_and_save(self, image_input):
        try:
            img_obj = image_input
            if isinstance(image_input, np.ndarray):
                img_obj = self._nd_to_qimage(image_input)

            base_dir = settings_manager.get("Capture/Directory") or str(Path.home() / "Pictures" / "FastDaytradeAssistant")
            opts = ImageSaveOptions(base_dir=base_dir, preferred_ext="webp", use_date_subdir=True, prefix="")

            def on_started(): self._status("正在背景處理並儲存影像...")
            def on_done(path: str, ms: float):
                logger.info("Image saved in %.2f ms: %s", ms, path)
                self._on_image_saved(path)
            def on_error(msg: str):
                logger.error("存檔失敗: %s", msg)
                QMessageBox.critical(self, "存檔失敗", msg)

            save_image_async(img_obj, opts, on_started=on_started, on_done=on_done, on_error=on_error)
        except Exception as e:
            logger.exception("process/save 例外：%s", e)
            QMessageBox.critical(self, "錯誤", str(e))

    def _on_image_saved(self, path: str):
        self.queue_model.add_item(path)
        try:
            sel = self.queue_view.selectionModel()
            if sel:
                sel.clearSelection()
                idx = self.queue_model.index(0, 0)
                self.queue_view.setCurrentIndex(idx)
                sel.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                self.queue_view.scrollTo(idx)
        except Exception:
            pass
        self._status(f"已加入待上傳區: {os.path.basename(path)}")
        # 嘗試從檔名自動帶出代號/名稱（若尚未填）
        if not self.ed_symbol.text().strip() or not self.ed_name.text().strip():
            self._auto_fill_symbol_name([path])

    # ---------- 編輯器 ----------
    def _open_editor(self, image):
        from ui.editor.editor_window import ImageEditorWindow
        if hasattr(self, "editor_window") and self.editor_window and self.editor_window.isVisible():
            if not self.editor_window.close():
                return
        self.editor_window = ImageEditorWindow(image, self)
        self.editor_window.image_saved.connect(lambda qimg: self._process_and_save(qimg))
        self.editor_window.show()

    # ---------- 分析 ----------
    def send_analysis_request(self):
        if not self._update_send_ready():
            QMessageBox.warning(self, "API Key 未設定", self.send_button.toolTip() or "請先至「設定」配置 API Key")
            return

        sel = self.queue_view.selectionModel()
        idxs = sel.selectedIndexes() if sel else []
        if not idxs and self.queue_model.rowCount() > 0:
            idxs = [self.queue_model.index(0, 0)]
            if sel:
                sel.setCurrentIndex(idxs[0], QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        if not idxs:
            self._status("請先截圖再分析。", True); return

        image_paths = self.queue_model.get_paths_by_indexes(idxs)

        # 構造 meta：股票代號/名稱
        symbol = self.ed_symbol.text().strip() or ""
        name = self.ed_name.text().strip() or ""
        if not symbol or not name:
            guess_sym, guess_name = self._guess_symbol_name_from_paths(image_paths)
            if not symbol and guess_sym: symbol = guess_sym
            if not name and guess_name: name = guess_name
            if symbol and not self.ed_symbol.text().strip(): self.ed_symbol.setText(symbol)
            if name and not self.ed_name.text().strip(): self.ed_name.setText(name)

        meta_line = ""
        if symbol or name:
            meta_line = f"【股票】代號={symbol or 'null'}; 名稱={name or 'null'}\n"

        # 使用者補充
        user_text = self.user_input.toPlainText().strip()
        # 不再加入「分析模式」，AI 端已固定要求包含「當沖方案」

        payload_text = (meta_line + user_text) if meta_line else user_text

        self.set_loading_state(True)
        prov = settings_manager.get("AI/Provider") or "OpenAI"
        self._status(f"開始分析請求 (使用 {prov})...")
        asyncio.create_task(self._run_analysis(image_paths, payload_text))

    async def _run_analysis(self, image_paths: list[str], user_text: str):
        try:
            result: AnalysisResult = await ai_manager.analyze(image_paths, user_text)
            self._status(f"分析完成。耗時: {result.response_time:.2f}s")
            card = AnalysisCard(result)
            self.results_layout.insertWidget(0, card)
            if settings_manager.get("General/AutoClearQueue"):
                sel = self.queue_view.selectionModel()
                idxs = sel.selectedIndexes() if sel else []
                self.queue_model.remove_items(idxs)
                self.user_input.clear()
        except Exception as e:
            self._status(f"分析失敗: {e}", True)
            QMessageBox.critical(self, "分析錯誤", f"請求 AI 分析時發生錯誤：\n\n{e}")
        finally:
            self.set_loading_state(False)

    # ---------- 設定視窗 ----------
    def open_settings(self):
        try:
            dlg = SettingsDialog(self)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "設定", f"無法開啟設定視窗：{e}")

    # ---------- 雜項 ----------
    def _queue_menu(self, pos):
        indexes = self.queue_view.selectedIndexes()
        menu = QMenu(self)
        if indexes:
            act_del = QAction("刪除選取", self); act_del.triggered.connect(lambda: self.queue_model.remove_items(list(indexes))); menu.addAction(act_del)
        if menu.actions():
            menu.exec(self.queue_view.viewport().mapToGlobal(pos))

    def on_settings_changed(self):
        self._update_send_ready()

    def _update_send_ready(self) -> bool:
        prov = settings_manager.get("AI/Provider") or "OpenAI"
        try:
            api_key = settings_manager.get_api_key(prov)
            ready = bool(api_key)
            self.send_button.setToolTip("" if ready else f"請先至「設定」配置 {prov} API Key")
            return ready
        except Exception:
            self.send_button.setToolTip(f"無效的 AI 供應商: {prov}")
            return False

    def set_loading_state(self, loading: bool):
        self.send_button.setEnabled(not loading)
        self.send_button.setText("分析中..." if loading else "送出分析請求")

    def _status(self, msg: str, err: bool = False):
        self.statusBar.showMessage(msg, 5000)
        (logger.error if err else logger.info)(msg)

    def closeEvent(self, e):
        try:
            self.hotkey_manager.stop()
        except Exception:
            pass
        super().closeEvent(e)

    # ---------- 代號/名稱猜測 ----------
    def _auto_fill_symbol_name(self, paths: list[str]):
        sym, name = self._guess_symbol_name_from_paths(paths)
        if sym and not self.ed_symbol.text().strip():
            self.ed_symbol.setText(sym)
        if name and not self.ed_name.text().strip():
            self.ed_name.setText(name)

    def _guess_symbol_name_from_paths(self, paths: list[str]) -> tuple[str | None, str | None]:
        sym = None
        name = None
        for p in paths:
            fname = os.path.basename(p)
            base, _ = os.path.splitext(fname)
            m = re.search(r'(?<!\d)(\d{4})(?!\d)', base)
            if m and not sym:
                sym = m.group(1)
            tmp = re.sub(r'[\d_@()\-\[\]{}]+', ' ', base)
            tmp = re.sub(r'\s+', ' ', tmp).strip()
            m2 = re.search(r'([A-Za-z]{2,}|[\u4e00-\u9fa5]{2,})', tmp)
            if m2 and not name:
                name = m2.group(1)
            if sym and name:
                break
        return sym, name
