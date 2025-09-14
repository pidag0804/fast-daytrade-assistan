import io
import os
import time
from datetime import datetime
from PIL import Image
import numpy as np
from PySide6.QtCore import QObject, Signal, QRunnable, Slot, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPixmap
from core.config import settings_manager

# --- Image Processing Worker (QRunnable for QThreadPool) ---

class ImageSaveWorker(QRunnable):
    """Processes and saves an image in a background thread."""
    
    class Signals(QObject):
        finished = Signal(str) # path
        error = Signal(str)

    def __init__(self, image_input: Image.Image | QImage | np.ndarray):
        super().__init__()
        self.image_input = image_input
        self.signals = self.Signals()

    @Slot()
    def run(self):
        try:
            start_time = time.time()
            settings = settings_manager.get_image_settings()
            save_path_base = settings_manager.get_save_path()

            # 1. Convert input to PIL Image
            if isinstance(self.image_input, QImage):
                image = self.qimage_to_pil(self.image_input)
            elif isinstance(self.image_input, np.ndarray):
                # Assuming BGRA format from mss
                height, width, _ = self.image_input.shape
                image = Image.frombytes("RGB", (width, height), self.image_input.tobytes(), "raw", "BGRX")
            elif isinstance(self.image_input, Image.Image):
                 image = self.image_input
            else:
                 raise TypeError("Unsupported image input type")

            # 2. Generate paths
            now = datetime.now()
            date_folder = now.strftime("%Y-%m-%d")
            timestamp = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            extension = settings['format'].lower()
            
            full_dir = os.path.join(save_path_base, date_folder)
            os.makedirs(full_dir, exist_ok=True)
            
            final_path = os.path.join(full_dir, f"{timestamp}.{extension}")
            original_path = os.path.join(full_dir, f"{timestamp}_original.png")

            # 3. Save Original (if configured)
            # Note: If input was QImage (from editor), we treat it as already processed.
            if settings['retain_original'] and isinstance(self.image_input, np.ndarray):
                image.save(original_path, format="PNG")

            # 4. Resize
            max_size = settings['max_size']
            if image.width > max_size or image.height > max_size:
                image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # 5. Save Final (Optimized)
            save_format = settings['format']
            kwargs = {}
            if save_format.lower() == 'webp':
                kwargs['quality'] = 85
                kwargs['method'] = 4 # Balance speed/compression
            elif save_format.lower() == 'jpeg':
                kwargs['quality'] = 85
                kwargs['optimize'] = True
            
            # Ensure image mode is compatible (e.g., convert RGBA to RGB if necessary)
            if image.mode == 'RGBA' and save_format.lower() != 'png':
                 image = image.convert('RGB')

            image.save(final_path, format=save_format, **kwargs)
            
            end_time = time.time()
            print(f"Image saved in {(end_time - start_time)*1000:.2f} ms: {final_path}")
            self.signals.finished.emit(final_path)

        except Exception as e:
            print(f"Error processing image: {e}")
            self.signals.error.emit(str(e))
        finally:
            if hasattr(self.image_input, 'close') and callable(self.image_input.close):
                 self.image_input.close()

    @staticmethod
    def qimage_to_pil(qimage: QImage) -> Image.Image:
        """Converts QImage to PIL Image reliably."""
        # Use QBuffer to save QImage into memory (as PNG) and then open with PIL
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        qimage.save(buffer, "PNG")
        pil_img = Image.open(io.BytesIO(buffer.data()))
        return pil_img.copy()

# --- Utility Functions ---

def pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    """Converts PIL Image to QPixmap efficiently."""
    buffer = io.BytesIO()
    # Use PNG format for conversion as it supports transparency if present
    save_format = "PNG" if pil_img.mode == 'RGBA' else "JPEG"
    pil_img.save(buffer, format=save_format)
    qpixmap = QPixmap()
    qpixmap.loadFromData(buffer.getvalue(), save_format)
    return qpixmap