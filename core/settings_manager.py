# core/settings_manager.py
from __future__ import annotations
from typing import Dict, Any, Type
from PySide6.QtCore import QObject, Signal, QSettings

class SettingsManager(QObject):
    """
    集中管理所有設定：
    - 寫入後一定呼叫 sync()
    - 立刻回讀核對（抓拼字/型別/命名空間不一致）
    - 以 settingsChanged 廣播完整快照，讓其他模組即時套用
    """
    settingsChanged = Signal(dict)  # 發布「最新完整設定快照」

    # 統一 Key 名稱，避免到處散落與拼字錯誤
    class KEYS:
        OPENAI_MODEL    = "openai/model"
        OPENAI_APIKEY   = "openai/api_key"
        NETWORK_TIMEOUT = "network/timeout"
        IMAGE_QUALITY   = "image/quality"
        HOTKEY_CAPTURE  = "hotkey/capture"

    DEFAULTS: Dict[str, Any] = {
        KEYS.OPENAI_MODEL:    "gpt-4o-mini",
        KEYS.OPENAI_APIKEY:   "",
        KEYS.NETWORK_TIMEOUT: 15,   # 秒
        KEYS.IMAGE_QUALITY:   80,   # 0~100
        KEYS.HOTKEY_CAPTURE:  "F2",
    }

    TYPES: Dict[str, Type] = {
        KEYS.OPENAI_MODEL:    str,
        KEYS.OPENAI_APIKEY:   str,
        KEYS.NETWORK_TIMEOUT: int,
        KEYS.IMAGE_QUALITY:   int,
        KEYS.HOTKEY_CAPTURE:  str,
    }

    def __init__(self) -> None:
        super().__init__()
        self._s = QSettings()  # 請確保外部已設定 Organization/Application 名稱
        self._cache = self._load_all()

    def _load_all(self) -> Dict[str, Any]:
        snap: Dict[str, Any] = {}
        for k, default in self.DEFAULTS.items():
            typ = self.TYPES.get(k, type(default))
            snap[k] = self._s.value(k, default, type=typ)
        return snap

    def snapshot(self) -> Dict[str, Any]:
        # 回傳淺拷貝，避免外部修改內部快取
        return dict(self._cache)

    def get(self, key: str) -> Any:
        return self._cache.get(key, self.DEFAULTS.get(key))

    def update(self, patch: Dict[str, Any]) -> bool:
        """
        原子更新：只對有變更的 key 寫入，sync 後回讀核對；最後更新快取並廣播。
        回傳是否真的有變更。
        """
        # 篩出真的變更
        changed = {k: v for k, v in patch.items() if self._cache.get(k) != v}
        if not changed:
            return False

        # 型別保護：將值轉成宣告型別
        for k, v in changed.items():
            if k in self.TYPES:
                typ = self.TYPES[k]
                try:
                    # bool/int/str 等簡單轉型
                    if typ is bool:
                        v2 = bool(v)
                    elif typ is int:
                        v2 = int(v)
                    elif typ is float:
                        v2 = float(v)
                    elif typ is str:
                        v2 = str(v)
                    else:
                        v2 = v  # 其他自負責
                except Exception as e:
                    raise TypeError(f"設定值型別不正確：{k} 期望 {typ.__name__}，實得 {type(v).__name__}（{v!r}）。錯誤：{e}") from e
                changed[k] = v2

        # 寫入
        for k, v in changed.items():
            self._s.setValue(k, v)
        self._s.sync()
        if self._s.status() != QSettings.NoError:
            raise RuntimeError(f"QSettings sync 失敗，status={self._s.status()}")

        # 立即回讀核對：最容易抓到命名空間/拼字/型別問題
        for k, want in changed.items():
            typ = self.TYPES.get(k, type(want))
            got = self._s.value(k, self.DEFAULTS.get(k), type=typ)
            if got != want:
                raise RuntimeError(
                    f"回讀不一致：{k} want={want!r} got={got!r}。"
                    "請檢查：Organization/Application 名稱是否一致？key 是否拼寫一致？型別是否相容？"
                )

        # 更新快取並廣播
        self._cache.update(changed)
        self.settingsChanged.emit(self.snapshot())
        return True
