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
        self.setMinimumSize(600, 650) # Increased height slightly
        # It is crucial that init_ui() runs before load_settings()
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # Initialize ALL tabs here
        self.init_general_tab()
        self.init_hotkeys_tab()
        self.init_ai_tab()

        self.layout.addWidget(self.tabs)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("儲存並套用")
        self.btn_save.clicked.connect(self.save_settings)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        self.layout.addLayout(btn_layout)

    # --- Tab Initialization Methods ---

    def init_general_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)
        self.tabs.addTab(tab, "一般與影像")

        # Save Path
        self.le_save_path = QLineEdit()
        self.btn_browse = QPushButton("瀏覽...")
        self.btn_browse.clicked.connect(self.browse_save_path)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.le_save_path)
        path_layout.addWidget(self.btn_browse)
        layout.addRow("截圖儲存資料夾:", path_layout)

        # Image Settings
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

        # Use QKeySequenceEdit for easy hotkey capture
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

        # --- General AI Settings Group ---
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

        # --- Provider Specific Settings (Side-by-side) ---
        providers_layout = QHBoxLayout()

        # OpenAI Group
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

        # Gemini Group
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
        path = QFileDialog.getExistingDirectory(self, "選擇儲存資料夾", self.le_save_path.text())
        if path:
            self.le_save_path.setText(path)

    # --- Load and Save Logic (Crucial Fix) ---

    def load_settings(self):
        # --- General Tab Loading ---
        self.le_save_path.setText(settings_manager.get_save_path())
        self.cb_image_format.setCurrentText(settings_manager.get("Image/Format"))
        # Config ensures values are correctly typed (int/bool) via the get() method
        self.sb_max_size.setValue(settings_manager.get("Image/MaxSize")) 
        self.chk_retain_original.setChecked(settings_manager.get("Image/RetainOriginal"))
        self.chk_auto_clear.setChecked(settings_manager.get("General/AutoClearQueue"))

        # --- Hotkeys Tab Loading ---
        self.kse_f2.setKeySequence(QKeySequence(settings_manager.get("Hotkeys/F2")))
        self.kse_f3.setKeySequence(QKeySequence(settings_manager.get("Hotkeys/F3")))
        self.kse_f4.setKeySequence(QKeySequence(settings_manager.get("Hotkeys/F4")))

        # --- AI Tab Loading ---
        # General
        self.cb_provider.setCurrentText(settings_manager.get("AI/Provider"))
        strategy = settings_manager.get("AI/Strategy")
        if strategy == "Auto": self.cb_strategy.setCurrentIndex(0)
        elif strategy == "Fast": self.cb_strategy.setCurrentIndex(1)
        elif strategy == "Deep": self.cb_strategy.setCurrentIndex(2)
            
        self.sb_timeout.setValue(settings_manager.get("AI/Timeout"))
        self.sb_max_images.setValue(settings_manager.get("AI/MaxImages"))

        # OpenAI
        self.current_openai_key = settings_manager.get_api_key("OpenAI")
        if self.current_openai_key:
            self.le_openai_api_key.setText(self.current_openai_key)
            self.le_openai_api_key.setPlaceholderText("已設定")
        
        self.le_openai_model_fast.setText(settings_manager.get("OpenAI/ModelFast"))
        self.le_openai_model_deep.setText(settings_manager.get("OpenAI/ModelDeep"))

        # Gemini
        self.current_gemini_key = settings_manager.get_api_key("Gemini")
        if self.current_gemini_key:
            self.le_gemini_api_key.setText(self.current_gemini_key)
            self.le_gemini_api_key.setPlaceholderText("已設定")
        
        self.le_gemini_model_fast.setText(settings_manager.get("Gemini/ModelFast"))
        self.le_gemini_model_deep.setText(settings_manager.get("Gemini/ModelDeep"))


    def save_settings(self):
        try:
            # --- General Tab Saving ---
            settings_manager.set("General/SavePath", self.le_save_path.text())
            settings_manager.set("Image/Format", self.cb_image_format.currentText())
            settings_manager.set("Image/MaxSize", self.sb_max_size.value())
            settings_manager.set("Image/RetainOriginal", self.chk_retain_original.isChecked())
            settings_manager.set("General/AutoClearQueue", self.chk_auto_clear.isChecked())

            # --- Hotkeys Tab Saving ---
            settings_manager.set("Hotkeys/F2", self.kse_f2.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
            settings_manager.set("Hotkeys/F3", self.kse_f3.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
            settings_manager.set("Hotkeys/F4", self.kse_f4.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

            # --- AI Tab Saving ---
            # General
            settings_manager.set("AI/Provider", self.cb_provider.currentText())
            strategy_index = self.cb_strategy.currentIndex()
            strategy = ["Auto", "Fast", "Deep"][strategy_index]
            settings_manager.set("AI/Strategy", strategy)
            settings_manager.set("AI/Timeout", self.sb_timeout.value())
            settings_manager.set("AI/MaxImages", self.sb_max_images.value())

            # OpenAI
            new_openai_key = self.le_openai_api_key.text().strip()
            if new_openai_key != self.current_openai_key:
                # Handle API Key saving separately (uses keyring)
                settings_manager.set_api_key("OpenAI", new_openai_key)

            # Ensure we are reading from the correct UI elements
            settings_manager.set("OpenAI/ModelFast", self.le_openai_model_fast.text().strip())
            settings_manager.set("OpenAI/ModelDeep", self.le_openai_model_deep.text().strip())

            # Gemini
            new_gemini_key = self.le_gemini_api_key.text().strip()
            if new_gemini_key != self.current_gemini_key:
                settings_manager.set_api_key("Gemini", new_gemini_key)

            # Ensure we are reading from the correct UI elements
            settings_manager.set("Gemini/ModelFast", self.le_gemini_model_fast.text().strip())
            settings_manager.set("Gemini/ModelDeep", self.le_gemini_model_deep.text().strip())

            # Save all QSettings changes and emit the signal
            settings_manager.save_and_emit()

            QMessageBox.information(self, "成功", "設定已儲存並套用。")
            self.accept()
        except RuntimeError as e:
            # Catch errors specifically from set_api_key
            QMessageBox.critical(self, "儲存錯誤", str(e))
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"儲存設定時發生未知錯誤: {e}")