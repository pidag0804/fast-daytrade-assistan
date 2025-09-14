# ui/settings_dialog.py
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QWidget, QFormLayout, QLineEdit,
    QPushButton, QSpinBox, QComboBox, QCheckBox, QFileDialog, QMessageBox,
    QKeySequenceEdit, QHBoxLayout, QLabel, QGroupBox
)
from PySide6.QtGui import QKeySequence
from core.config import settings_manager

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumSize(600, 650)
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        self.init_general_tab()
        self.init_hotkeys_tab()
        self.init_ai_tab()

        self.layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("儲存並套用")
        self.btn_save.clicked.connect(self.save_settings)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        self.layout.addLayout(btn_layout)

    def init_general_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)
        self.tabs.addTab(tab, "一般與影像")

        self.le_save_path = QLineEdit()
        self.btn_browse = QPushButton("瀏覽...")
        self.btn_browse.clicked.connect(self.browse_save_path)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.le_save_path)
        path_layout.addWidget(self.btn_browse)
        layout.addRow("截圖儲存資料夾:", path_layout)

        self.cb_image_format = QComboBox()
        self.cb_image_format.addItems(["WebP", "PNG", "JPEG"])
        layout.addRow("影像格式 (建議 WebP):", self.cb_image_format)

        self.sb_max_size = QSpinBox()
        self.sb_max_size.setRange(500, 4000)
        self.sb_max_size.setSingleStep(100)
        self.sb_max_size.setSuffix(" px")
        layout.addRow("最大邊長 (降低延遲):", self.sb_max_size)

        self.chk_retain_original = QCheckBox("儲存壓縮檔時，同時保留原始未壓縮 PNG 檔")
        layout.addRow("保留原始檔:", self.chk_retain_original)

        self.chk_auto_clear = QCheckBox("上傳成功後自動清空對應的待上傳項目")
        layout.addRow("自動清除:", self.chk_auto_clear)

    def init_hotkeys_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)
        self.tabs.addTab(tab, "熱鍵")

        layout.addRow(QLabel("點擊輸入框後，按下您想要的組合鍵。"))

        self.kse_f2 = QKeySequenceEdit()
        layout.addRow("截取當前視窗 (F2):", self.kse_f2)

        self.kse_f3 = QKeySequenceEdit()
        layout.addRow("截取並編輯 (F3):", self.kse_f3)

        self.kse_f4 = QKeySequenceEdit()
        layout.addRow("框選範圍截圖 (F4):", self.kse_f4)

        layout.addRow(QLabel("注意: 熱鍵變更將在儲存後立即套用。"))

    def init_ai_tab(self):
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        self.tabs.addTab(tab, "AI 模型設定")

        general_group = QGroupBox("通用設定")
        general_layout = QFormLayout(general_group)

        self.cb_provider = QComboBox()
        self.cb_provider.addItems(["OpenAI", "Gemini"])
        general_layout.addRow("主要 AI 供應商:", self.cb_provider)

        self.cb_strategy = QComboBox()
        self.cb_strategy.addItems(["Auto (自動)", "Fast (快速)", "Deep (深度)"])
        general_layout.addRow("速度策略:", self.cb_strategy)

        self.sb_timeout = QSpinBox()
        self.sb_timeout.setRange(1, 120)
        self.sb_timeout.setSuffix(" 秒")
        general_layout.addRow("最長等待秒數 (Timeout):", self.sb_timeout)

        self.sb_max_images = QSpinBox()
        self.sb_max_images.setRange(1, 20)
        general_layout.addRow("最大同時上傳圖片張數:", self.sb_max_images)

        main_layout.addWidget(general_group)

        providers_layout = QHBoxLayout()

        openai_group = QGroupBox("OpenAI 設定")
        openai_layout = QFormLayout(openai_group)
        self.le_openai_api_key = QLineEdit()
        self.le_openai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        openai_layout.addRow("API Key:", self.le_openai_api_key)
        self.le_openai_model_fast = QLineEdit()
        openai_layout.addRow("快速模型:", self.le_openai_model_fast)
        self.le_openai_model_deep = QLineEdit()
        openai_layout.addRow("深度模型:", self.le_openai_model_deep)
        providers_layout.addWidget(openai_group)

        gemini_group = QGroupBox("Gemini 設定")
        gemini_layout = QFormLayout(gemini_group)
        self.le_gemini_api_key = QLineEdit()
        self.le_gemini_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        gemini_layout.addRow("API Key:", self.le_gemini_api_key)
        self.le_gemini_model_fast = QLineEdit()
        gemini_layout.addRow("快速模型 (Flash):", self.le_gemini_model_fast)
        self.le_gemini_model_deep = QLineEdit()
        gemini_layout.addRow("深度模型 (Pro):", self.le_gemini_model_deep)
        providers_layout.addWidget(gemini_group)

        main_layout.addLayout(providers_layout)
        main_layout.addStretch()

    def browse_save_path(self):
        base = self.le_save_path.text().strip() or settings_manager.get_save_path()
        path = QFileDialog.getExistingDirectory(self, "選擇儲存資料夾", base)
        if path:
            self.le_save_path.setText(path)

    # ---- Load & Save ----

    def load_settings(self):
        # 一般
        self.le_save_path.setText(settings_manager.get_save_path())
        self.cb_image_format.setCurrentText(str(settings_manager.get("Image/Format") or "PNG"))
        self.sb_max_size.setValue(settings_manager.get_int("Image/MaxSize", 2048))
        self.chk_retain_original.setChecked(settings_manager.get_bool("Image/RetainOriginal", True))
        self.chk_auto_clear.setChecked(settings_manager.get_bool("General/AutoClearQueue", False))

        # 熱鍵
        self.kse_f2.setKeySequence(QKeySequence(str(settings_manager.get("Hotkeys/F2") or "F2")))
        self.kse_f3.setKeySequence(QKeySequence(str(settings_manager.get("Hotkeys/F3") or "F3")))
        self.kse_f4.setKeySequence(QKeySequence(str(settings_manager.get("Hotkeys/F4") or "F4")))

        # AI - 通用
        self.cb_provider.setCurrentText(str(settings_manager.get("AI/Provider") or "OpenAI"))
        strategy = str(settings_manager.get("AI/Strategy") or "Auto")
        self.cb_strategy.setCurrentIndex({"Auto": 0, "Fast": 1, "Deep": 2}.get(strategy, 0))
        timeout = settings_manager.get_int("AI/Timeout", settings_manager.get_int("AI/TimeoutSec", 60))
        self.sb_timeout.setValue(timeout)
        self.sb_max_images.setValue(settings_manager.get_int("AI/MaxImages", 5))

        # AI - OpenAI
        self.current_openai_key = settings_manager.get_api_key("OpenAI") or ""
        if self.current_openai_key:
            self.le_openai_api_key.setText(self.current_openai_key)
            self.le_openai_api_key.setPlaceholderText("已設定")
        self.le_openai_model_fast.setText(str(settings_manager.get("OpenAI/ModelFast") or "gpt-4o-mini"))
        self.le_openai_model_deep.setText(str(settings_manager.get("OpenAI/ModelDeep") or "gpt-4o"))

        # AI - Gemini
        self.current_gemini_key = settings_manager.get_api_key("Gemini") or ""
        if self.current_gemini_key:
            self.le_gemini_api_key.setText(self.current_gemini_key)
            self.le_gemini_api_key.setPlaceholderText("已設定")
        self.le_gemini_model_fast.setText(str(settings_manager.get("Gemini/ModelFast") or "gemini-1.5-flash"))
        self.le_gemini_model_deep.setText(str(settings_manager.get("Gemini/ModelDeep") or "gemini-1.5-pro"))

    def save_settings(self):
        try:
            # 一般
            settings_manager.set_save_path(self.le_save_path.text())
            settings_manager.set("Image/Format", self.cb_image_format.currentText())
            settings_manager.set("Image/MaxSize", self.sb_max_size.value())
            settings_manager.set("Image/RetainOriginal", self.chk_retain_original.isChecked())
            settings_manager.set("General/AutoClearQueue", self.chk_auto_clear.isChecked())

            # 熱鍵
            settings_manager.set("Hotkeys/F2", self.kse_f2.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
            settings_manager.set("Hotkeys/F3", self.kse_f3.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
            settings_manager.set("Hotkeys/F4", self.kse_f4.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

            # AI - 通用
            settings_manager.set("AI/Provider", self.cb_provider.currentText())
            strategy = ["Auto", "Fast", "Deep"][self.cb_strategy.currentIndex()]
            settings_manager.set("AI/Strategy", strategy)
            settings_manager.set("AI/Timeout", self.sb_timeout.value())
            settings_manager.set("AI/TimeoutSec", self.sb_timeout.value())  # 舊程式相容
            settings_manager.set("AI/MaxImages", self.sb_max_images.value())

            # AI - OpenAI
            new_openai_key = self.le_openai_api_key.text().strip()
            if new_openai_key != (self.current_openai_key or ""):
                settings_manager.set_api_key("OpenAI", new_openai_key or None)
            settings_manager.set("OpenAI/ModelFast", self.le_openai_model_fast.text().strip())
            settings_manager.set("OpenAI/ModelDeep", self.le_openai_model_deep.text().strip())

            # AI - Gemini
            new_gemini_key = self.le_gemini_api_key.text().strip()
            if new_gemini_key != (self.current_gemini_key or ""):
                settings_manager.set_api_key("Gemini", new_gemini_key or None)
            settings_manager.set("Gemini/ModelFast", self.le_gemini_model_fast.text().strip())
            settings_manager.set("Gemini/ModelDeep", self.le_gemini_model_deep.text().strip())

            settings_manager.save_and_emit()
            QMessageBox.information(self, "成功", "設定已儲存並套用。")
            self.accept()
        except RuntimeError as e:
            QMessageBox.critical(self, "儲存錯誤", str(e))
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"儲存設定時發生未知錯誤: {e}")
