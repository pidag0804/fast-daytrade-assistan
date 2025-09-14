# core/imaging.py
from __future__ import annotations
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Union

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

# ========= PIL 轉換工具 =========

def pil_to_qpixmap(pil_image) -> QPixmap:
    """
    將 Pillow Image 轉為 QPixmap。
    - 會自動轉成 RGBA，避免調色盤/灰階模式造成相容問題。
    - 需要安裝 pillow：pip install pillow
    """
    from PIL import Image
    from PIL.ImageQt import ImageQt  # Pillow 9+
    if not isinstance(pil_image, Image.Image):
        raise TypeError("pil_to_qpixmap 需要 Pillow Image 物件")
    if pil_image.mode not in ("RGB", "RGBA"):
        pil_image = pil_image.convert("RGBA")
    qt_img = ImageQt(pil_image)  # 這會回傳 PySide6 的 QImage 相容物件
    if isinstance(qt_img, QImage):
        qimg = qt_img
    else:
        qimg = QImage(qt_img)
    return QPixmap.fromImage(qimg)

def qpixmap_to_pil(pix: QPixmap):
    """
    將 QPixmap 轉為 Pillow Image（方便做進一步處理或轉檔）。
    """
    from PIL.ImageQt import ImageQt
    qimg = pix.toImage()
    return ImageQt(qimg).copy()  # Pillow Image


# ========= 存檔實用工具 =========

def _timestamp_name() -> str:
    # 例：20250914_085556_415（毫秒精度）
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S_") + f"{int(now.microsecond/1000):03d}"

def _ensure_dir(base: str, use_date_subdir: bool = True) -> Path:
    base_path = Path(base)
    if use_date_subdir:
        base_path = base_path / datetime.now().strftime("%Y-%m-%d")
    base_path.mkdir(parents=True, exist_ok=True)
    return base_path

def _qimage_from_any(img: Union[QImage, QPixmap, str]) -> QImage:
    if isinstance(img, QImage):
        return img
    if isinstance(img, QPixmap):
        return img.toImage()
    if isinstance(img, str):
        q = QImage(img)
        if q.isNull():
            raise ValueError(f"Cannot load image from path: {img}")
        return q
    raise TypeError("Unsupported image type; expected QImage/QPixmap/str(path).")

def _qt_save(image: QImage, out_path: Path, fmt_upper: str) -> bool:
    try:
        return image.save(str(out_path), fmt_upper)
    except Exception:
        return False

def _pil_save(image: QImage, out_path: Path, fmt_upper: str) -> bool:
    try:
        from PIL.ImageQt import fromqimage   # Pillow 9+
        pil = fromqimage(image)              # 轉成 PIL Image
        fmt = "JPEG" if fmt_upper in ("JPG", "JPEG") else fmt_upper
        if fmt == "WEBP":
            pil.save(str(out_path), format=fmt, quality=95, method=6)
        else:
            pil.save(str(out_path), format=fmt, optimize=True)
        return True
    except Exception:
        return False

def save_image_sync(
    img: Union[QImage, QPixmap, str],
    base_dir: str,
    preferred_ext: str = "webp",
    use_date_subdir: bool = True,
    prefix: str = "",
) -> str:
    """
    同步存檔：將 QImage/QPixmap/檔案路徑 存成圖片檔。
    回傳：完整檔案路徑。
    """
    qimg = _qimage_from_any(img)
    out_dir = _ensure_dir(base_dir, use_date_subdir)
    ext = preferred_ext.lower().lstrip(".")
    name = (prefix or "") + _timestamp_name() + f".{ext}"
    out_path = out_dir / name

    fmt_upper = ext.upper()
    ok = _qt_save(qimg, out_path, fmt_upper) or _pil_save(qimg, out_path, fmt_upper)
    if not ok:
        # 若仍失敗則退回 PNG
        out_path = out_dir / ((prefix or "") + _timestamp_name() + ".png")
        _qt_save(qimg, out_path, "PNG") or _pil_save(qimg, out_path, "PNG")
    return str(out_path)


# ========= 背景存檔 Worker =========

class _ImageSaveSignals(QObject):
    started = Signal()
    finished = Signal(str, float)   # (saved_path, elapsed_ms)
    error = Signal(str)

@dataclass
class ImageSaveOptions:
    base_dir: str
    preferred_ext: str = "webp"
    use_date_subdir: bool = True
    prefix: str = ""

class ImageSaveWorker(QRunnable):
    """
    將影像在背景執行緒存檔。
    事件：
      - signals.started()
      - signals.finished(path: str, elapsed_ms: float)
      - signals.error(msg: str)
    """
    def __init__(self, image: Union[QImage, QPixmap, str], opts: ImageSaveOptions):
        super().__init__()
        self._image = image
        self._opts = opts
        self.signals = _ImageSaveSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        self.signals.started.emit()
        t0 = time.perf_counter()
        try:
            saved = save_image_sync(
                self._image,
                base_dir=self._opts.base_dir,
                preferred_ext=self._opts.preferred_ext,
                use_date_subdir=self._opts.use_date_subdir,
                prefix=self._opts.prefix,
            )
            ms = (time.perf_counter() - t0) * 1000.0
            self.signals.finished.emit(saved, ms)
        except Exception as e:
            self.signals.error.emit(str(e))

def save_image_async(
    image: Union[QImage, QPixmap, str],
    opts: ImageSaveOptions,
    on_done=None, on_error=None, on_started=None,
):
    """
    便利函式：啟動背景存檔並綁定回呼。
    """
    worker = ImageSaveWorker(image, opts)
    if on_started:
        worker.signals.started.connect(on_started)
    if on_done:
        worker.signals.finished.connect(on_done)
    if on_error:
        worker.signals.error.connect(on_error)
    QThreadPool.globalInstance().start(worker)
    return worker
