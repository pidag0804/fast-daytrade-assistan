# core/config.py
import os
import sys
import keyring
from PySide6.QtCore import QSettings, QStandardPaths, QObject, Signal

class SettingsManager(QObject):
    """Manages application settings and secure storage."""
    settings_changed = Signal()
    
    SERVICE_NAME = "FastDaytradeAssistant"
    # Update API Key names to be provider-specific
    OPENAI_API_KEY_NAME = "OpenAI_APIKey"
    GEMINI_API_KEY_NAME = "Gemini_APIKey"

    # Default Settings (Updated structure)
    DEFAULTS = {
        "Hotkeys/F2": "F2",
        "Hotkeys/F3": "F3",
        "Hotkeys/F4": "F4",
        "Image/Format": "WebP",
        "Image/MaxSize": 1600,
        "Image/RetainOriginal": False,
        
        # New AI General Settings (Migrated from old OpenAI settings)
        "AI/Provider": "OpenAI", # Default provider: OpenAI or Gemini
        "AI/Strategy": "Auto",
        "AI/Timeout": 15, # Increased default timeout slightly
        "AI/MaxImages": 8,

        # OpenAI Specific
        "OpenAI/ModelFast": "gpt-4o-mini",
        "OpenAI/ModelDeep": "gpt-4o",

        # Gemini Specific (Using 1.5 Flash for speed and 1.5 Pro for depth)
        "Gemini/ModelFast": "gemini-1.5-flash-latest",
        "Gemini/ModelDeep": "gemini-1.5-pro-latest", # 可替換為 gemini-2.5-pro-latest

        "General/AutoClearQueue": True,
    }

    def __init__(self):
        super().__init__()
        # QSettings uses Organization/Application name (Set in app.py)
        self.settings = QSettings()
        self._default_save_path = os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation), 
            self.SERVICE_NAME
        )
        self._migrate_old_settings()

    def _migrate_old_settings(self):
        """Migrates settings from the old structure (v1) if necessary."""
        # Migrate old OpenAI settings (like Strategy/Timeout) to new AI/ prefix if they exist
        if self.settings.contains("OpenAI/Strategy"):
            print("Migrating old AI settings structure...")
            # Use self.get to respect existing values or use defaults if missing
            self.set("AI/Strategy", self.get("OpenAI/Strategy"))
            self.set("AI/Timeout", self.get("OpenAI/Timeout"))
            self.set("AI/MaxImages", self.get("OpenAI/MaxImages"))
            # Remove old keys that are now generalized
            self.settings.remove("OpenAI/Strategy")
            self.settings.remove("OpenAI/Timeout")
            self.settings.remove("OpenAI/MaxImages")
            self.settings.sync()

    # --- API Key (Keyring) - Generalized ---
    
    def _get_key_name(self, provider: str) -> str:
        if provider == "OpenAI":
            return self.OPENAI_API_KEY_NAME
        elif provider == "Gemini":
            return self.GEMINI_API_KEY_NAME
        raise ValueError(f"Unknown provider: {provider}")

    def get_api_key(self, provider: str) -> str | None:
        try:
            key_name = self._get_key_name(provider)
            return keyring.get_password(self.SERVICE_NAME, key_name)
        except Exception:
            return None

    def set_api_key(self, provider: str, key: str):
        try:
            key_name = self._get_key_name(provider)
            if not key:
                try:
                    keyring.delete_password(self.SERVICE_NAME, key_name)
                except keyring.errors.PasswordDeleteError:
                    pass
            else:
                keyring.set_password(self.SERVICE_NAME, key_name, key)
        except Exception as e:
            raise RuntimeError(f"無法安全儲存 {provider} API Key: {e}")
        # Emit change signal as API key changes affect other components
        self.settings_changed.emit()

    # --- General Settings (QSettings) ---
    
    def get(self, key, default=None):
        if default is None:
            # If no default provided, try to fetch from DEFAULTS dictionary
            default = self.DEFAULTS.get(key)
        
        value = self.settings.value(key, default)
        
        # Handle type conversion (QSettings often stores bool/int as strings)
        if key in self.DEFAULTS:
            # Use the type from the DEFAULTS dict for accurate conversion
            default_type = type(self.DEFAULTS.get(key))
            if default_type is bool:
                return value == 'true' or value is True
            if default_type is int:
                try:
                    return int(value)
                except (ValueError, TypeError):
                    # If conversion fails, return the default value
                    return default
        return value

    def set(self, key, value):
        self.settings.setValue(key, value)

    def save_and_emit(self):
        """Syncs settings to disk and emits the change signal."""
        self.settings.sync()
        self.settings_changed.emit()

    # --- Specific Getters (get_save_path, get_hotkeys, get_image_settings 保持不變) ---
    def get_save_path(self) -> str:
        path = self.get("General/SavePath", self._default_save_path)
        # Ensure the path exists
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                return self._default_save_path # Fallback
        return path

    def get_hotkeys(self) -> dict[str, str]:
        return {
            "F2": self.get("Hotkeys/F2"),
            "F3": self.get("Hotkeys/F3"),
            "F4": self.get("Hotkeys/F4"),
        }

    def get_image_settings(self) -> dict:
        return {
            "format": self.get("Image/Format"),
            "max_size": self.get("Image/MaxSize"),
            "retain_original": self.get("Image/RetainOriginal"),
        }

# Global instance
settings_manager = SettingsManager()