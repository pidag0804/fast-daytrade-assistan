# app.py
from __future__ import annotations
import asyncio
import logging
import sys
from pathlib import Path

from PySide6 import QtCore
from PySide6.QtWidgets import QApplication
import qasync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("app")


def _find_stylesheet() -> Path | None:
    """
    嘗試從以下位置找到 QSS：
    1) 專案根目錄下 assets/styles.qss
    2) 與本檔同層或上層的 assets/styles.qss
    3) 目前工作目錄下 assets/styles.qss
    """
    candidates: list[Path] = []
    here = Path(__file__).resolve()
    # 專案根推測：app.py 位於 <root>/app.py 或 <root>/xxx/app.py
    for parent in [here.parent, here.parent.parent, Path.cwd()]:
        candidates.append(parent / "assets" / "styles.qss")

    # 去重並回傳第一個存在者
    seen = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if p.exists():
            return p
    return None


def _apply_qss(app: QApplication, qss_path: Path) -> None:
    try:
        css = qss_path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning("讀取 QSS 失敗（%s）：%s", qss_path, e)
        return
    app.setStyleSheet(css)
    log.info("已套用樣式：%s", qss_path)


def _watch_qss(app: QApplication, qss_path: Path) -> None:
    """
    使用 QFileSystemWatcher 監看 QSS，有變更就重新套用。
    需把 watcher 綁到 app 上，避免被 GC。
    """
    watcher = getattr(app, "_qss_watcher", None)
    if isinstance(watcher, QtCore.QFileSystemWatcher):
        try:
            watcher.removePaths(watcher.files())
        except Exception:
            pass
    else:
        watcher = QtCore.QFileSystemWatcher()
        app._qss_watcher = watcher  # 綁住

    # 確保路徑存在再加入監看
    if qss_path.exists():
        watcher.addPath(str(qss_path))

    def _on_changed(path: str):
        p = Path(path)
        if not p.exists():
            # 檔案可能被替換，延遲一點點再試著重新加入
            QtCore.QTimer.singleShot(300, lambda: (_find_stylesheet() and _rebind()))
            return
        _apply_qss(app, p)

    def _rebind():
        p = _find_stylesheet()
        if p and p.exists():
            # 重新監看 + 重新套用
            try:
                watcher.removePaths(watcher.files())
            except Exception:
                pass
            watcher.addPath(str(p))
            _apply_qss(app, p)

    watcher.fileChanged.connect(_on_changed)
    # 一開始先套用一次
    _apply_qss(app, qss_path)


async def main():
    """
    正確使用 qasync：
    - 讓 qasync.run() 建立整合事件圈；這裡不要再手動 new QEventLoop 或 run_forever。
    - 建立 QApplication（若已存在就沿用），建立主視窗後，等待「視窗全關」事件。
    """
    app = QApplication.instance() or QApplication(sys.argv)

    # 先套用 QSS（若找到）
    qss = _find_stylesheet()
    if qss:
        _watch_qss(app, qss)
    else:
        log.info("找不到樣式檔 assets/styles.qss（可忽略或稍後補上）。")

    # 延後 import，避免模組在 import 階段意外觸發 Qt 事件圈
    from ui.main_window import MainWindow

    w = MainWindow()
    w.show()

    # 建一個 Future：當最後一個視窗關閉時，把它標記完成，讓 main() 結束
    loop = asyncio.get_running_loop()
    quit_future: asyncio.Future[None] = loop.create_future()

    def _on_last_window_closed():
        if not quit_future.done():
            quit_future.set_result(None)

    app.lastWindowClosed.connect(_on_last_window_closed)

    try:
        await quit_future
    finally:
        log.info("Shutting down application...")
        # 可選：這裡若你有背景 Task，要在此取消並等待
        pending = [
            t
            for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task() and not t.done()
        ]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await loop.shutdown_asyncgens()


if __name__ == "__main__":
    # 交給 qasync.run 建立/管理事件圈；main() 裡不要再新建 QEventLoop
    qasync.run(main())
