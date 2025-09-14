# core/config.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import keyring
from PySide6.QtCore import QSettings, QStandardPaths, QObject, Signal


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


class SettingsManager(QObject):
    settings_changed = Signal()

    ORG_NAME = "FastDaytradeTools"
    SERVICE_NAME = "FastDaytradeAssistant"

    OPENAI_API_KEY_NAME = "OpenAI_APIKey"
    GEMINI_API_KEY_NAME = "Gemini_APIKey"

    DEFAULTS: Dict[str, Any] = {
        # 一般
        "General/AutoClearQueue": False,

        # 熱鍵
        "Hotkeys/F2": "F2",
        "Hotkeys/F3": "F3",
        "Hotkeys/F4": "F4",

        # 圖片
        "Image/Format": "PNG",
        "Image/MaxSize": 2048,
        "Image/RetainOriginal": True,

        # AI（通用）
        "AI/Provider": "OpenAI",
        "AI/Strategy": "Auto",
        "AI/Timeout": 60,        # 給 UI 使用
        "AI/TimeoutSec": 60,     # 若舊程式用這個 key 也能相容
        "AI/MaxImages": 5,

        # OpenAI / Gemini 模型預設
        "OpenAI/ModelFast": "gpt-4o-mini",
        "OpenAI/ModelDeep": "gpt-4o",
        "Gemini/ModelFast": "gemini-1.5-flash",
        "Gemini/ModelDeep": "gemini-1.5-pro",
    }

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._settings: Optional[QSettings] = None
        self._migrated: bool = False

    @property
    def settings(self) -> QSettings:
        if self._settings is None:
            self._settings = QSettings(
                QSettings.IniFormat, QSettings.UserScope,
                self.ORG_NAME, self.SERVICE_NAME
            )
            self._ensure_defaults()
            if not self._migrated:
                try:
                    self._migrate_old_settings()
                finally:
                    self._migrated = True
        return self._settings

    # ---- 基本 API（型別安全） ----
    def get(self, key: str, default: Any = None) -> Any:
        if default is None and key in self.DEFAULTS:
            default = self.DEFAULTS[key]
        return self.settings.value(key, default)

    def get_int(self, key: str, default: Optional[int] = None) -> int:
        v = self.get(key, default)
        try:
            return int(v)
        except Exception:
            return int(default or 0)

    def get_float(self, key: str, default: Optional[float] = None) -> float:
        v = self.get(key, default)
        try:
            return float(v)
        except Exception:
            return float(default or 0.0)

    def get_bool(self, key: str, default: Optional[bool] = None) -> bool:
        if default is None and key in self.DEFAULTS:
            default = bool(self.DEFAULTS[key])
        v = self.get(key, default)
        return _to_bool(v)

    def set(self, key: str, value: Any) -> None:
        self.settings.setValue(key, value)

    def set_many(self, pairs: Dict[str, Any]) -> None:
        s = self.settings
        for k, v in pairs.items():
            s.setValue(k, v)

    def remove(self, key: str) -> None:
        self.settings.remove(key)

    def clear_all(self) -> None:
        self.settings.clear()
        self.save_and_emit()

    def save_and_emit(self) -> None:
        if self._settings is not None:
            self._settings.sync()
        self._settings = None
        self.settings_changed.emit()

    # ---- 業務便利 ----
    def get_hotkeys(self) -> Dict[str, str]:
        return {
            "F2": str(self.get("Hotkeys/F2")),
            "F3": str(self.get("Hotkeys/F3")),
            "F4": str(self.get("Hotkeys/F4")),
        }

    def get_image_settings(self) -> Dict[str, Any]:
        return {
            "format": str(self.get("Image/Format")),
            "max_size": self.get_int("Image/MaxSize"),
            "retain_original": self.get_bool("Image/RetainOriginal"),
        }

    # 儲存路徑
    def _compute_default_save_dir(self) -> str:
        pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        base = pictures or documents or os.path.expanduser("~")
        path = os.path.join(base, self.SERVICE_NAME)
        return os.path.normpath(path)

    def get_save_path(self) -> str:
        path = str(self.get("Paths/SaveDir", "") or "").strip()
        if not path:
            path = self._compute_default_save_dir()
            self.set("Paths/SaveDir", path)
            if self._settings is not None:
                self._settings.sync()
        path = os.path.expandvars(os.path.expanduser(path))
        os.makedirs(path, exist_ok=True)
        return os.path.normpath(path)

    def set_save_path(self, path: str) -> None:
        if not path:
            return
        path = os.path.expandvars(os.path.expanduser(path))
        os.makedirs(path, exist_ok=True)
        self.set("Paths/SaveDir", os.path.normpath(path))

    # ---- 金鑰（keyring） ----
    def get_api_key(self, provider: str) -> Optional[str]:
        name = self._key_name_for_provider(provider)
        if not name:
            return None
        try:
            return keyring.get_password(self.SERVICE_NAME, name)
        except Exception:
            return None

    def set_api_key(self, provider: str, value: Optional[str]) -> None:
        name = self._key_name_for_provider(provider)
        if not name:
            return
        try:
            if value:
                keyring.set_password(self.SERVICE_NAME, name, value)
            else:
                keyring.delete_password(self.SERVICE_NAME, name)
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception:
            pass

    def _key_name_for_provider(self, provider: str) -> Optional[str]:
        p = (provider or "").strip().lower()
        if p in ("openai", "oai"):
            return self.OPENAI_API_KEY_NAME
        if p in ("gemini", "google", "vertex"):
            return self.GEMINI_API_KEY_NAME
        return None

    # ---- 初始化 / 遷移 ----
    def _ensure_defaults(self) -> None:
        s = self._settings
        if s is None:
            return
        for k, v in self.DEFAULTS.items():
            if s.value(k, None) is None:
                s.setValue(k, v)
        if s.value("Paths/SaveDir", None) is None:
            s.setValue("Paths/SaveDir", self._compute_default_save_dir())
        s.sync()

    def _migrate_old_settings(self) -> None:
        """
        遷移舊鍵：
        - General/SavePath -> Paths/SaveDir
        """
        s = self._settings
        if s is None:
            return
        old = s.value("General/SavePath", None)
        if old:
            s.setValue("Paths/SaveDir", old)
            s.remove("General/SavePath")
            s.sync()


settings_manager = SettingsManager()
